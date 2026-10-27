from itertools import pairwise

from conftest import dossier_dirs
from lcw.deviations import detect
from lcw.dossier import Dossier, load_json, parse_ts
from lcw.phases import segment


def test_phases_are_contiguous():
    for folder in dossier_dirs():
        phases = segment(load_json(folder / "dossier.json"))
        names = [p["name"] for p in phases]
        assert names[0] == "ground_departure" and names[-1] == "ground_arrival"
        assert "stopover" in names and names.count("cruise") == 2
        for left, right in pairwise(phases):
            assert left["end"] == right["start"]


def test_detection_matches_expected(rules):
    for folder in dossier_dirs():
        dossier = Dossier(folder)
        expected = load_json(folder / "expected.json")
        curve = dossier.curve()
        if expected["investigation"] is None:
            assert curve is None
            continue
        found = detect(curve, segment(dossier.record), rules, dossier.record)
        assert found["unresolved_rules"] == []
        got = [(d["rule"], d["start"], d["end"]) for d in found["deviations"]]
        want = [(d["rule"], d["start"], d["end"]) for d in expected["investigation"]["deviations"]]
        assert got == want, folder.name


def test_takeoff_and_landing_jolts_are_ignored(rules):
    for folder in dossier_dirs():
        dossier = Dossier(folder)
        curve = dossier.curve()
        if curve is None:
            continue
        jolts = [r for r in curve if r["shock_g"] > dossier.record["sensor"]["shock_alert_g"]]
        assert jolts, "the synthetic curve should contain normal takeoff/landing jolts"
        found = detect(curve, segment(dossier.record), rules, dossier.record)
        r09 = {d["start"] for d in found["deviations"] if d["rule"] == "R09"}
        phases = segment(dossier.record)
        for jolt in jolts:
            phase = next(p["name"] for p in phases
                         if parse_ts(p["start"]) <= parse_ts(jolt["timestamp"]) < parse_ts(p["end"]))
            assert (jolt["timestamp"] in r09) == (phase not in ("takeoff", "landing"))


def test_missing_threshold_is_reported_not_guessed(rules):
    folder = next(f for f in dossier_dirs() if Dossier(f).curve() is not None)
    dossier = Dossier(folder)
    record = dict(dossier.record)
    record["sensor"] = {k: v for k, v in record["sensor"].items() if k != "light_alert_lux"}
    found = detect(dossier.curve(), segment(record), rules, record)
    assert found["unresolved_rules"] == ["R10"]
    assert all(d["rule"] != "R10" for d in found["deviations"])
