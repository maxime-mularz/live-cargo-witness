"""Non-AI verifier (EF-14).

Every statement the agent wants in the shared handover record is a *claim*. The verifier accepts
a claim only if:

1. it cites an active rule card;
2. every piece of evidence resolves to something that exists (a curve segment, a document field
   as read, a crate feature as segmented, a convoy note, a handler answer actually obtained, an
   inspection window declared in the entry record, a dossier field);
3. the evidence supports the claim: a deviation's curve segment really breaks the rule's
   threshold in a phase where the rule applies; a pre-departure claim agrees with the
   deterministic evaluation of the cited readings;
4. the status is backed by the right kind of evidence (an explanation needs a note or an answer,
   a dismissed false positive needs a declared inspection window, "indeterminate" needs a handler
   answer that was actually asked for);
5. every number, time, date and air waybill number in the statement comes from the evidence;
6. the statement contains no forbidden (veterinary) vocabulary.

Rejected claims go back to the agent with the reasons. Nothing here calls a model.

Claim format::

    {"id": "C1", "kind": "deviation" | "pre_departure", "rule": "R07",
     "status": "<lcw.STATUSES>" (deviation) | "violated" | "satisfied" (pre_departure),
     "interval": {"start": iso, "end": iso} (deviation),
     "statement": "...", "evidence": [ {...}, ... ]}

Evidence types::

    {"type": "curve_segment", "series": "temperature_c", "start": iso, "end": iso}
    {"type": "dossier_field", "path": "declared.temperature_range_c"}
    {"type": "document_field", "document": "awb", "field": "head_count"}
    {"type": "crate_feature", "photo": "crate_02", "feature": "orientation_arrows"}
    {"type": "voice_note", "id": "N2"}
    {"type": "handler_answer", "id": "H1"}
    {"type": "inspection_window", "id": "I1"}

``observations`` holds what the tools returned during the run (documents read, crates segmented,
handler answers obtained) — see ``lcw.tools``.
"""

from __future__ import annotations

import re
from datetime import timedelta

from . import STATUSES
from .deviations import _applies, _out_of_bounds
from .dossier import Dossier, parse_ts
from .phases import phase_at, segment
from .predeparture import evaluate_rule
from .rules import Rule, get_path, resolve_threshold
from .vocab import find_forbidden

NOTE_WINDOW = timedelta(minutes=10)  # a note explains an interval if dictated during it (± 10 min)
SERIES = ("temperature_c", "light_lux", "shock_g")
DOSSIER_PREFIXES = ("declared.", "sensor.", "schedule.", "route.", "phase_model.", "awb_number_declared")
TOLERANCE = 0.051

AWB_RE = re.compile(r"\b\d{3}-\d{8}\b")
DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
TIME_RE = re.compile(r"\b([01]\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?\b")
ID_RE = re.compile(r"\b[RCNHI]\d+\b")
NUMBER_RE = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?")  # "31C", "45min" are caught too
NUMBER_WORDS = re.compile(
    r"\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
    r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|"
    r"hundred|thousand|dozen|deux|trois|quatre|cinq|sept|huit|neuf|onze|douze|treize|quatorze|"
    r"quinze|seize|vingt|trente|quarante|cinquante|soixante|cent|mille|douzaine)s?\b", re.IGNORECASE)


class Verifier:
    def __init__(self, dossier: Dossier, rules: dict[str, Rule], observations: dict):
        self.dossier = dossier
        self.record = dossier.record
        self.rules = rules
        self.observations = observations
        self.curve = dossier.curve() or []
        self.phases = segment(self.record) if self.curve else []
        self.notes = {n["id"]: n for n in dossier.convoy_notes()}
        self.answers = {a["id"]: a for a in observations.get("handler_answers", [])}
        self.windows = {w["id"]: w for w in self.record.get("declared", {}).get("inspection_windows", [])}
        self.sampling = timedelta(minutes=self.record.get("sensor", {}).get("sampling_minutes", 5))

    # ------------------------------------------------------------------ public

    def check(self, claims: list[dict]) -> dict:
        accepted, rejected = [], []
        for claim in claims:
            reasons = self.check_claim(claim)
            (rejected if reasons else accepted).append(
                {"claim": claim, "reasons": reasons} if reasons else claim)
        return {"accepted": accepted, "rejected": rejected}

    def check_claim(self, claim: dict) -> list[str]:
        reasons: list[str] = []
        rule = self.rules.get(claim.get("rule", ""))
        if rule is None:
            return [f"unknown rule {claim.get('rule')!r}"]
        if not rule.active:
            return [f"rule {rule.id} is disabled"]
        evidence = claim.get("evidence") or []
        if not evidence:
            return ["no evidence cited"]

        grounded = _Grounding()
        grounded.ids = set(self.rules) | {str(claim.get("id", ""))}
        for item in evidence:
            problem = self._resolve(item, grounded)
            if problem:
                reasons.append(problem)
        if reasons:
            return reasons

        kind = claim.get("kind")
        if kind == "deviation":
            reasons += self._check_deviation(claim, rule, evidence, grounded)
        elif kind == "pre_departure":
            reasons += self._check_pre_departure(claim, rule, evidence)
        else:
            reasons.append(f"unknown claim kind {kind!r}")

        statement = claim.get("statement", "")
        if not statement.strip():
            reasons.append("empty statement")
        forbidden = find_forbidden(statement)
        if forbidden:
            reasons.append(f"forbidden vocabulary: {', '.join(forbidden)}")
        grounded.ids |= {str(e.get("id")) for e in evidence if e.get("id")}
        reasons += grounded.ungrounded(statement)
        return reasons

    # ------------------------------------------------------------------ evidence

    def _resolve(self, item: dict, grounded: "_Grounding") -> str | None:
        kind = item.get("type")
        if kind == "curve_segment":
            if not self.curve:
                return "no sensor curve in this dossier"
            try:
                start, end = parse_ts(item["start"]), parse_ts(item["end"])
            except (KeyError, ValueError):
                return "curve_segment needs valid start and end"
            rows = [r for r in self.curve if start <= parse_ts(r["timestamp"]) <= end]
            if not rows:
                return f"no samples between {item['start']} and {item['end']}"
            series = item.get("series")
            if series not in SERIES:
                return f"unknown series {series!r}"
            values = [r[series] for r in rows]
            grounded.numbers += values + [round(v) for v in values]
            grounded.numbers += [min(values), max(values)]
            first = start - self.sampling
            last = end + self.sampling
            grounded.times += [parse_ts(r["timestamp"]) for r in self.curve
                               if first <= parse_ts(r["timestamp"]) <= last]
            minutes = (end - start).total_seconds() / 60
            grounded.numbers += [minutes, minutes + self.sampling.total_seconds() / 60]
            grounded.dates.add(item["start"][:10])
            grounded.dates.add(item["end"][:10])
            return None
        if kind == "dossier_field":
            path = item.get("path") or ""
            if not path.startswith(DOSSIER_PREFIXES):
                return f"dossier field {path!r} is not a citable entry-record field"
            try:
                value = get_path(self.record, path)
            except (KeyError, IndexError, TypeError, ValueError):
                return f"dossier field {path!r} not found"
            if isinstance(value, dict) or (isinstance(value, list) and any(isinstance(v, dict) for v in value)):
                return f"dossier field {path!r} is not a single value; cite a leaf field"
            grounded.add_value(value)
            return None
        if kind == "document_field":
            document = self.observations.get("documents", {}).get(item.get("document"))
            if document is None:
                return f"document {item.get('document')!r} was not read"
            if item.get("field") not in document:
                return f"field {item.get('field')!r} not read on {item.get('document')}"
            grounded.add_value(document[item["field"]])
            return None
        if kind == "crate_feature":
            crate = self.observations.get("crates", {}).get(item.get("photo"))
            if crate is None:
                return f"photo {item.get('photo')!r} was not segmented"
            if item.get("feature") not in crate:
                return f"feature {item.get('feature')!r} not found on {item.get('photo')}"
            grounded.add_value(crate[item["feature"]])
            grounded.numbers.append(len(self.observations.get("crates", {})))
            grounded.numbers += [float(d) for d in re.findall(r"\d+", item["photo"])]
            return None
        if kind == "voice_note":
            note = self.notes.get(item.get("id"))
            if note is None:
                return f"convoy note {item.get('id')!r} does not exist"
            grounded.add_text(note["text"])
            grounded.times.append(parse_ts(note["time"]))
            return None
        if kind == "handler_answer":
            answer = self.answers.get(item.get("id"))
            if answer is None:
                return f"handler answer {item.get('id')!r} was never obtained"
            grounded.add_text(answer["answer"])
            return None
        if kind == "inspection_window":
            window = self.windows.get(item.get("id"))
            if window is None:
                return f"inspection window {item.get('id')!r} is not in the entry record"
            grounded.add_text(window["reason"])
            grounded.times += [parse_ts(window["start"]), parse_ts(window["end"])]
            return None
        return f"unknown evidence type {kind!r}"

    # ------------------------------------------------------------------ deviations

    def _check_deviation(self, claim, rule: Rule, evidence, grounded) -> list[str]:
        reasons: list[str] = []
        if rule.phase != "investigation":
            return [f"{rule.id} is not an investigation rule"]
        status = claim.get("status")
        if status not in STATUSES:
            return [f"unknown status {status!r}"]
        resolved = resolve_threshold(rule, self.record)
        if resolved is None:
            return [f"threshold of {rule.id} cannot be resolved for this dossier"]
        threshold, path = resolved
        if not any(e.get("type") == "dossier_field" and e.get("path") == path for e in evidence):
            reasons.append(f"the threshold source ({path}) must be cited")

        segments = [e for e in evidence if e.get("type") == "curve_segment"
                    and e.get("series") == rule.check["series"]]
        if not segments:
            return reasons + [f"a curve segment of {rule.check['series']} must be cited"]
        interval = claim.get("interval") or {}
        try:
            first, last = parse_ts(interval["start"]), parse_ts(interval["end"])
        except (KeyError, ValueError, AttributeError):
            return reasons + ["deviation claim needs an interval"]
        if last < first:
            return reasons + ["interval ends before it starts"]
        inside = [item for item in segments
                  if parse_ts(item["start"]) <= first and last <= parse_ts(item["end"])]
        if not inside:
            reasons.append("the interval must lie inside a cited curve segment")
        breach = False
        for row in self.curve:
            moment = parse_ts(row["timestamp"])
            if first <= moment <= last:
                phase = phase_at(self.phases, row["timestamp"])
                if _applies(rule, phase) and _out_of_bounds(rule, row[rule.check["series"]], threshold):
                    breach = True
        if not breach:
            reasons.append(f"the claimed interval does not break {rule.id}")

        def overlaps(start, end) -> bool:
            return start <= last and end >= first

        notes = [self.notes[e["id"]] for e in evidence if e.get("type") == "voice_note"]
        answers = [self.answers[e["id"]] for e in evidence if e.get("type") == "handler_answer"]
        windows = [self.windows[e["id"]] for e in evidence if e.get("type") == "inspection_window"]
        explaining_notes = [n for n in notes
                            if first - NOTE_WINDOW <= parse_ts(n["time"]) <= last + NOTE_WINDOW]
        # A recorded answer explains only if it is about this interval; the default
        # "no information" answer never explains. Whether its words actually explain the
        # deviation is the agent's judgement, shown verbatim in the record for the signatories.
        explaining_answers = [a for a in answers if not a.get("default") and a.get("start")
                              and a.get("end") and overlaps(parse_ts(a["start"]), parse_ts(a["end"]))]

        if status in ("explained_compliant", "explained_rule_exceeded"):
            if not explaining_notes and not explaining_answers:
                reasons.append("an explanation needs a convoy note or a handler answer about this interval")
        elif status == "false_positive_dismissed":
            if not any(overlaps(parse_ts(w["start"]), parse_ts(w["end"])) for w in windows):
                reasons.append("a dismissed false positive needs a declared inspection window "
                               "covering the interval")
        elif status == "indeterminate":
            if not answers:
                reasons.append("'indeterminate' is only allowed after asking the handler")
        return reasons

    # ------------------------------------------------------------------ pre-departure

    def _check_pre_departure(self, claim, rule: Rule, evidence) -> list[str]:
        if rule.phase != "pre_departure":
            return [f"{rule.id} is not a pre-departure rule"]
        status = claim.get("status")
        if status not in ("violated", "satisfied"):
            return [f"pre-departure status must be 'violated' or 'satisfied', not {status!r}"]
        cited_docs = {(e.get("document"), e.get("field")) for e in evidence if e.get("type") == "document_field"}
        cited_crates = {e.get("photo") for e in evidence if e.get("type") == "crate_feature"}
        check = rule.check
        if check["type"] in ("field_contains", "field_true"):
            needed = {(check["document"], check["field"])}
        elif check["type"] == "fields_equal":
            needed = {(f["document"], f["field"]) for f in check["fields"]}
        else:
            needed = {(check["document"], check["field"])} if check["type"] == "crate_awb_matches" else set()
            if not cited_crates:
                return ["crate rules must cite the crate features they rely on"]
            all_crates = set(self.observations.get("expected_crates") or self.observations.get("crates", {}))
            if status == "satisfied" and cited_crates != all_crates:
                return ["a satisfied crate rule must cite every crate"]
        missing = needed - cited_docs
        if missing:
            return [f"missing cited fields: {sorted(missing)}"]
        subset = {"documents": self.observations.get("documents", {}),
                  "expected_crates": sorted(cited_crates) if status == "violated" else
                  self.observations.get("expected_crates"),
                  "crates": {k: v for k, v in self.observations.get("crates", {}).items()
                             if not cited_crates or k in cited_crates}}
        outcome = evaluate_rule(rule, subset)["outcome"]
        if outcome != status:
            return [f"the cited readings give '{outcome}', not '{status}'"]
        return []


class _Grounding:
    """Collects the values the evidence makes available to the statement."""

    def __init__(self):
        self.numbers: list[float] = []
        self.times: list = []
        self.dates: set[str] = set()
        self.awbs: set[str] = set()
        self.ids: set[str] = set()

    def add_value(self, value) -> None:
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, (int, float)):
            self.numbers.append(float(value))
        elif isinstance(value, str):
            self.add_text(value)
        elif isinstance(value, (list, tuple)):
            for item in value:
                self.add_value(item)
        elif isinstance(value, dict):
            for item in value.values():
                self.add_value(item)

    def add_text(self, text: str) -> None:
        self.awbs.update(AWB_RE.findall(text))
        self.dates.update(DATE_RE.findall(text))
        cleaned = DATE_RE.sub(" ", AWB_RE.sub(" ", text))
        for match in TIME_RE.finditer(cleaned):
            self.numbers += [float(match.group(1)), float(match.group(2))]
        for token in NUMBER_RE.findall(TIME_RE.sub(" ", cleaned)):
            self.numbers.append(float(token.replace(",", ".")))

    def ungrounded(self, statement: str) -> list[str]:
        reasons = []
        for token in ID_RE.findall(statement):
            if token not in self.ids:
                reasons.append(f"identifier {token} is not a known rule or cited evidence")
        text = ID_RE.sub(" ", statement)
        for word in NUMBER_WORDS.findall(text):
            reasons.append(f"spelled-out number '{word}': write numbers as digits from the evidence")
        for awb in AWB_RE.findall(text):
            if awb not in self.awbs:
                reasons.append(f"air waybill number {awb} is not in the evidence")
        text = AWB_RE.sub(" ", text)
        for date in DATE_RE.findall(text):
            if date not in self.dates:
                reasons.append(f"date {date} is not in the evidence")
        text = DATE_RE.sub(" ", text)
        allowed_times = {(t.hour, t.minute) for t in self.times}
        for match in TIME_RE.finditer(text):
            if (int(match.group(1)), int(match.group(2))) not in allowed_times:
                reasons.append(f"time {match.group(0)} is not in the evidence")
        text = TIME_RE.sub(" ", text)
        for token in NUMBER_RE.findall(text):
            value = float(token.replace(",", "."))
            if not any(abs(value - known) <= TOLERANCE for known in self.numbers):
                reasons.append(f"number {token} is not in the evidence")
        return reasons
