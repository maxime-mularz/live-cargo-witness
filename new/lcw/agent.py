"""The investigation loop.

Two stages, as in real life:

1. **Pre-departure** (connected, before loading): read the documents, segment the crates, submit
   claims for violated rules, decide go / block.
2. **Investigation** (first network contact after the flight), only if the consignment flew:
   sensor curve, convoy notes, ground handler when needed, one claim per deviation.

The model (Muse Spark Open in production) chooses every tool call. The loop only dispatches
calls, feeds results back, and stops when the model answers without a tool call. Malformed model
output (missing tool name, arguments as a JSON string, prose around the final JSON, "GO" instead
of "go") is tolerated where the intent is unambiguous and reported to the model otherwise.

The model client must expose ``chat(messages, tools) -> {"content": str | None,
"tool_calls": [{"id": str, "name": str, "arguments": dict}]}`` — see ``lcw.models.chat``.
Messages use the roles system / user / assistant / tool.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Protocol

from . import models
from .env import redact
from .jsonutil import final_json
from .predeparture import evaluate
from .prompts import INVESTIGATION, PRE_DEPARTURE
from .tools import TOOL_SCHEMAS, Toolset

MAX_RESULT_CHARS = 12000
RULE_ID = re.compile(r"^R\d{2}$")
STAGE_TOOLS = {
    "pre_departure": {"read_document", "segment_crate", "lookup_rule", "write_case_file"},
    "investigation": {"get_sensor_curve", "lookup_rule", "ask_handler", "draft_notification",
                      "write_case_file"},
}


class ModelClient(Protocol):
    def chat(self, messages: list[dict], tools: list[dict]) -> dict: ...


class MetaModelClient:
    """Production client: Muse Spark Open through ``lcw.models.chat`` (or Muse Spark when
    ``LCW_ORCHESTRATOR=spark``, the CA-02 fallback)."""

    @property
    def model_name(self) -> str:
        return models.orchestrator_name()

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        return models.chat(messages, tools)


@dataclass
class StageOutcome:
    final: dict | None
    steps: int
    error: str | None = None
    messages: list[dict] = field(default_factory=list)


@dataclass
class AgentRun:
    dossier_id: str
    pre_departure: StageOutcome
    investigation: StageOutcome | None
    deterministic_pre_departure: dict
    result: dict


# ---------------------------------------------------------------------- parsing helpers

def normalise_decision(final: dict | None) -> tuple[str | None, list[str], list[str]]:
    """Return (decision, violated_rules, problems) from the stage-1 final JSON."""
    problems: list[str] = []
    final = final or {}
    decision = final.get("decision")
    decision = decision.strip().lower() if isinstance(decision, str) else None
    if decision not in ("go", "block"):
        problems.append(f"decision must be 'go' or 'block', got {final.get('decision')!r}")
        decision = None
    raw = final.get("violated_rules", [])
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        problems.append("violated_rules must be a list")
        raw = []
    rules = sorted({r.strip().upper() for r in raw if isinstance(r, str) and RULE_ID.match(r.strip().upper())})
    if len(rules) != len([r for r in raw if r]):
        problems.append(f"ignored invalid entries in violated_rules: {raw!r}")
    return decision, rules, problems


def usage_summary(calls: list[dict], seconds: float) -> dict:
    """Model calls of one run, per model (CA-12: time and cost per dossier). Token counts are
    those the providers report; calls that report none are counted apart, never as zero."""
    by_model: dict[str, dict] = {}
    for call in calls:
        entry = by_model.setdefault(call.get("model", "?"), {
            "calls": 0, "failed": 0, "attempts": 0, "prompt_tokens": 0, "completion_tokens": 0,
            "calls_without_tokens": 0})
        entry["calls"] += 1
        entry["attempts"] += call.get("attempts") or 1
        if call.get("failed"):
            entry["failed"] += 1
        elif isinstance(call.get("prompt_tokens"), int) and isinstance(call.get("completion_tokens"), int):
            entry["prompt_tokens"] += call["prompt_tokens"]
            entry["completion_tokens"] += call["completion_tokens"]
        else:
            entry["calls_without_tokens"] += 1
    return {"model_calls": len(calls), "seconds": round(seconds, 1), "by_model": by_model}


def _arguments(call: dict) -> dict:
    arguments = call.get("arguments")
    if arguments is None:
        return {}
    if isinstance(arguments, str):
        arguments = json.loads(arguments) if arguments.strip() else {}
    if not isinstance(arguments, dict):
        raise ValueError("tool arguments must be a JSON object")
    return arguments


def _clip(value) -> str:
    """Serialise a tool result for the model; oversized results stay valid JSON."""
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= MAX_RESULT_CHARS:
        return text
    return json.dumps({"truncated": True,
                       "note": "result too long: ask for a shorter interval or a single item",
                       "preview": text[:MAX_RESULT_CHARS // 2]}, ensure_ascii=False)


# ---------------------------------------------------------------------- the agent

class Agent:
    def __init__(self, tools: Toolset, client: ModelClient | None = None, max_steps: int = 40):
        self.tools = tools
        self.client = client or MetaModelClient()
        self.max_steps = max_steps

    def _call(self, name: str | None, arguments: dict):
        if not name:
            raise ValueError("tool call without a name")
        arguments = dict(arguments)
        reason = arguments.pop("reason", None)
        if reason is not None and not isinstance(reason, str):
            reason = json.dumps(reason, ensure_ascii=False, default=str)
        self.tools.reason = reason
        if name not in STAGE_TOOLS[self.tools.stage]:
            raise ValueError(f"tool {name!r} is not available at stage {self.tools.stage}")
        return getattr(self.tools, name)(**arguments)

    def _note_message(self, content: str | None) -> None:
        if content and content.strip():
            self.tools.journal.append({"type": "message", "stage": self.tools.stage,
                                       "model": getattr(self.client, "model_name", "unknown model"),
                                       "content": content.strip()})

    def _loop(self, stage: str, system: str, user: str,
              keys: tuple[str, ...] = ("decision", "summary")) -> StageOutcome:
        self.tools.stage = stage
        tools = [t for t in TOOL_SCHEMAS if t["name"] in STAGE_TOOLS[stage]]
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        for step in range(1, self.max_steps + 1):
            try:
                reply = self.client.chat(messages, tools) or {}
            except Exception as error:
                return StageOutcome(None, step, f"model call failed: {type(error).__name__}: "
                                                f"{redact(error)}", messages)
            content, calls = reply.get("content"), reply.get("tool_calls") or []
            messages.append({"role": "assistant", "content": content, "tool_calls": calls})
            if not calls:
                self._note_message(content)
                final = final_json(content, keys)
                if final is None:
                    return StageOutcome(None, step, "final answer is not JSON", messages)
                return StageOutcome(final, step, None, messages)
            for call in calls:
                name = call.get("name") if isinstance(call, dict) else None
                try:
                    result = self._call(name, _arguments(call))
                except Exception as error:  # the model sees the error and can recover
                    message = redact(f"{type(error).__name__}: {error}")
                    result = {"error": message}
                    self.tools.journal.append({"type": "error", "stage": stage, "tool": name,
                                               "error": message})
                    self.tools.reason = None
                messages.append({"role": "tool", "tool_call_id": call.get("id") if isinstance(call, dict) else None,
                                 "name": name, "content": _clip(result)})
        return StageOutcome(None, self.max_steps, f"no final answer after {self.max_steps} steps", messages)

    def run(self) -> AgentRun:
        started, calls_before = time.monotonic(), len(models.USAGE)
        entry = self.tools.entry_record()
        pre = self._loop("pre_departure", PRE_DEPARTURE,
                         "Entry record:\n" + json.dumps(entry, ensure_ascii=False, indent=1),
                         keys=("decision",))
        deterministic = evaluate(self.tools.rules, self.tools.observations)
        decision, violated, problems = normalise_decision(pre.final)
        if pre.final is not None and problems:
            pre.error = "; ".join(problems) if decision is None else pre.error

        investigation = None
        if decision == "go" and entry["sensor_curve_available"]:
            self.tools.stage = "investigation"
            try:
                notes = self.tools.convoy_notes()
            except Exception as error:
                notes = []
                self.tools.journal.append({"type": "error", "stage": "investigation", "tool": "convoy_notes",
                                           "error": redact(f"{type(error).__name__}: {error}")})
            context = {"entry_record": entry,
                       "pre_departure": {"decision": decision,
                                         "accepted_claims": [c["id"] for c in self.tools.accepted]},
                       "convoy_notes": notes}
            investigation = self._loop("investigation", INVESTIGATION,
                                       json.dumps(context, ensure_ascii=False, indent=1), keys=("summary",))

        deviations = [{"rule": c["rule"], "start": c["interval"]["start"], "end": c["interval"]["end"],
                       "status": c["status"]}
                      for c in self.tools.accepted if c.get("kind") == "deviation"]
        handler_called = any(e.get("type") == "tool" and e.get("tool") == "ask_handler"
                             for e in self.tools.journal)
        errors = [e for e in (pre.error, investigation.error if investigation else None) if e]
        result = {
            "dossier_id": self.tools.dossier.id,
            "phase1": {"decision": decision, "violated_rules": violated},
            "investigation": None if investigation is None else
            {"handler_called": handler_called, "deviations": deviations},
            "errors": errors,
            "warnings": problems,
            "decision_matches_readings": decision == deterministic["decision"],
            "usage": usage_summary(models.USAGE[calls_before:], time.monotonic() - started),
        }
        return AgentRun(self.tools.dossier.id, pre, investigation, deterministic, result)
