"""The agent's tools (contract in CLAUDE.md).

``Toolset(dossier, backend="offline")`` answers from the dossier's ground-truth files and recorded
answers — for tests and for the scoring plumbing only. ``backend="live"`` calls ``lcw.models``.
Every tool call is appended to ``journal`` and every reading to ``observations`` (what the
verifier later checks claims against).
"""

from __future__ import annotations

from datetime import UTC, datetime

from . import models
from .deviations import detect, values_in
from .dossier import Dossier, format_ts, load_json, parse_ts
from .drafts import RECIPIENTS, render_draft
from .env import redact
from .phases import segment
from .rules import load_rules

MODEL_FOR_TOOL = {
    "read_document": "Muse Spark Open",
    "segment_crate": "SAM 3.1 + Muse Spark Open",
    "get_sensor_curve": "deterministic (lcw.deviations)",
    "lookup_rule": "deterministic (rule cards)",
    "ask_handler": "Muse Voice Transcribe",
    "draft_notification": "template",
    "write_case_file": "lcw.verifier + lcw.casefile",
    "convoy_notes": "Muse Voice Transcribe",
}
# Label used when a voice item has no recording, or in offline mode: no model was involved.
STORED_TEXT = "stored transcript (no recording)"
MAX_WINDOW_ROWS = 72  # raw samples returned for one interval (6 h at 5-minute sampling)
CLAIM_KIND_FOR_STAGE = {"pre_departure": "pre_departure", "investigation": "deviation"}

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
     "description": "Draft (never send) a message to one of the three signatories. The body is a "
                    "fixed template filled with the claims the verifier has accepted so far.",
     "parameters": {"type": "object", "required": ["recipient"], "properties": {
         "reason": REASON,
         "recipient": {"type": "string", "enum": list(RECIPIENTS)}}}},
    {"name": "write_case_file",
     "description": "Submit claims for the shared handover record. Claims are checked by the "
                    "non-AI verifier; rejected claims come back with reasons.",
     "parameters": {"type": "object", "required": ["claims"], "properties": {
         "reason": REASON,
         "claims": {"type": "array", "items": CLAIM_ITEM}}}},
]



def _utc(value):
    """``value`` rewritten in UTC (``...Z``) when it is a timestamp, keeping any fraction of a second
    (truncating it could make an interval the verifier rejects pass); anything else is returned as
    is, for the verifier to judge as sent."""
    if not isinstance(value, str):
        return value
    try:
        moment = parse_ts(value)
    except (ValueError, OverflowError):
        return value
    if moment.microsecond:
        return moment.isoformat(timespec="microseconds").replace("+00:00", "Z")
    return format_ts(moment)


def _rewritten(sent: dict, checked: dict) -> list[str]:
    """``sent -> checked`` for each start/end the UTC rewrite changed, so a rejection can be explained
    in terms of what the model sent."""
    pairs = [(sent.get("interval"), checked.get("interval"))]
    pairs += list(zip(sent.get("evidence") or [], checked.get("evidence") or [], strict=False))
    changes = []
    for before, after in pairs:
        if isinstance(before, dict) and isinstance(after, dict):
            changes += [f"{before[k]} is {after[k]}" for k in ("start", "end")
                        if k in before and before[k] != after[k]]
    return changes


def _in_utc(claim: dict) -> dict:
    """Copy of a submitted claim with the start/end of its interval and curve segments in UTC.
    The record, the drafts and the journal print HH:MM UTC from these strings, so 18:15+05:00 must
    become 13:15Z before the verifier checks it (dates included), never be printed as 18:15 UTC."""
    claim = dict(claim)
    if isinstance(claim.get("interval"), dict):
        claim["interval"] = {k: _utc(v) if k in ("start", "end") else v for k, v in claim["interval"].items()}
    if isinstance(claim.get("evidence"), list):
        claim["evidence"] = [{k: _utc(v) if k in ("start", "end") else v for k, v in item.items()}
                             if isinstance(item, dict) and item.get("type") == "curve_segment" else item
                             for item in claim["evidence"]]
    return claim


class Toolset:
    def __init__(self, dossier: Dossier, backend: str = "offline", rules=None,
                 allow_real_data: bool = False):
        if backend not in ("offline", "live"):
            raise ValueError(backend)
        if backend == "live" and not dossier.synthetic and not allow_real_data:
            # CLAUDE.md rule 2: no client document, photo, curve or recording is sent to any API
            # without the client's written consent (and never on free credits, whose prompts
            # may be used for product improvement).
            raise ValueError(f"{dossier.id} is not marked synthetic: refusing to send it to the model APIs")
        self.dossier = dossier
        self.backend = backend
        self.rules = rules or load_rules()
        self.journal: list[dict] = []
        self.observations: dict = {
            "documents": {}, "crates": {}, "handler_answers": [], "convoy_notes": [],
            # every crate photo of the dossier must be segmented before a decision
            "expected_crates": [p.split("/")[-1].removesuffix(".png")
                                for p in dossier.record.get("photos", [])],
        }
        self.drafts: list[dict] = []
        self.accepted: list[dict] = []
        self.claim_stage: dict[str, str] = {}  # claim id -> stage where it was first accepted
        self.stage: str | None = None     # set by the agent loop ("pre_departure" / "investigation")
        self.reason: str | None = None    # the model's stated reason for the current call

    def _log(self, tool: str, arguments: dict, result, model: str | None = None) -> None:
        self.journal.append({
            "time": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "type": "tool", "stage": self.stage, "reason": self.reason,
            "tool": tool, "model": model or MODEL_FOR_TOOL[tool], "backend": self.backend,
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
        start, end = _utc(start), _utc(end)  # logged and used in UTC, like claims
        curve = self.dossier.curve()
        if curve is None:
            result = {"available": False, "reason": "no sensor curve (departure blocked or no sensor)"}
        else:
            phases = segment(self.dossier.record)
            found = detect(curve, phases, self.rules, self.dossier.record)
            result = {"available": True, "synthetic": self.dossier.synthetic, "samples": len(curve),
                      "phases": phases, **found}
            if start and end:
                window = [row for row in curve
                          if parse_ts(start) <= parse_ts(row["timestamp"]) <= parse_ts(end)]
                result["window"] = window[:MAX_WINDOW_ROWS]
                if len(window) > MAX_WINDOW_ROWS:
                    result["window_truncated"] = (f"{len(window)} samples in the interval, first "
                                                  f"{MAX_WINDOW_ROWS} returned: ask for a shorter interval")
        self._log("get_sensor_curve", {"start": start, "end": end}, result)
        return result

    def lookup_rule(self, rule: str) -> dict:
        if rule not in self.rules:
            raise KeyError(f"no rule {rule!r} (R01 to R10)")
        card = self.rules[rule].raw
        self._log("lookup_rule", {"rule": rule}, card)
        return card

    def ask_handler(self, question: str, start: str, end: str) -> dict:
        start, end = _utc(start), _utc(end)  # logged and used in UTC, like claims
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
        text, model = self._voice_text(chosen, chosen["answer"])
        result = {"id": chosen["id"], "question": question, "asked_start": start, "asked_end": end,
                  # the interval the recorded answer is about (None for the default answer)
                  "start": chosen.get("start"), "end": chosen.get("end"),
                  "default": bool(chosen.get("default")), "answer": text,
                  "transcribed": self.backend == "live" and model == MODEL_FOR_TOOL["ask_handler"]}
        self.observations["handler_answers"].append(result)
        self._log("ask_handler", {"question": question, "start": start, "end": end}, result, model)
        return result

    def _audio(self, item: dict):
        """Recording of a note or answer: the ``audio`` field, else ``voice/audio/<id>.<ext>``."""
        if item.get("audio"):
            path = self.dossier.path(item["audio"])
            return path if path.is_file() else None
        folder = self.dossier.root / "voice" / "audio"
        for extension in ("m4a", "mp3", "wav", "ogg", "webm"):
            candidate = folder / f"{item.get('id')}.{extension}"
            if candidate.exists():
                return candidate
        return None

    def _voice_text(self, item: dict, stored: str) -> tuple[str, str]:
        """Text of a note or answer and the label of what produced it."""
        audio = self._audio(item)
        if audio is None:
            return stored, STORED_TEXT        # no recording: no model involved, live or offline
        if self.backend == "live":
            return models.transcribe(audio), MODEL_FOR_TOOL["convoy_notes"]
        return stored, MODEL_FOR_TOOL["convoy_notes"]  # offline stand-in for the transcription

    def convoy_notes(self) -> list[dict]:
        """Convoy attendant's notes, transcribed (Muse Voice Transcribe in live mode when the
        note has a recording; the stored transcript otherwise). The text the agent saw is kept
        in ``observations`` so the verifier and the record use the same words."""
        notes, models_used = [], set()
        for note in self.dossier.convoy_notes():
            try:
                text, model = self._voice_text(note, note["text"])
            except Exception as error:  # a failed transcription falls back to the stored text
                self.journal.append({"type": "error", "stage": self.stage, "tool": "convoy_notes",
                                     "error": redact(f"transcription of {note['id']} failed: "
                                                     f"{type(error).__name__}: {error}")})
                text, model = note["text"], STORED_TEXT
            models_used.add(model)
            notes.append({"id": note["id"], "time": note["time"], "text": text,
                          "transcribed": self.backend == "live" and model == MODEL_FOR_TOOL["convoy_notes"]})
        self.observations["convoy_notes"] = notes
        self._log("convoy_notes", {}, notes, " + ".join(sorted(models_used)) or STORED_TEXT)
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

    def draft_notification(self, recipient: str) -> dict:
        """Fill the draft template with verified facts only (lcw.drafts); no model text."""
        body = render_draft(recipient, self.dossier.id, self.dossier.synthetic, self.accepted, self.rules)
        draft = {"recipient": recipient, "status": "draft — not sent", "body": body}
        self.drafts.append(draft)
        self._log("draft_notification", {"recipient": recipient}, draft)
        return draft

    def write_case_file(self, claims: list[dict]) -> dict:
        """Run the non-AI verifier. Accepted claims are kept for the record; rejected ones come
        back with their reasons so the agent can correct them."""
        from .verifier import Verifier

        if not isinstance(claims, list) or not all(isinstance(c, dict) for c in claims):
            raise ValueError("claims must be a list of objects")
        # Stage rules, checked before the verifier: stage 1 records pre-departure claims only,
        # stage 2 deviation claims only, and an id accepted at one stage is never reused at the other.
        early, to_check = [], []
        kind = CLAIM_KIND_FOR_STAGE.get(self.stage)
        seen: set[str] = set()
        for claim in claims:
            reasons = []
            claim_id = claim.get("id")
            if not isinstance(claim_id, str) or not claim_id.strip():
                reasons.append("claim id must be a non-empty string such as \"C1\"")
                claim_id = repr(claim_id)
            elif claim_id in seen:
                reasons.append(f"id {claim_id} is used twice in this submission")
            seen.add(claim_id)
            if kind and claim.get("kind") != kind:
                reasons.append(f"only {kind!r} claims can be recorded at stage {self.stage}")
            first_stage = self.claim_stage.get(claim_id)
            if first_stage and first_stage != self.stage:
                reasons.append(f"id {claim_id} was already used at stage {first_stage}: pick a new id")
            (early if reasons else to_check).append({"claim": claim, "reasons": reasons} if reasons else claim)

        checked = [_in_utc(c) for c in to_check]
        report = Verifier(self.dossier, self.rules, self.observations).check(checked)
        sent_by_id = {id(c): s for c, s in zip(checked, to_check, strict=True)}
        for entry in report["rejected"]:
            changes = _rewritten(sent_by_id.get(id(entry["claim"]), {}), entry["claim"])
            about_time = any(r.startswith(("date ", "time ")) for r in entry["reasons"])
            if changes and about_time:
                entry["reasons"].append("times are recorded in UTC (" + "; ".join(sorted(set(changes)))
                                        + "): dates and times in the statement must be the UTC ones")
        rejected = early + report["rejected"]
        accepted_ids = {c["id"] for c in report["accepted"]}
        self.accepted = [c for c in self.accepted if c["id"] not in accepted_ids]
        self.accepted += report["accepted"]
        for claim_id in accepted_ids:
            self.claim_stage.setdefault(claim_id, self.stage)
        summary = {"accepted": sorted(accepted_ids),
                   "rejected": [{"id": r["claim"].get("id"), "reasons": r["reasons"]}
                                for r in rejected]}
        self._log("write_case_file", {"claims": [c.get("id") for c in claims]}, summary)
        return summary

    def values(self, series: str, start: str, end: str) -> list[float]:
        return values_in(self.dossier.curve() or [], series, start, end)
