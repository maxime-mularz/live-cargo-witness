"""Test helpers: a scripted, model-free run over the offline tools.

This is plumbing for tests and scoring only. It reads expected.json to know what to claim, so it
says nothing about how good the real agent is. The real agent lives in lcw/agent.py (to be wired
with Meta's models) and must never read expected.json.
"""
from datetime import timedelta

from lcw.dossier import Dossier, load_json, parse_ts
from lcw.predeparture import evaluate
from lcw.rules import load_rules
from lcw.tools import Toolset


def read_everything(tools: Toolset) -> dict:
    for name in tools.dossier.record["documents"]:
        tools.read_document(name)
    for photo in tools.dossier.record.get("photos", []):
        tools.segment_crate(photo.split("/")[-1].removesuffix(".png"))
    return evaluate(tools.rules, tools.observations)


def fmt(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def deviation_claim(tools: Toolset, index: int, deviation: dict, status: str, extra: list) -> dict:
    rule = tools.rules[deviation["rule"]]
    series = rule.check["series"]
    values = tools.values(series, deviation["start"], deviation["end"])
    threshold_path = rule.threshold["path"]
    if series == "temperature_c":
        peak = max(values)
        limit = tools.dossier.record["declared"]["temperature_range_c"][1]
        text = (f"Between {deviation['start'][11:16]} and {deviation['end'][11:16]} UTC "
                f"({deviation['phase'].replace('_', ' ')}), temperature reached {fmt(peak)} °C, "
                f"above the declared maximum of {fmt(limit)} °C.")
    elif series == "light_lux":
        text = (f"Light rose to {fmt(max(values))} lux from {deviation['start'][11:16]} UTC, "
                f"above the sensor alert level of {fmt(tools.dossier.record['sensor']['light_alert_lux'])} lux.")
    else:
        text = (f"A shock of {fmt(max(values))} g was recorded at {deviation['start'][11:16]} UTC, "
                f"above the sensor alert level of {fmt(tools.dossier.record['sensor']['shock_alert_g'])} g.")
    return {
        "id": f"C{index}", "kind": "deviation", "rule": rule.id, "status": status,
        "interval": {"start": deviation["start"], "end": deviation["end"]},
        "statement": text,
        "evidence": [{"type": "curve_segment", "series": series,
                      "start": deviation["start"], "end": deviation["end"]},
                     {"type": "dossier_field", "path": threshold_path}, *extra],
    }


def scripted_run(folder) -> tuple[Toolset, dict, list, dict]:
    """Return (tools, pre_departure, claims, result) for one bench dossier."""
    dossier = Dossier(folder)
    expected = load_json(folder / "expected.json")
    tools = Toolset(dossier, backend="offline", rules=load_rules())
    pre = read_everything(tools)
    claims = []
    for rule_id in pre["violated_rules"]:
        rule = tools.rules[rule_id]
        evidence = []
        check = rule.check
        if check["type"] == "fields_equal":
            evidence = [{"type": "document_field", "document": f["document"], "field": f["field"]}
                        for f in check["fields"]]
            counts = [tools.observations["documents"][f["document"]][f["field"]] for f in check["fields"]]
            text = f"Head counts differ: {counts[0]} on the air waybill, {counts[1]} on the certification."
        elif check["type"] in ("field_contains", "field_true"):
            evidence = [{"type": "document_field", "document": check["document"], "field": check["field"]}]
            text = f"{rule.title}: not met on the {check['document']}."
        else:
            crates = sorted(tools.observations["crates"])
            feature = {"crate_feature_present": "live_animals_label",
                       "crate_arrows_up": "orientation_arrows",
                       "crate_awb_matches": "awb_number"}[check["type"]]
            evidence = [{"type": "crate_feature", "photo": c, "feature": feature} for c in crates]
            if check["type"] == "crate_awb_matches":
                evidence.append({"type": "document_field", "document": "awb", "field": "awb_number"})
            text = f"{rule.title}: not met on at least one crate."
        claims.append({"id": f"C{len(claims) + 1}", "kind": "pre_departure", "rule": rule_id,
                       "status": "violated", "statement": text, "evidence": evidence})

    handler_called = False
    deviations_out = []
    if pre["decision"] == "go":
        curve = tools.get_sensor_curve()
        notes = dossier.convoy_notes()
        windows = dossier.record["declared"]["inspection_windows"]
        exp_inv = expected["investigation"]
        status_by_start = {(d["rule"], d["start"]): d["status"] for d in exp_inv["deviations"]}
        answer = None
        for deviation in curve["deviations"]:
            status = status_by_start[(deviation["rule"], deviation["start"])]
            extra = []
            if status == "false_positive_dismissed":
                extra = [{"type": "inspection_window", "id": w["id"]} for w in windows]
            elif exp_inv["handler_call_expected"]:
                if answer is None:
                    answer = tools.ask_handler("What happened to the crates during this interval?",
                                               deviation["start"], deviation["end"])
                    handler_called = True
                extra = [{"type": "handler_answer", "id": answer["id"]}]
            else:
                start = parse_ts(deviation["start"])
                note = next(n for n in notes if abs(parse_ts(n["time"]) - start) <= timedelta(hours=1)
                            and n["id"] != "N1")
                extra = [{"type": "voice_note", "id": note["id"]}]
            claims.append(deviation_claim(tools, len(claims) + 1, deviation, status, extra))
            deviations_out.append({"rule": deviation["rule"], "start": deviation["start"],
                                   "end": deviation["end"], "status": status})
    result = {"dossier_id": dossier.id,
              "phase1": {"decision": pre["decision"], "violated_rules": pre["violated_rules"]},
              "investigation": None if pre["decision"] == "block" else
              {"handler_called": handler_called, "deviations": deviations_out}}
    return tools, pre, claims, result
