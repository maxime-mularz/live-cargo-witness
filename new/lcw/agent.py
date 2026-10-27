"""The investigation loop.

Two stages, as in real life:

1. **Pre-departure** (connected, before loading): read the documents, segment the crates, submit
   claims for violated rules, decide go / block.
2. **Investigation** (first network contact after the flight), only if the consignment flew:
   sensor curve, convoy notes, ground handler when needed, one claim per deviation.

The model (Muse Spark Open in production) chooses every tool call. The loop only dispatches
calls, feeds results back, and stops when the model answers without a tool call.

The model client must expose ``chat(messages, tools) -> {"content": str | None,
"tool_calls": [{"id": str, "name": str, "arguments": dict}]}`` — see ``lcw.models.chat``.
Messages use the roles system / user / assistant / tool.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Protocol

from . import models
from .predeparture import evaluate
from .prompts import INVESTIGATION, PRE_DEPARTURE
from .tools import TOOL_SCHEMAS, Toolset

MAX_RESULT_CHARS = 12000
STAGE_TOOLS = {
    "pre_departure": {"read_document", "segment_crate", "lookup_rule", "write_case_file"},
    "investigation": {"get_sensor_curve", "lookup_rule", "ask_handler", "draft_notification",
                      "write_case_file"},
}


class ModelClient(Protocol):
    def chat(self, messages: list[dict], tools: list[dict]) -> dict: ...


class MetaModelClient:
    """Production client: Muse Spark Open through ``lcw.models.chat``."""

    model_name = "Muse Spark Open"

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


def _json_from_text(text: str | None) -> dict | None:
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _clip(value) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + '..."[truncated: ask for a shorter interval]"'
    return text


class Agent:
    def __init__(self, tools: Toolset, client: ModelClient | None = None, max_steps: int = 40):
        self.tools = tools
        self.client = client or MetaModelClient()
        self.max_steps = max_steps

    # ------------------------------------------------------------------ dispatch

    def _call(self, name: str, arguments: dict):
        arguments = dict(arguments or {})
        self.tools.reason = arguments.pop("reason", None)
        if name not in STAGE_TOOLS[self.tools.stage]:
            raise ValueError(f"tool {name!r} is not available at stage {self.tools.stage}")
        method = getattr(self.tools, name)
        return method(**arguments)

    def _note_message(self, content: str | None) -> None:
        if content and content.strip():
            self.tools.journal.append({"type": "message", "stage": self.tools.stage,
                                       "model": getattr(self.client, "model_name", "unknown model"),
                                       "content": content.strip()})

    def _loop(self, stage: str, system: str, user: str) -> StageOutcome:
        self.tools.stage = stage
        tools = [t for t in TOOL_SCHEMAS if t["name"] in STAGE_TOOLS[stage]]
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        for step in range(1, self.max_steps + 1):
            reply = self.client.chat(messages, tools)
            content, calls = reply.get("content"), reply.get("tool_calls") or []
            messages.append({"role": "assistant", "content": content, "tool_calls": calls})
            if not calls:
                self._note_message(content)
                final = _json_from_text(content)
                if final is None:
                    return StageOutcome(None, step, "final answer is not JSON", messages)
                return StageOutcome(final, step, None, messages)
            for call in calls:
                try:
                    result = self._call(call["name"], call.get("arguments") or {})
                except Exception as error:  # the model sees the error and can recover
                    result = {"error": f"{type(error).__name__}: {error}"}
                    self.tools.journal.append({"type": "error", "stage": stage, "tool": call["name"],
                                               "arguments": call.get("arguments"), "error": result["error"]})
                    self.tools.reason = None
                messages.append({"role": "tool", "tool_call_id": call.get("id"), "name": call["name"],
                                 "content": _clip(result)})
        return StageOutcome(None, self.max_steps, f"no final answer after {self.max_steps} steps", messages)

    # ------------------------------------------------------------------ stages

    def run(self) -> AgentRun:
        entry = self.tools.entry_record()
        pre = self._loop("pre_departure", PRE_DEPARTURE,
                         "Entry record:\n" + json.dumps(entry, ensure_ascii=False, indent=1))
        deterministic = evaluate(self.tools.rules, self.tools.observations)
        decision = (pre.final or {}).get("decision")
        violated = sorted((pre.final or {}).get("violated_rules") or [])

        investigation = None
        if decision == "go" and entry["sensor_curve_available"]:
            self.tools.stage = "investigation"
            notes = self.tools.convoy_notes()
            accepted_pre = [c["id"] for c in self.tools.accepted]
            context = {"entry_record": entry,
                       "pre_departure": {"decision": decision, "accepted_claims": accepted_pre},
                       "convoy_notes": notes}
            investigation = self._loop("investigation", INVESTIGATION,
                                       json.dumps(context, ensure_ascii=False, indent=1))

        deviations = [{"rule": c["rule"], "start": c["interval"]["start"], "end": c["interval"]["end"],
                       "status": c["status"]}
                      for c in self.tools.accepted if c.get("kind") == "deviation"]
        handler_called = any(e.get("tool") == "ask_handler" for e in self.tools.journal)
        result = {
            "dossier_id": self.tools.dossier.id,
            "phase1": {"decision": decision, "violated_rules": violated},
            "investigation": None if investigation is None else
            {"handler_called": handler_called, "deviations": deviations},
            "errors": [e for e in (pre.error, investigation.error if investigation else None) if e],
            "decision_matches_readings": decision == deterministic["decision"],
        }
        return AgentRun(self.tools.dossier.id, pre, investigation, deterministic, result)
