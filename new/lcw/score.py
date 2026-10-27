"""Bench scoring: compare agent results with ``expected.json`` (CA-03, 04, 07, 08, 09).

Result file format (one per dossier, ``<results_dir>/<dossier_id>.json``)::

    {"dossier_id": "DEV-01",
     "phase1": {"decision": "go" | "block", "violated_rules": ["R03"]},
     "investigation": null | {"handler_called": true,
                              "deviations": [{"rule": "R07", "start": iso, "end": iso,
                                              "status": "<lcw.STATUSES>"}]}}

A reported deviation matches an expected one when the rule is the same and the intervals overlap.
"""

from __future__ import annotations

from pathlib import Path

from .dossier import load_json, parse_ts


def _overlap(a: dict, b: dict) -> bool:
    return parse_ts(a["start"]) <= parse_ts(b["end"]) and parse_ts(b["start"]) <= parse_ts(a["end"])


def score_dossier(expected: dict, result: dict | None) -> dict:
    row = {"dossier_id": expected["dossier_id"], "category": expected["category"],
           "missing_result": result is None}
    result = result or {}
    phase1 = result.get("phase1") or {}
    exp1 = expected["phase1"]
    row["phase1_ok"] = (phase1.get("decision") == exp1["decision"]
                        and sorted(phase1.get("violated_rules", [])) == sorted(exp1["violated_rules"]))
    row["false_block"] = exp1["decision"] == "go" and phase1.get("decision") == "block"

    exp_inv = expected.get("investigation")
    inv = result.get("investigation")
    if exp_inv is None:
        row["investigation_ok"] = inv in (None, {}) or not (inv.get("deviations"))
        return row
    inv = inv or {}
    row["handler_ok"] = bool(inv.get("handler_called")) == exp_inv["handler_call_expected"]
    reported = list(inv.get("deviations", []))
    matched, status_ok, missed = 0, 0, []
    for wanted in exp_inv["deviations"]:
        hit = next((d for d in reported if d.get("rule") == wanted["rule"] and _overlap(d, wanted)), None)
        if hit is None:
            missed.append(f"{wanted['rule']}@{wanted['start'][11:16]}")
            continue
        reported.remove(hit)
        matched += 1
        status_ok += hit.get("status") == wanted["status"]
    row.update({
        "deviations_expected": len(exp_inv["deviations"]), "deviations_matched": matched,
        "statuses_ok": status_ok, "missed": missed,
        "spurious": [f"{d.get('rule')}@{str(d.get('start'))[11:16]}" for d in reported],
    })
    row["investigation_ok"] = (row["handler_ok"] and not missed and not reported
                               and status_ok == len(exp_inv["deviations"]))
    return row


def score_bench(bench_dir: Path | str, results_dir: Path | str) -> dict:
    bench_dir, results_dir = Path(bench_dir), Path(results_dir)
    rows = []
    for folder in sorted(p for p in bench_dir.iterdir() if (p / "expected.json").exists()):
        expected = load_json(folder / "expected.json")
        result_path = results_dir / f"{expected['dossier_id']}.json"
        result = load_json(result_path) if result_path.exists() else None
        rows.append(score_dossier(expected, result))

    def ratio(selected, key):
        selected = list(selected)
        return {"passed": sum(1 for r in selected if r.get(key)), "total": len(selected)}

    defects = [r for r in rows if r["category"].startswith("defect_")]
    compliant = [r for r in rows if r["category"] == "compliant"]
    investigated = [r for r in rows if "handler_ok" in r]
    with_deviations = [r for r in investigated if r.get("deviations_expected", 0) > 0]
    metrics = {
        "dossiers": len(rows),
        "missing_results": sum(r["missing_result"] for r in rows),
        "CA-03 defects blocked with the right rule": ratio(defects, "phase1_ok"),
        "CA-04 false blocks on compliant dossiers": {
            "count": sum(r["false_block"] for r in compliant), "total": len(compliant)},
        "CA-07 handler called when (and only when) needed": ratio(investigated, "handler_ok"),
        "CA-07 on dossiers with deviations only": ratio(with_deviations, "handler_ok"),
        "CA-08 false positives dismissed": ratio([r for r in rows if r["category"] == "false_positive"],
                                                 "investigation_ok"),
        "CA-09 indeterminate after asking": ratio([r for r in rows if r["category"] == "indeterminate"],
                                                  "investigation_ok"),
        "phase 1 decisions correct": ratio(rows, "phase1_ok"),
        "investigations fully correct": ratio(investigated, "investigation_ok"),
    }
    return {"metrics": metrics, "rows": rows}


def to_markdown(report: dict, title: str = "Bench score") -> str:
    lines = [f"# {title}", "", "| Metric | Result |", "| --- | --- |"]
    for name, value in report["metrics"].items():
        if isinstance(value, dict) and "passed" in value:
            lines.append(f"| {name} | {value['passed']} / {value['total']} |")
        elif isinstance(value, dict):
            lines.append(f"| {name} | {value['count']} / {value['total']} |")
        else:
            lines.append(f"| {name} | {value} |")
    lines += ["", "| Dossier | Category | Phase 1 | Investigation | Notes |", "| --- | --- | --- | --- | --- |"]
    for row in report["rows"]:
        notes = []
        if row["missing_result"]:
            notes.append("no result")
        if row.get("missed"):
            notes.append("missed " + ", ".join(row["missed"]))
        if row.get("spurious"):
            notes.append("spurious " + ", ".join(row["spurious"]))
        if "handler_ok" in row and not row["handler_ok"]:
            notes.append("handler call wrong")
        inv = "—" if "handler_ok" not in row else ("ok" if row["investigation_ok"] else "KO")
        lines.append(f"| {row['dossier_id']} | {row['category']} | {'ok' if row['phase1_ok'] else 'KO'} "
                     f"| {inv} | {'; '.join(notes)} |")
    return "\n".join(lines) + "\n"
