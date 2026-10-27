import copy

import pytest

from lcw.dossier import Dossier, load_json
from lcw.verifier import Verifier

from conftest import dossier_dirs
from helpers import scripted_run


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
    claim["statement"] = "Temperature stayed normal."
    assert any("does not break" in r for r in reasons(tools, claim))


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
