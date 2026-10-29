"""draft_notification: a fixed template filled with verified facts only, written into the case."""
import re

import pytest

from conftest import dossier_dirs
from fake_model import ScriptedClient
from helpers import scripted_run
from lcw.agent import Agent
from lcw.casefile import verify_case, write_case
from lcw.dossier import Dossier, load_json
from lcw.drafts import DRAFT_HEADER, RECIPIENTS
from lcw.journal_page import STATUS_LABEL
from lcw.runner import run_dossier
from lcw.tools import TOOL_SCHEMAS, Toolset
from lcw.vocab import find_forbidden


def folder_of(category):
    return next(f for f in dossier_dirs() if load_json(f / "expected.json")["category"] == category)


def accepted_tools(category="explained_by_handler"):
    tools, pre, claims, _ = scripted_run(folder_of(category))
    tools.stage = "investigation"
    report = tools.write_case_file([c for c in claims if c["kind"] == "deviation"])
    assert not report["rejected"]
    return tools, pre, claims


def test_draft_is_the_template_filled_with_accepted_claims():
    tools, _, _ = accepted_tools()
    draft = tools.draft_notification("carrier")
    body = draft["body"]
    assert body.startswith(DRAFT_HEADER)
    assert DRAFT_HEADER == "DRAFT — NOT SENT. A human reviews, signs and sends."
    assert draft["status"] == "draft — not sent" and draft["recipient"] == "carrier"
    assert tools.dossier.id in body
    for claim in tools.accepted:
        rule = tools.rules[claim["rule"]]
        assert claim["rule"] in body and rule.title in body
        assert STATUS_LABEL[claim["status"]] in body
        assert claim["statement"] in body
        assert f"{claim['interval']['start'][11:16]}–{claim['interval']['end'][11:16]} UTC" in body
    assert tools.drafts == [draft]


def test_draft_body_holds_no_value_outside_the_verified_facts():
    tools, _, _ = accepted_tools()
    body = tools.draft_notification("ground_handler")["body"]
    rest = body.replace(tools.dossier.id, "")
    for claim in tools.accepted:  # whole statements and titles first: they contain times and rule ids
        rest = rest.replace(claim["statement"], "").replace(tools.rules[claim["rule"]].title, "")
    for claim in tools.accepted:
        rest = rest.replace(claim["rule"], "")
        rest = rest.replace(claim["interval"]["start"][11:16], "").replace(claim["interval"]["end"][11:16], "")
    assert not re.search(r"\d", rest), rest  # every digit comes from the record
    assert find_forbidden(body) == []


def test_model_free_text_cannot_enter_the_draft():
    tools, _, _ = accepted_tools()
    schema = next(t for t in TOOL_SCHEMAS if t["name"] == "draft_notification")
    assert set(schema["parameters"]["properties"]) == {"reason", "recipient"}
    assert set(schema["parameters"]["properties"]["recipient"]["enum"]) == set(RECIPIENTS)
    with pytest.raises(TypeError):
        tools.draft_notification("carrier", summary="About 37 crates were sick.")
    with pytest.raises(ValueError):
        tools.draft_notification("../pv")  # also the file name in the case folder


def test_no_draft_before_any_accepted_claim():
    tools, _, _ = accepted_tools()
    tools.accepted = []
    with pytest.raises(ValueError, match="no claim accepted"):
        tools.draft_notification("shipper")
    assert tools.drafts == []


def test_the_model_gets_a_tool_error_before_any_accepted_claim():
    folder = folder_of("explained_by_note")
    client = ScriptedClient(folder)
    stage2 = client.plans["STAGE 2"]
    stage2.insert(1, ("draft_notification", {"recipient": "carrier", "reason": "Too early."}))
    agent = Agent(Toolset(Dossier(folder), backend="offline"), client=client)
    agent.run()
    errors = [e for e in agent.tools.journal if e.get("type") == "error" and e["tool"] == "draft_notification"]
    assert errors and "no claim accepted" in errors[0]["error"]


def test_drafts_are_written_into_the_case_and_hashed(tmp_path):
    folder = folder_of("explained_by_handler")
    result = run_dossier(folder, tmp_path, client=ScriptedClient(folder, draft_for="carrier"),
                         backend="offline")
    assert result["case"] == "written"
    case = tmp_path / "cases" / result["dossier_id"]
    text = (case / "drafts" / "carrier.md").read_text(encoding="utf-8")
    assert text.startswith(DRAFT_HEADER) and "SYNTHETIC" in text
    assert find_forbidden(text) == []
    manifest = load_json(case / "manifest.json")
    assert "drafts/carrier.md" in manifest["files"]
    assert verify_case(case) == []
    (case / "drafts" / "carrier.md").write_text(text + "\nSent already.", encoding="utf-8")
    assert "modified: drafts/carrier.md" in verify_case(case)


def test_case_drafts_follow_the_final_record(tmp_path):
    tools, pre, claims = accepted_tools()
    write_case(tmp_path / "case", tools.dossier, tools.rules, claims, tools.observations, pre,
               tools.journal, drafts=["shipper", "shipper"])
    text = (tmp_path / "case" / "drafts" / "shipper.md").read_text(encoding="utf-8")
    for claim in claims:
        assert claim["statement"] in text
    assert sorted(p.name for p in (tmp_path / "case" / "drafts").iterdir()) == ["shipper.md"]


def test_no_drafts_folder_without_a_draft(tmp_path):
    tools, pre, claims = accepted_tools()
    write_case(tmp_path / "case", tools.dossier, tools.rules, claims, tools.observations, pre, tools.journal)
    assert not (tmp_path / "case" / "drafts").exists()


def test_accepted_intervals_are_stored_in_utc_whatever_offset_the_model_used():
    # Review of 2026-10-29: 18:15+05:00 passed the verifier and was printed "18:15 UTC" (it is 13:15 UTC).
    from datetime import timedelta, timezone

    from lcw.dossier import parse_ts

    tools, _, claims, _ = scripted_run(folder_of("explained_by_handler"))
    tools.stage = "investigation"
    deviations = [dict(c, interval=dict(c["interval"]), evidence=[dict(e) for e in c["evidence"]])
                  for c in claims if c["kind"] == "deviation"]
    utc = {c["id"]: dict(c["interval"]) for c in deviations}
    shift = timezone(timedelta(hours=5))
    for claim in deviations:
        for item in [claim["interval"]] + [e for e in claim["evidence"] if e["type"] == "curve_segment"]:
            for key in ("start", "end"):
                item[key] = parse_ts(item[key]).astimezone(shift).isoformat()
    assert tools.write_case_file(deviations)["rejected"] == []
    for claim in tools.accepted:
        if claim["id"] in utc:
            expected = {k: parse_ts(v).strftime("%Y-%m-%dT%H:%M:%SZ") for k, v in utc[claim["id"]].items()}
            assert claim["interval"] == expected
            segments = [e for e in claim["evidence"] if e["type"] == "curve_segment"]
            assert segments and all(e["start"].endswith("Z") and e["end"].endswith("Z") for e in segments)
    body = tools.draft_notification("carrier")["body"]
    for interval in utc.values():
        assert f"{parse_ts(interval['start']):%H:%M}–{parse_ts(interval['end']):%H:%M} UTC" in body


def test_odd_interval_values_never_crash_the_submission():
    # Review of the UTC fix: a null or extra interval key raised after the verifier, losing every claim.
    tools, _, claims, _ = scripted_run(folder_of("explained_by_handler"))
    tools.stage = "investigation"
    deviations = [dict(c, interval=dict(c["interval"], note="stopover")) for c in claims if c["kind"] == "deviation"]
    deviations[0] = dict(deviations[0], interval={"start": None, "end": "n/a"})
    report = tools.write_case_file(deviations)
    assert [r["id"] for r in report["rejected"]] == [deviations[0]["id"]]
    assert sorted(report["accepted"]) == sorted(c["id"] for c in deviations[1:])


def test_claims_accepted_with_an_offset_are_accepted_again_when_the_record_is_written(tmp_path):
    # Review of the UTC fix: normalising after the verifier changed the dates write_case re-checks.
    from datetime import timedelta, timezone

    from lcw.dossier import parse_ts

    folder = folder_of("explained_by_handler")
    tools, pre, claims, _ = scripted_run(folder)
    shift = timezone(timedelta(hours=12))
    shifted = []
    for claim in claims:
        claim = dict(claim, evidence=[dict(e) for e in claim["evidence"]])
        if claim["kind"] == "deviation":
            claim["interval"] = {k: parse_ts(v).astimezone(shift).isoformat() for k, v in claim["interval"].items()}
            for item in claim["evidence"]:
                if item["type"] == "curve_segment":
                    for key in ("start", "end"):
                        item[key] = parse_ts(item[key]).astimezone(shift).isoformat()
        shifted.append(claim)
    tools.accepted = []
    for stage, kind in (("pre_departure", "pre_departure"), ("investigation", "deviation")):
        tools.stage = stage
        assert tools.write_case_file([c for c in shifted if c["kind"] == kind])["rejected"] == []
    write_case(tmp_path / "case", tools.dossier, tools.rules, tools.accepted, tools.observations, pre, tools.journal)
    assert verify_case(tmp_path / "case") == []


def test_a_local_date_in_a_statement_is_refused_when_submitted_not_when_the_record_is_written():
    # The record is in UTC: 01:15+12:00 on the 4th is 13:15 UTC on the 3rd. A statement giving the 4th
    # used to pass at submission (raw date) and then sink the whole record at write_case.
    from datetime import timedelta, timezone

    from lcw.dossier import parse_ts

    tools, _, claims, _ = scripted_run(folder_of("explained_by_handler"))
    tools.stage = "investigation"
    shift = timezone(timedelta(hours=12))
    dated = []
    for claim in (c for c in claims if c["kind"] == "deviation"):
        claim = dict(claim, evidence=[dict(e) for e in claim["evidence"]])
        claim["interval"] = {k: parse_ts(v).astimezone(shift).isoformat() for k, v in claim["interval"].items()}
        for item in claim["evidence"]:
            if item["type"] == "curve_segment":
                for key in ("start", "end"):
                    item[key] = parse_ts(item[key]).astimezone(shift).isoformat()
        claim["statement"] = f"On {claim['interval']['start'][:10]}, " + claim["statement"]
        dated.append(claim)
    if all(c["interval"]["start"][:10] == parse_ts(c["interval"]["start"]).strftime("%Y-%m-%d") for c in dated):
        pytest.skip("no deviation crosses midnight under this offset")
    report = tools.write_case_file(dated)
    crossing = [c["id"] for c in dated
                if c["interval"]["start"][:10] != parse_ts(c["interval"]["start"]).strftime("%Y-%m-%d")]
    assert {r["id"] for r in report["rejected"]} >= set(crossing)
