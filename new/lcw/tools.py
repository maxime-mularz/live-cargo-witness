"""The agent's tools (contract in CLAUDE.md).

``Toolset(dossier, backend="offline")`` answers from the dossier's ground-truth files and recorded
answers — for tests and for the scoring plumbing only. ``backend="live"`` calls ``lcw.models``.
Every tool call is appended to ``journal`` and every reading to ``observations`` (what the
verifier later checks claims against).
"""

from __future__ import annotations

from datetime import datetime, timezone

from . import models
from .deviations import detect, values_in
from .dossier import Dossier, load_json, parse_ts
from .phases import segment
from .rules import load_rules

MODEL_FOR_TOOL = {
    "read_document": "Muse Spark Open",
    "segment_crate": "SAM 3.1",
    "get_sensor_curve": "deterministic (lcw.deviations)",
    "lookup_rule": "deterministic (rule cards)",
    "ask_handler": "Muse Voice Transcribe",
    "draft_notification": "template",
    "write_case_file": "lcw.verifier + lcw.casefile",
    "convoy_notes": "Muse Voice Transcribe",
}

REASON = {"type": "string",
          "description": "One sentence: why you call this tool now (your current hypothesis). "
                         "Shown in the investigation journal."}

EVIDENCE_ITEM = {
    "type": "object", "required": ["type"],
    "description": "One piece of evidence. Types: curve_segment {series, start, end}; "
                   "dossier_field {path}; document_field {document, field}; "
                   "crate_feature {photo, feature}; voice_note {id}; handler_answer {id}; "
                   "inspection_window {id}.",
    "properties": {
        "type": {"type": "string", "enum": ["curve_segment", "dossier_field", "document_field",
                                            "crate_feature", "voice_note", "handler_answer",
                                            "inspection_window"]},
        "series": {"type": "string", "enum": ["temperature_c", "light_lux", "shock_g"]},
        "start": {"type": "string"}, "end": {"type": "string"},
        "path": {"type": "string"}, "document": {"type": "string"}, "field": {"type": "string"},
        "photo": {"type": "string"}, "feature": {"type": "string"}, "id": {"type": "string"},
    },
}

CLAIM_ITEM = {
    "type": "object", "required": ["id", "kind", "rule", "status", "statement", "evidence"],
    "properties": {
        "id": {"type": "string", "description": "C1, C2, ... (reuse an id to replace a rejected claim)"},
        "kind": {"type": "string", "enum": ["pre_departure", "deviation"]},
        "rule": {"type": "string", "description": "R01 to R10"},
        "status": {"type": "string", "enum": ["violated", "satisfied", "explained_compliant",
                                              "explained_rule_exceeded", "false_positive_dismissed",
                                              "indeterminate"]},
        "interval": {"type": "object", "properties": {"start": {"type": "string"},
                                                       "end": {"type": "string"}},
                     "description": "deviation claims only: start and end of the deviation"},
        "statement": {"type": "string", "description": "One factual sentence. Every number, time and "
                      "date in it must come from the cited evidence."},
        "evidence": {"type": "array", "items": EVIDENCE_ITEM},
    },
}

TOOL_SCHEMAS = [
    {"name": "read_document",
     "description": "Read a shipping document image and return its fields.",
     "parameters": {"type": "object", "required": ["document"], "properties": {
         "reason": REASON,
         "document": {"type": "string", "enum": ["awb", "certification", "loading_list"]}}}},
    {"name": "segment_crate",
     "description": "Segment a crate photo: 'Live Animals' label, orientation arrows and their "
                    "direction, air waybill number plate.",
     "parameters": {"type": "object", "required": ["photo"], "properties": {
         "reason": REASON,
         "photo": {"type": "string", "description": "e.g. crate_01"}}}},
    {"name": "get_sensor_curve",
     "description": "Flight phases and deviations from the rule cards on the sensor curve. "
                    "With start/end, also returns the raw samples of that interval.",
     "parameters": {"type": "object", "properties": {
         "reason": REASON,
         "start": {"type": "string"}, "end": {"type": "string"}}}},
    {"name": "lookup_rule",
     "description": "Return a rule card (R01–R10) with its source.",
     "parameters": {"type": "object", "required": ["rule"], "properties": {
         "reason": REASON, "rule": {"type": "string"}}}},
    {"name": "ask_handler",
     "description": "Ask the ground handler about an interval. Use only when a deviation has no "
                    "explanation in the convoy notes or the entry record.",
     "parameters": {"type": "object", "required": ["question", "start", "end"], "properties": {
         "reason": REASON,
         "question": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"}}}},
    {"name": "draft_notification",
     "description": "Draft (never send) a message to one of the three signatories.",
     "parameters": {"type": "object", "required": ["recipient", "summary"], "properties": {
         "reason": REASON,
         "recipient": {"type": "string", "enum": ["shipper", "carrier", "handler"]},
         "summary": {"type": "string"}}}},
    {"name": "write_case_file",
     "description": "Submit claims for the shared handover record. Claims are checked by the "
                    "non-AI verifier; rejected claims come back with reasons.",
     "parameters": {"type": "object", "required": ["claims"], "properties": {
         "reason": REASON,
         "claims": {"type": "array", "items": CLAIM_ITEM}}}},
]


class Toolset:
    def __init__(self, dossier: Dossier, backend: str = "offline", rules=None):
        if backend not in ("offline", "live"):
            raise ValueError(backend)
        self.dossier = dossier
        self.backend = backend
        self.rules = rules or load_rules()
        self.journal: list[dict] = []
        self.observations: dict = {
            "documents": {}, "crates": {}, "handler_answers": [],
            # every crate photo of the dossier must be segmented before a decision
            "expected_crates": [p.split("/")[-1].removesuffix(".png")
                                for p in dossier.record.get("photos", [])],
        }
        self.drafts: list[dict] = []
        self.accepted: list[dict] = []
        self.stage: str | None = None     # set by the agent loop ("pre_departure" / "investigation")
        self.reason: str | None = None    # the model's stated reason for the current call

    def _log(self, tool: str, arguments: dict, result) -> None:
        self.journal.append({
            "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "type": "tool", "stage": self.stage, "reason": self.reason,
            "tool": tool, "model": MODEL_FOR_TOOL[tool], "backend": self.backend,
            "arguments": arguments, "result": result,
        })
        self.reason = None

    # ------------------------------------------------------------------ tools

    def read_document(self, document: str) -> dict:
        if document not in self.dossier.record["documents"]:
            raise KeyError(f"no document {document!r} in this dossier")
        if self.backend == "offline":
            truth = self.dossier.document_truth(document)
            fields = {k: v["value"] for k, v in truth["fields"].items()}
            fields["_regions"] = {k: v["bbox"] for k, v in truth["fields"].items() if v.get("bbox")}
        else:
            fields = models.read_document_image(self.dossier.path(self.dossier.record["documents"][document]), document)
        self.observations["documents"][document] = {k: v for k, v in fields.items() if not k.startswith("_")}
        self._log("read_document", {"document": document}, fields)
        return fields

    def segment_crate(self, photo: str) -> dict:
        path = f"photos/{photo}.png"
        if path not in self.dossier.record.get("photos", []):
            raise KeyError(f"no photo {photo!r} in this dossier")
        if self.backend == "offline":
            features = load_json(self.dossier.path(f"photos/{photo}.truth.json"))["features"]
        else:
            features = models.segment_crate_image(self.dossier.path(path))
        self.observations["crates"][photo] = features
        self._log("segment_crate", {"photo": photo}, features)
        return features

    def get_sensor_curve(self, start: str | None = None, end: str | None = None) -> dict:
        curve = self.dossier.curve()
        if curve is None:
            result = {"available": False, "reason": "no sensor curve (departure blocked or no sensor)"}
        else:
            phases = segment(self.dossier.record)
            found = detect(curve, phases, self.rules, self.dossier.record)
            result = {"available": True, "synthetic": self.dossier.synthetic, "samples": len(curve),
                      "phases": phases, **found}
            if start and end:
                result["window"] = [row for row in curve
                                    if parse_ts(start) <= parse_ts(row["timestamp"]) <= parse_ts(end)]
        self._log("get_sensor_curve", {"start": start, "end": end}, result)
        return result

    def lookup_rule(self, rule: str) -> dict:
        card = self.rules[rule].raw
        self._log("lookup_rule", {"rule": rule}, card)
        return card

    def ask_handler(self, question: str, start: str, end: str) -> dict:
        first, last = parse_ts(start), parse_ts(end)
        chosen = None
        for answer in self.dossier.handler_answers():
            if answer.get("default"):
                continue
            if parse_ts(answer["start"]) <= last and parse_ts(answer["end"]) >= first:
                chosen = answer
                break
        if chosen is None:
            chosen = next((a for a in self.dossier.handler_answers() if a.get("default")),
                          {"id": "H0", "answer": "No answer recorded."})
        audio = self._audio(chosen)
        if self.backend == "live" and audio:
            text = models.transcribe(audio)
        else:
            text = chosen["answer"]
        result = {"id": chosen["id"], "question": question, "asked_start": start, "asked_end": end,
                  # the interval the recorded answer is about (None for the default answer)
                  "start": chosen.get("start"), "end": chosen.get("end"),
                  "default": bool(chosen.get("default")), "answer": text}
        self.observations["handler_answers"].append(result)
        self._log("ask_handler", {"question": question, "start": start, "end": end}, result)
        return result

    def _audio(self, item: dict):
        """Recording of a note or answer: the ``audio`` field, else ``voice/audio/<id>.<ext>``."""
        if item.get("audio"):
            return self.dossier.path(item["audio"])
        folder = self.dossier.root / "voice" / "audio"
        for extension in ("m4a", "mp3", "wav", "ogg", "webm"):
            candidate = folder / f"{item.get('id')}.{extension}"
            if candidate.exists():
                return candidate
        return None

    def convoy_notes(self) -> list[dict]:
        """Convoy attendant's notes, transcribed (Muse Voice Transcribe in live mode when the
        note has an audio file; the stored transcript otherwise)."""
        notes = []
        for note in self.dossier.convoy_notes():
            text = note["text"]
            audio = self._audio(note)
            if self.backend == "live" and audio:
                text = models.transcribe(audio)
            notes.append({"id": note["id"], "time": note["time"], "text": text})
        self._log("convoy_notes", {}, notes)
        return notes

    def entry_record(self) -> dict:
        """What the agent may know from the entry record (never expected.json)."""
        record = self.dossier.record
        keys = ("id", "synthetic", "route", "schedule", "phase_model", "declared", "sensor")
        entry = {k: record[k] for k in keys if k in record}
        entry["documents"] = sorted(record.get("documents", {}))
        entry["photos"] = self.observations["expected_crates"]
        entry["sensor_curve_available"] = bool(record.get("sensor_curve"))
        return entry

    def draft_notification(self, recipient: str, summary: str) -> dict:
        draft = {"recipient": recipient, "status": "draft — not sent", "body": summary}
        self.drafts.append(draft)
        self._log("draft_notification", {"recipient": recipient}, draft)
        return draft

    def write_case_file(self, claims: list[dict]) -> dict:
        """Run the non-AI verifier. Accepted claims are kept for the record; rejected ones come
        back with their reasons so the agent can correct them."""
        from .verifier import Verifier

        report = Verifier(self.dossier, self.rules, self.observations).check(claims)
        accepted_ids = {c["id"] for c in report["accepted"]}
        self.accepted = [c for c in self.accepted if c["id"] not in accepted_ids]
        self.accepted += report["accepted"]
        summary = {"accepted": sorted(accepted_ids),
                   "rejected": [{"id": r["claim"].get("id"), "reasons": r["reasons"]}
                                for r in report["rejected"]]}
        self._log("write_case_file", {"claims": [c.get("id") for c in claims]}, summary)
        return summary

    def values(self, series: str, start: str, end: str) -> list[float]:
        return values_in(self.dossier.curve() or [], series, start, end)
