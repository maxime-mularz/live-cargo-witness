"""CA-06 — the verifier blocks claims without evidence: 5 unsourced claims injected, 5 rejected.

Usage: python new/scripts/check_ca06.py [dossier]      (default: the demo stopover scenario)

Starts from a claim the verifier accepts (a real deviation of the dossier, correctly cited), then
breaks its sourcing in five different ways. Offline: the dossier's readings come from its
ground-truth files, no model is called.
"""
import copy
import sys
from pathlib import Path

import _path  # noqa: F401
from lcw import BENCH_DIR
from lcw.dossier import Dossier
from lcw.tools import Toolset
from lcw.verifier import Verifier

DEFAULT = BENCH_DIR / "demo" / "DEMO-02"


def base_claim(tools: Toolset) -> dict:
    curve = tools.get_sensor_curve()
    deviation = next(d for d in curve["deviations"] if d["rule"] == "R07")
    answer = tools.ask_handler("What happened to the crates during this interval?", deviation["start"],
                               deviation["end"])
    rule = tools.rules["R07"]
    peak = max(tools.values("temperature_c", deviation["start"], deviation["end"]))
    high = tools.dossier.record["declared"]["temperature_range_c"][1]
    return {"id": "C1", "kind": "deviation", "rule": "R07", "status": "explained_rule_exceeded",
            "interval": {"start": deviation["start"], "end": deviation["end"]},
            "statement": f"Between {deviation['start'][11:16]} and {deviation['end'][11:16]} UTC the temperature "
                         f"reached {peak:g} °C, above the declared maximum of {high:g} °C.",
            "evidence": [{"type": "curve_segment", "series": "temperature_c",
                          "start": deviation["start"], "end": deviation["end"]},
                         {"type": "dossier_field", "path": rule.threshold["path"]},
                         {"type": "handler_answer", "id": answer["id"]}]}


def injected(claim: dict) -> list[tuple[str, str, dict]]:
    """(name, reason the verifier must give, broken claim)."""
    def variant(change):
        broken = copy.deepcopy(claim)
        change(broken)
        return broken

    return [
        ("no evidence at all", "no evidence cited", variant(lambda c: c.update(evidence=[]))),
        ("a number found in no evidence", "number 37 is not in the evidence",
         variant(lambda c: c.update(statement=c["statement"] + " 37 crates were affected."))),
        ("threshold not cited", "threshold source", variant(lambda c: c.update(
            evidence=[e for e in c["evidence"] if e["type"] != "dossier_field"]))),
        ("explanation without any note or answer", "an explanation needs", variant(lambda c: c.update(
            evidence=[e for e in c["evidence"] if e["type"] != "handler_answer"]))),
        ("handler answer never obtained", "was never obtained", variant(lambda c: c.update(
            evidence=[*[e for e in c["evidence"] if e["type"] != "handler_answer"],
                      {"type": "handler_answer", "id": "H9"}]))),
    ]


def run(folder: Path = DEFAULT) -> tuple[bool, list[tuple[str, list[str]]]]:
    """Each injected claim must be rejected *for its own reason*, not just rejected."""
    tools = Toolset(Dossier(folder), backend="offline")
    claim = base_claim(tools)
    verifier = Verifier(tools.dossier, tools.rules, tools.observations)
    control = verifier.check_claim(claim)
    if control:
        raise SystemExit(f"the control claim should be accepted, got: {control}")
    outcomes, ok = [], True
    for name, expected, broken in injected(claim):
        reasons = verifier.check_claim(broken)
        ok &= any(expected in reason for reason in reasons)
        outcomes.append((name, reasons))
    return ok, outcomes


def main() -> None:
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    ok, outcomes = run(folder)
    print(f"CA-06 on {folder.name}: control claim accepted; injected claims:")
    for name, reasons in outcomes:
        print(f"  [{'rejected' if reasons else 'ACCEPTED'}] {name}: {'; '.join(reasons) or '-'}")
    rejected = sum(1 for _, reasons in outcomes if reasons)
    print(f"\nCA-06: {'PASS' if ok else 'FAIL'} ({rejected}/5 rejected)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
