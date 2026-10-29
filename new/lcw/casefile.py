"""Shared handover record (PV) and its SHA-256 manifest (EF-15, EF-16).

``write_case`` writes a self-contained folder:

    pv.md            the record, in English (French optional), with three signature lines
    pv.json          the same content, structured
    journal.json     every tool call of the run, with the model behind it
    journal.html     the same journal as a self-contained page (EF-13)
    drafts/          notification drafts, if the agent asked for any (never sent; lcw.drafts)
    pieces/          copies of the dossier pieces the record relies on
    manifest.json    SHA-256 of every file above + the record's root hash

Anyone can recompute the hashes with ``new/scripts/verify_case.py``. Only verified claims enter
the record: ``write_case`` re-runs the verifier and refuses any rejected claim. It also refuses
an incomplete record: every violated pre-departure rule and every deviation found on the curve
must be covered by a verified claim (``missing_claims``).
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

from .deviations import detect
from .dossier import Dossier, parse_ts, write_json
from .drafts import write_drafts
from .hashing import canonical_json, sha256_bytes, sha256_file
from .journal_page import render as render_journal
from .phases import segment
from .predeparture import evaluate
from .rules import Rule
from .verifier import Verifier, notes_seen
from .vocab import mask_deep

STATUS_LABEL = {
    "explained_compliant": "Explained, compliant",
    "explained_rule_exceeded": "Explained, rule exceeded",
    "false_positive_dismissed": "False positive, dismissed",
    "indeterminate": "Indeterminate",
}
SIGNATORIES = ("Shipper", "Carrier", "Ground handler")


class RejectedClaims(Exception):
    def __init__(self, rejected: list[dict]):
        super().__init__(f"{len(rejected)} claim(s) rejected by the verifier")
        self.rejected = rejected


class IncompleteCase(ValueError):
    def __init__(self, missing: list[str]):
        super().__init__("incomplete record: " + "; ".join(missing))
        self.missing = missing


def missing_claims(dossier: Dossier, rules: dict[str, Rule], claims: list[dict],
                   observations: dict) -> list[str]:
    """What the record would leave out: pre-departure rules that could not be checked (a
    document or a crate never read), violated rules without a 'violated' claim, and deviations
    detected on the curve without their own deviation claim (matched one to one)."""
    missing = [f"{rule_id} could not be checked (document or crate not read)"
               for rule_id in evaluate(rules, observations).get("unreadable_rules", [])]
    pre = evaluate(rules, observations)
    for rule_id in pre.get("violated_rules", []):
        if not any(c.get("kind") == "pre_departure" and c.get("rule") == rule_id
                   and c.get("status") == "violated" for c in claims):
            missing.append(f"{rule_id} is violated but has no claim")
    verifier = Verifier(dossier, rules, observations)
    if pre["decision"] == "go" and verifier.detected:
        designated = set()
        for claim in claims:
            interval = claim.get("interval") or {}
            if claim.get("kind") != "deviation" or not interval.get("start") or not interval.get("end"):
                continue
            match = verifier.matching_deviation(claim.get("rule"), parse_ts(interval["start"]),
                                                parse_ts(interval["end"]))
            if match is not None:
                designated.add((match["rule"], match["start"]))
        for deviation in verifier.detected:
            if (deviation["rule"], deviation["start"]) not in designated:
                missing.append(f"deviation {deviation['rule']} {deviation['start'][11:16]}–"
                               f"{deviation['end'][11:16]} UTC has no claim")
    return missing


def _pieces(dossier: Dossier) -> list[str]:
    record = dossier.record
    pieces = ["dossier.json"]
    pieces += list(record.get("documents", {}).values())
    pieces += list(record.get("photos", []))
    for key in ("sensor_curve", "voice_notes"):
        if record.get(key):
            pieces.append(record[key])
    return pieces


def _basis(claim: dict, dossier: Dossier, observations: dict) -> list[str]:
    """Human-readable list of what a claim rests on (shown in the record)."""
    notes = notes_seen(dossier, observations)
    answers = {a["id"]: a for a in observations.get("handler_answers", [])}
    windows = {w["id"]: w for w in dossier.record.get("declared", {}).get("inspection_windows", [])}
    basis = []
    for item in claim.get("evidence", []):
        kind = item.get("type")
        if kind == "curve_segment":
            basis.append(f"Sensor curve, {item['series']}, {item['start'][11:16]}–{item['end'][11:16]} UTC")
        elif kind == "dossier_field":
            basis.append(f"Entry record: {item['path']}")
        elif kind == "document_field":
            basis.append(f"{item['document']}: {item['field']} (as read)")
        elif kind == "crate_feature":
            basis.append(f"{item['photo']}: {item['feature']} (as segmented)")
        elif kind == "voice_note" and item["id"] in notes:
            note = notes[item["id"]]
            how = ", transcribed" if note.get("transcribed") else ""
            basis.append(f"Convoy note {item['id']} ({note['time'][11:16]} UTC{how}): \u201c{note['text']}\u201d")
        elif kind == "handler_answer" and item["id"] in answers:
            answer = answers[item["id"]]
            how = " (transcribed)" if answer.get("transcribed") else ""
            basis.append(f"Ground handler answer {item['id']}{how}: \u201c{answer['answer']}\u201d")
        elif kind == "inspection_window" and item["id"] in windows:
            window = windows[item["id"]]
            basis.append(f"Declared inspection {item['id']} ({window['start'][11:16]}–{window['end'][11:16]} UTC): "
                         f"{window['reason']}")
    return basis


def render_markdown(pv: dict) -> str:
    lines = [f"# Shared handover record — {pv['dossier_id']}", ""]
    if pv["synthetic"]:
        lines += ["> **SYNTHETIC** — fictitious dossier generated for testing. Not a real shipment.", ""]
    lines += [
        f"- Air waybill: {pv['awb_number'] or 'not read'}",
        f"- Route: {pv['route']}",
        f"- Record created: {pv['created_at']}",
        f"- Pre-departure decision: **{pv['pre_departure']['decision'].upper()}**",
        "",
        "## Pre-departure checks",
        "",
    ]
    pre = [c for c in pv["claims"] if c["kind"] == "pre_departure"]
    if pre:
        lines += ["| Rule | Outcome | Statement | Based on |", "| --- | --- | --- | --- |"]
        lines += [f"| {c['rule']} | {c['status']} | {c['statement']} | {'<br>'.join(c.get('basis', []))} |"
                  for c in pre]
    else:
        lines.append("No pre-departure claim recorded.")
    lines += ["", "## Deviations found at investigation", ""]
    deviations = [c for c in pv["claims"] if c["kind"] == "deviation"]
    if deviations:
        lines += ["| Rule | Interval (UTC) | Status | Statement | Based on |",
                  "| --- | --- | --- | --- | --- |"]
        for c in deviations:
            interval = f"{c['interval']['start'][11:16]}–{c['interval']['end'][11:16]}"
            based = "<br>".join(c.get("basis", []))
            lines.append(f"| {c['rule']} | {interval} | {STATUS_LABEL[c['status']]} | {c['statement']} | {based} |")
    else:
        lines.append("No deviation recorded.")
    if pv["unresolved_rules"]:
        lines += ["", f"Rules not applied (threshold unavailable): {', '.join(pv['unresolved_rules'])}."]
    lines += ["", "## Rules cited", ""]
    lines += [f"- {r['id']} — {r['title']} (source: {r['source']})" for r in pv["rules_cited"]]
    lines += ["", "## Signatures", "",
              "This record was prepared by an AI agent and checked by a non-AI verifier. "
              "It is not valid until signed by the three parties below.", ""]
    lines += [f"- {who}: name ____________________  date ____________  signature ____________"
              for who in SIGNATORIES]
    lines += ["", "Integrity: `manifest.json` lists the SHA-256 of every file of this record; its `root` "
              "field is the SHA-256 of that list. Publish or sign the root to make later changes "
              "detectable by anyone.", ""]
    return "\n".join(lines)


def write_case(case_dir: Path | str, dossier: Dossier, rules: dict[str, Rule], claims: list[dict],
               observations: dict, pre_departure: dict, journal: list[dict],
               unresolved_rules: list[str] | None = None, drafts: list[str] | None = None) -> dict:
    """Write the case folder and return its manifest. Raises ``RejectedClaims`` if any claim
    fails verification. ``drafts``: recipients the agent drafted a notification for; each draft
    is re-rendered from the verified claims into ``drafts/<recipient>.md`` (lcw.drafts)."""
    report = Verifier(dossier, rules, observations).check(claims)
    if report["rejected"]:
        raise RejectedClaims(report["rejected"])
    # The decision and the unapplied rules are recomputed, never taken from the caller.
    recomputed = evaluate(rules, observations)
    if pre_departure.get("decision") != recomputed["decision"]:
        raise ValueError(f"pre-departure decision {pre_departure.get('decision')!r} does not match "
                         f"the readings ({recomputed['decision']!r})")
    pre_departure = recomputed
    missing = missing_claims(dossier, rules, claims, observations)
    if missing:
        raise IncompleteCase(missing)
    curve = dossier.curve()
    unresolved_rules = (detect(curve, segment(dossier.record), rules, dossier.record)["unresolved_rules"]
                        if curve else [])

    # Written into a temporary folder, moved into place only when complete: a failure never
    # leaves a half-written record that looks valid.
    final_dir = Path(case_dir)
    case_dir = final_dir.with_name(final_dir.name + ".partial")
    if case_dir.exists():
        shutil.rmtree(case_dir)
    (case_dir / "pieces").mkdir(parents=True)
    journal = mask_deep(journal)  # the raw journal stays in runs/<id>.json

    for relative in _pieces(dossier):
        target = case_dir / "pieces" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dossier.path(relative), target)

    cited = sorted({c["rule"] for c in claims})
    route = dossier.record.get("route", {})
    pv = {
        "dossier_id": dossier.id,
        "synthetic": dossier.synthetic,
        "awb_number": observations.get("documents", {}).get("awb", {}).get("awb_number"),
        "route": " → ".join(route.get(k, "?") for k in ("origin", "stopover", "destination")),
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pre_departure": {"decision": pre_departure["decision"],
                          "violated_rules": pre_departure.get("violated_rules", [])},
        "claims": [dict(c, basis=_basis(c, dossier, observations)) for c in claims],
        "unresolved_rules": unresolved_rules or [],
        "rules_cited": [{"id": r, "title": rules[r].title,
                         "source": rules[r].source.get("note") or rules[r].source.get("kind")}
                        for r in cited],
        "signatures": [{"party": who, "name": None, "date": None, "signed": False}
                       for who in SIGNATORIES],
        "language": "en",
    }
    write_json(case_dir / "pv.json", pv)
    (case_dir / "pv.md").write_text(render_markdown(pv), encoding="utf-8")
    write_json(case_dir / "journal.json", journal)
    (case_dir / "journal.html").write_text(render_journal(pv, journal), encoding="utf-8")
    write_drafts(case_dir, drafts or [], dossier.id, dossier.synthetic, claims, rules)

    files = {}
    for path in sorted(p for p in case_dir.rglob("*") if p.is_file()):
        files[path.relative_to(case_dir).as_posix()] = sha256_file(path)
    manifest = {"algorithm": "sha256", "files": files}
    manifest["root"] = sha256_bytes(canonical_json({"algorithm": "sha256", "files": files}))
    write_json(case_dir / "manifest.json", manifest)
    if final_dir.exists():
        shutil.rmtree(final_dir)
    case_dir.rename(final_dir)
    return manifest



def verify_case(case_dir: Path | str) -> list[str]:
    """Recompute every hash of a case folder. Returns the list of problems (empty = intact)."""
    from .dossier import load_json

    case_dir = Path(case_dir)
    manifest = load_json(case_dir / "manifest.json")
    problems = []
    present = {p.relative_to(case_dir).as_posix() for p in case_dir.rglob("*") if p.is_file()}
    present.discard("manifest.json")
    for relative, expected in manifest["files"].items():
        path = case_dir / relative
        if not path.exists():
            problems.append(f"missing: {relative}")
        elif sha256_file(path) != expected:
            problems.append(f"modified: {relative}")
    for extra in sorted(present - set(manifest["files"])):
        problems.append(f"not in manifest: {extra}")
    root = sha256_bytes(canonical_json({"algorithm": manifest["algorithm"], "files": manifest["files"]}))
    if root != manifest.get("root"):
        problems.append("root hash does not match the file list")
    return problems
