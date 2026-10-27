import copy

import pytest

from conftest import dossier_dirs
from helpers import scripted_run
from lcw.dossier import Dossier, load_json
from lcw.verifier import Verifier


def by_category(category, index=0):
    folders = [f for f in dossier_dirs() if load_json(f / "expected.json")["category"] == category]
    return folders[index]


@pytest.fixture(scope="module")
def handler_case():
    tools, pre, claims, result = scripted_run(by_category("explained_by_handler"))
    return tools, claims


def verifier_for(tools):
    return Verifier(tools.dossier, tools.rules, tools.observations)


def test_scripted_claims_pass_on_every_dossier():
    for folder in dossier_dirs():
        tools, pre, claims, result = scripted_run(folder)
        report = verifier_for(tools).check(claims)
        assert report["rejected"] == [], (folder.name, report["rejected"])


def mutate(claim, **changes):
    claim = copy.deepcopy(claim)
    claim.update(changes)
    return claim


def reasons(tools, claim):
    return verifier_for(tools).check_claim(claim)


def test_invented_number_is_rejected(handler_case):
    tools, claims = handler_case
    claim = mutate(claims[0], statement=claims[0]["statement"] + " Losses estimated at 37 percent.")
    assert any("number 37" in r for r in reasons(tools, claim))


def test_invented_time_and_date_are_rejected(handler_case):
    tools, claims = handler_case
    claim = mutate(claims[0], statement="It started at 03:17 UTC on 2025-01-01.")
    found = reasons(tools, claim)
    assert any("time 03:17" in r for r in found) and any("date 2025-01-01" in r for r in found)


def test_veterinary_vocabulary_is_rejected(handler_case):
    tools, claims = handler_case
    claim = mutate(claims[0], statement="The heifers were sick after the stopover.")
    assert any("forbidden vocabulary" in r for r in reasons(tools, claim))


def test_threshold_source_must_be_cited(handler_case):
    tools, claims = handler_case
    claim = mutate(claims[0], evidence=[e for e in claims[0]["evidence"] if e["type"] != "dossier_field"])
    assert any("threshold source" in r for r in reasons(tools, claim))


def test_explanation_needs_a_note_or_an_answer(handler_case):
    tools, claims = handler_case
    claim = mutate(claims[0], evidence=[e for e in claims[0]["evidence"] if e["type"] != "handler_answer"])
    assert any("explanation needs" in r for r in reasons(tools, claim))


def test_answer_never_asked_is_rejected():
    tools, pre, claims, result = scripted_run(by_category("explained_by_note"))
    claim = mutate(claims[0], evidence=claims[0]["evidence"] + [{"type": "handler_answer", "id": "H1"}])
    assert any("never obtained" in r for r in reasons(tools, claim))


def test_indeterminate_requires_asking():
    tools, pre, claims, result = scripted_run(by_category("explained_by_note"))
    claim = mutate(claims[0], status="indeterminate",
                   statement=claims[0]["statement"],
                   evidence=[e for e in claims[0]["evidence"] if e["type"] != "voice_note"])
    assert any("only allowed after asking" in r for r in reasons(tools, claim))


def test_false_positive_needs_a_declared_window():
    tools, pre, claims, result = scripted_run(by_category("false_positive"))
    claim = mutate(claims[0], evidence=[e for e in claims[0]["evidence"] if e["type"] != "inspection_window"])
    assert any("inspection window" in r for r in reasons(tools, claim))


def test_segment_that_does_not_break_the_rule_is_rejected(handler_case):
    tools, claims = handler_case
    record = tools.dossier.record
    start = record["schedule"]["loading_start"]
    claim = copy.deepcopy(claims[0])
    for item in claim["evidence"]:
        if item["type"] == "curve_segment":
            item["start"] = item["end"] = start
    claim["interval"] = {"start": start, "end": start}
    claim["statement"] = "Temperature stayed normal."
    assert any("does not break" in r for r in reasons(tools, claim))


# --- counter-examples from the independent review -------------------------------------------

def test_numbers_glued_to_units_and_spelled_out_are_rejected(handler_case):
    tools, claims = handler_case
    found = reasons(tools, mutate(claims[0], statement=claims[0]["statement"] + " It reached 31C for 45min."))
    assert any("number 31" in r for r in found) and any("number 45" in r for r in found)
    found = reasons(tools, mutate(claims[0], statement=claims[0]["statement"] + " Thirty-seven crates."))
    assert any("spelled-out" in r for r in found)


def test_unknown_identifiers_are_rejected(handler_case):
    tools, claims = handler_case
    found = reasons(tools, mutate(claims[0], statement=claims[0]["statement"] + " See R99 and H42."))
    assert any("R99" in r for r in found) and any("H42" in r for r in found)


def test_whole_dossier_cannot_be_cited(handler_case):
    tools, claims = handler_case
    for path in ("", "declared", "schedule"):
        claim = mutate(claims[0], evidence=claims[0]["evidence"] + [{"type": "dossier_field", "path": path}])
        assert any("dossier field" in r for r in reasons(tools, claim)), path


def test_default_answer_never_explains():
    tools, pre, claims, result = scripted_run(by_category("explained_by_note"))
    claim = claims[0]
    default = tools.ask_handler("Anything?", "2000-01-01T00:00:00Z", "2000-01-01T00:10:00Z")
    assert default["default"]
    claim = mutate(claim, evidence=[e for e in claim["evidence"] if e["type"] != "voice_note"]
                   + [{"type": "handler_answer", "id": default["id"]}])
    assert any("explanation needs" in r for r in reasons(tools, claim))


def test_far_away_note_does_not_explain():
    tools, pre, claims, result = scripted_run(by_category("indeterminate"))
    claim = claims[0]
    last_note = tools.dossier.convoy_notes()[-1]
    claim = mutate(claim, status="explained_rule_exceeded",
                   evidence=claim["evidence"] + [{"type": "voice_note", "id": last_note["id"]}])
    claim["evidence"] = [e for e in claim["evidence"] if e["type"] != "handler_answer"]
    assert any("explanation needs" in r for r in reasons(tools, claim))


def test_interval_must_match_the_breach(handler_case):
    tools, claims = handler_case
    claim = copy.deepcopy(claims[0])
    record = tools.dossier.record
    whole = {"start": record["schedule"]["loading_start"], "end": record["schedule"]["unloading_end"]}
    for item in claim["evidence"]:
        if item["type"] == "curve_segment":
            item.update(whole)
    claim["interval"] = {"start": record["schedule"]["loading_start"],
                         "end": record["schedule"]["loading_start"]}
    claim["statement"] = "A deviation was found."
    assert any("does not break" in r for r in reasons(tools, claim))


def test_unsegmented_crate_cannot_pass(rules):
    from lcw.predeparture import evaluate
    from lcw.tools import Toolset
    folder = by_category("defect_R04")
    tools = Toolset(Dossier(folder), rules=rules)
    for name in tools.dossier.record["documents"]:
        tools.read_document(name)
    good = [c for c in tools.observations["expected_crates"]
            if load_json(folder / "photos" / f"{c}.truth.json")["features"]["live_animals_label"]["present"]]
    tools.segment_crate(good[0])
    assert evaluate(rules, tools.observations)["decision"] == "block"
    claim = {"id": "C1", "kind": "pre_departure", "rule": "R04", "status": "satisfied",
             "statement": "Every crate carries the label.",
             "evidence": [{"type": "crate_feature", "photo": good[0], "feature": "live_animals_label"}]}
    assert verifier_for(tools).check_claim(claim)


def test_timestamps_with_offsets_are_accepted(handler_case):
    tools, claims = handler_case
    start = claims[0]["interval"]["start"].replace("Z", "+00:00")
    end = claims[0]["interval"]["end"].replace("Z", "+00:00")
    answer = tools.ask_handler("What happened?", start, end)
    assert not answer["default"]


def test_bad_series_is_rejected_not_crashing(handler_case):
    tools, claims = handler_case
    claim = copy.deepcopy(claims[0])
    claim["evidence"].append({"type": "curve_segment", "series": "timestamp",
                              "start": claim["interval"]["start"], "end": claim["interval"]["end"]})
    assert any("unknown series" in r for r in reasons(tools, claim))


def test_unknown_rule_and_evidence(handler_case):
    tools, claims = handler_case
    assert reasons(tools, mutate(claims[0], rule="R99")) == ["unknown rule 'R99'"]
    claim = mutate(claims[0], evidence=claims[0]["evidence"] + [{"type": "gut_feeling"}])
    assert any("unknown evidence type" in r for r in reasons(tools, claim))


def test_pre_departure_claim_must_agree_with_readings():
    tools, pre, claims, result = scripted_run(by_category("defect_R03"))
    assert claims[0]["rule"] == "R03"
    wrong = mutate(claims[0], status="satisfied")
    assert any("give 'violated'" in r for r in reasons(tools, wrong))


def test_satisfied_crate_rule_must_cite_every_crate():
    tools, pre, claims, result = scripted_run(by_category("compliant"))
    first = sorted(tools.observations["crates"])[0]
    claim = {"id": "C9", "kind": "pre_departure", "rule": "R04", "status": "satisfied",
             "statement": "Every crate carries the label.",
             "evidence": [{"type": "crate_feature", "photo": first, "feature": "live_animals_label"}]}
    assert any("cite every crate" in r for r in reasons(tools, claim))
