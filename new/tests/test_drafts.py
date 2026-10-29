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
