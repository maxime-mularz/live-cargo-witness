"""A scripted stand-in for Muse Spark Open, for testing the agent loop's plumbing only.

It reads expected.json (through tests/helpers.py) to know which tool calls to emit, so it proves
nothing about the real agent's quality. Never use it to produce a published score.
"""
from __future__ import annotations

import copy
import json

from helpers import scripted_run


class ScriptedClient:
    model_name = "scripted test client (not a model)"

    def __init__(self, folder, bad_first_submission: bool = False, draft_for: str | None = None):
        tools, pre, claims, result = scripted_run(folder)
        self.dossier = tools.dossier
        self.pre = pre
        pre_claims = [c for c in claims if c["kind"] == "pre_departure"]
        dev_claims = [c for c in claims if c["kind"] == "deviation"]

        stage1 = [("read_document", {"document": d, "reason": f"Read the {d} to check R01–R03."})
                  for d in tools.dossier.record["documents"]]
        stage1 += [("segment_crate", {"photo": p.split("/")[-1].removesuffix(".png"),
                                      "reason": "Check label, arrows and plate on this crate."})
                   for p in tools.dossier.record.get("photos", [])]
        if pre_claims:
            stage1.append(("write_case_file", {"claims": pre_claims, "reason": "Record the violated rules."}))
        stage1.append(("final", {"decision": pre["decision"], "violated_rules": pre["violated_rules"],
                                 "summary": "Pre-departure check done."}))

        stage2 = [("get_sensor_curve", {"reason": "Look for deviations in the sensor log."})]
        asked = next((c for c in dev_claims
                      if any(e["type"] == "handler_answer" for e in c["evidence"])), None)
        if asked:
            stage2.append(("ask_handler", {"question": "What happened to the crates during this interval?",
                                           "start": asked["interval"]["start"], "end": asked["interval"]["end"],
                                           "reason": "No note explains this deviation."}))
        if dev_claims:
            if bad_first_submission:
                bad = copy.deepcopy(dev_claims)
                bad[0]["statement"] += " About 37 crates were affected."
                stage2.append(("write_case_file", {"claims": bad, "reason": "Record the deviations."}))
            stage2.append(("write_case_file", {"claims": dev_claims, "reason": "Record the deviations."}))
        if draft_for:  # off by default: the dry run never drafts, as the real agent may not
            stage2.append(("draft_notification", {"recipient": draft_for, "reason": "Prepare the draft."}))
        stage2.append(("final", {"summary": "Investigation done."}))
        self.plans = {"STAGE 1": stage1, "STAGE 2": stage2}
        self.calls = 0

    def chat(self, messages, tools):
        system = messages[0]["content"]
        stage = "STAGE 1" if "STAGE 1" in system else "STAGE 2"
        done = sum(1 for m in messages if m["role"] == "assistant")
        name, arguments = self.plans[stage][done]
        self.calls += 1
        if name == "final":
            return {"content": json.dumps(arguments), "tool_calls": []}
        return {"content": None, "tool_calls": [{"id": f"call_{self.calls}", "name": name,
                                                  "arguments": copy.deepcopy(arguments)}]}
