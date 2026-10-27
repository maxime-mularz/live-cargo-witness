"""Regression tests for the second review of the agent loop (one test per finding)."""
import copy
import json

import pytest

from conftest import dossier_dirs
from fake_model import ScriptedClient
from helpers import read_everything, scripted_run
from lcw.agent import Agent, _clip, final_json, normalise_decision
from lcw.casefile import IncompleteCase, missing_claims, write_case
from lcw.dossier import Dossier, load_json
from lcw.env import redact
from lcw.journal_page import render
from lcw.runner import run_bench, run_dossier
from lcw.tools import MAX_WINDOW_ROWS, Toolset
from lcw.verifier import Verifier


def folder_of(category):
    return next(f for f in dossier_dirs() if load_json(f / "expected.json")["category"] == category)


class Dropping(ScriptedClient):
    """Scripted client that leaves out the last stage-2 claim (an incomplete investigation)."""

    def __init__(self, folder):
        super().__init__(folder)
        for i, (name, arguments) in enumerate(self.plans["STAGE 2"]):
            if name == "write_case_file":
                arguments = copy.deepcopy(arguments)
                arguments["claims"] = arguments["claims"][:-1]
                self.plans["STAGE 2"][i] = (name, arguments)


# 1 — the record is never written for an incomplete investigation

def test_record_refused_when_a_deviation_has_no_claim(tmp_path):
    folder = folder_of("explained_by_handler")  # several deviations
    result = run_dossier(folder, tmp_path, client=Dropping(folder), backend="offline")
    assert result["case"].startswith("refused: incomplete record")
    assert not (tmp_path / "cases" / result["dossier_id"]).exists()


def test_record_refused_when_investigation_errors(tmp_path):
    folder = folder_of("explained_by_note")

    class StopsMidway(ScriptedClient):
        def chat(self, messages, tools):
            if "STAGE 2" in messages[0]["content"]:
                raise TimeoutError("provider timeout")
            return super().chat(messages, tools)

    result = run_dossier(folder, tmp_path, client=StopsMidway(folder), backend="offline")
    assert result["case"].startswith("not written")
    assert any("TimeoutError" in e for e in result["errors"])


def test_write_case_lists_what_is_missing(tmp_path):
    folder = folder_of("explained_by_handler")
    tools, pre, claims, _ = scripted_run(folder)
    partial = [c for c in claims if c["kind"] == "pre_departure"] + [c for c in claims if c["kind"] == "deviation"][1:]
    assert missing_claims(tools.dossier, tools.rules, partial, tools.observations)
    with pytest.raises(IncompleteCase):
        write_case(tmp_path / "case", tools.dossier, tools.rules, partial, tools.observations, pre, tools.journal)


def test_blocked_record_needs_a_claim_per_violated_rule(tmp_path):
    folder = folder_of("defect_R03")
    tools = Toolset(Dossier(folder), backend="offline")
    pre = read_everything(tools)
    assert missing_claims(tools.dossier, tools.rules, [], tools.observations) == ["R03 is violated but has no claim"]
    with pytest.raises(IncompleteCase):
        write_case(tmp_path / "case", tools.dossier, tools.rules, [], tools.observations, pre, tools.journal)


# 2 — malformed model output

def test_string_arguments_and_missing_name_are_handled():
    folder = folder_of("compliant")

    class Sloppy:
        model_name = "sloppy"

        def __init__(self):
            self.step = 0

        def chat(self, messages, tools):
            self.step += 1
            if self.step == 1:
                return {"content": None, "tool_calls": [
                    {"id": "a", "arguments": {}},                                   # no name
                    {"id": "b", "name": "read_document", "arguments": '{"document": "awb"}'},
                    {"id": "c", "name": "read_document", "arguments": "[1, 2]"}]}  # not an object
            return {"content": 'Done. {"decision": "GO", "violated_rules": "r01"}', "tool_calls": []}

    tools = Toolset(Dossier(folder), backend="offline")
    outcome = Agent(tools, client=Sloppy(), max_steps=5)._loop("pre_departure", "STAGE 1", "go")
    errors = [e["error"] for e in tools.journal if e["type"] == "error"]
    assert any("without a name" in e for e in errors) and any("JSON object" in e for e in errors)
    assert "awb" in tools.observations["documents"]
    decision, rules, problems = normalise_decision(outcome.final)
    assert decision == "go" and rules == ["R01"] and problems == []


def test_invalid_decisions_are_reported():
    assert normalise_decision({"decision": "maybe"})[0] is None
    decision, rules, problems = normalise_decision({"decision": "block", "violated_rules": ["R3", 7]})
    assert decision == "block" and rules == [] and problems


def test_clipped_result_is_still_json():
    text = _clip({"rows": ["x" * 100] * 1000})
    assert json.loads(text)["truncated"] is True


def test_sensor_window_is_capped():
    folder = folder_of("explained_by_note")
    tools = Toolset(Dossier(folder), backend="offline")
    schedule = tools.dossier.record["schedule"]
    result = tools.get_sensor_curve(schedule["loading_start"], schedule["unloading_end"])
    assert len(result["window"]) == MAX_WINDOW_ROWS and "window_truncated" in result


def test_one_crashing_dossier_does_not_stop_the_bench(tmp_path):
    folders = dossier_dirs()[:2]

    def factory(folder):
        if folder == folders[0]:
            raise RuntimeError("broken client")
        return ScriptedClient(folder)

    results = run_bench(folders[0].parent, tmp_path, client_factory=factory, backend="offline",
                        only=[f.name for f in folders])
    assert len(results) == 2
    assert results[0]["errors"][0].startswith("run crashed") and results[1]["case"] == "written"


# 3 — final JSON wrapped in prose

def test_final_json_in_prose_keeps_the_answer_object():
    text = ('I checked {"R03": "ok"} and here is my answer:\n'
            '```json\n{"decision": "block", "violated_rules": ["R03"]}\n```')
    assert final_json(text, ("decision",)) == {"decision": "block", "violated_rules": ["R03"]}
    assert final_json("no json here", ("decision",)) is None


# 4 — a failed handler call is not a handler call

def test_failed_ask_handler_is_not_counted(tmp_path):
    folder = folder_of("explained_by_handler")

    class Fails(ScriptedClient):
        def __init__(self, folder):
            super().__init__(folder)
            stage2 = self.plans["STAGE 2"]
            self.plans["STAGE 2"] = [stage2[0], ("ask_handler", {"question": "?", "start": "not a time",
                                                                 "end": "x"}),
                                     ("final", {"summary": "done"})]

    result = run_dossier(folder, tmp_path, client=Fails(folder), backend="offline")
    assert result["investigation"]["handler_called"] is False


# 5 — claim kinds per stage and id collisions

def test_stage_claim_kind_and_ids():
    folder = folder_of("explained_by_note")
    tools, pre, claims, _ = scripted_run(folder)
    deviation = next(c for c in claims if c["kind"] == "deviation")
    fresh = Toolset(Dossier(folder), backend="offline")
    read_everything(fresh)
    fresh.get_sensor_curve()
    fresh.convoy_notes()
    fresh.stage = "pre_departure"
    report = fresh.write_case_file([deviation])
    assert report["accepted"] == [] and "only 'pre_departure'" in report["rejected"][0]["reasons"][0]

    fresh.stage = "investigation"
    assert fresh.write_case_file([deviation])["accepted"] == [deviation["id"]]
    twice = fresh.write_case_file([deviation, deviation])
    assert any("used twice" in r for item in twice["rejected"] for r in item["reasons"])

    # an id accepted at stage 1 cannot be reused at stage 2
    blocked_folder = folder_of("defect_R03")
    b_tools, b_pre, b_claims, _ = scripted_run(blocked_folder)
    b_tools.accepted, b_tools.claim_stage = [], {}
    b_tools.stage = "pre_departure"
    assert b_tools.write_case_file(b_claims)["accepted"] == ["C1"]
    b_tools.stage = "investigation"
    reused = dict(deviation, id="C1")
    reasons = b_tools.write_case_file([reused])["rejected"][0]["reasons"]
    assert any("already used at stage pre_departure" in r for r in reasons)


# 6 — journal page labels and counters

def test_rejected_then_fixed_counts_only_fixed_ids():
    pv = {"dossier_id": "X", "synthetic": True, "pre_departure": {"decision": "go"}, "claims": []}
    journal = [
        {"type": "tool", "tool": "write_case_file",
         "result": {"accepted": [], "rejected": [{"id": "C1"}, {"id": "C2"}]}},
        {"type": "tool", "tool": "write_case_file", "result": {"accepted": ["C1"], "rejected": []}},
        {"type": "error", "tool": "ask_handler", "error": "bad time"},
    ]
    page = render(pv, journal)
    assert "<b>Claims rejected, then fixed</b><span>1</span>" in page
    assert "<b>Ground handler asked</b><span>0</span>" in page


# 7 — free model text is masked and labelled

def test_model_text_is_masked_and_labelled():
    pv = {"dossier_id": "X", "synthetic": True, "pre_departure": {"decision": "go"}, "claims": []}
    journal = [{"type": "message", "model": "Muse Spark Open", "content": "The heifers looked sick."},
               {"type": "tool", "tool": "lookup_rule", "reason": "Maybe an injury?",
                "result": {"id": "R07", "title": "t"}}]
    page = render(pv, journal)
    assert "sick" not in page and "injury" not in page.lower()
    assert "[withheld]" in page and "unverified model text" in page


# 8 — the verifier and the record use the notes the agent saw

def test_verifier_uses_the_transcript_the_agent_saw():
    folder = folder_of("explained_by_note")
    tools = Toolset(Dossier(folder), backend="offline")
    notes = tools.convoy_notes()
    tools.observations["convoy_notes"] = [dict(n, text="Transcript at 99 minutes.") for n in notes]
    verifier = Verifier(tools.dossier, tools.rules, tools.observations)
    assert all(n["text"] == "Transcript at 99 minutes." for n in verifier.notes.values())


# 9 — secrets never leave in error messages

def test_redact_removes_keys(monkeypatch):
    monkeypatch.setenv("BASETEN_API_KEY", "sk-test-1234567890")
    token = "abcdef" * 6  # built at run time so the release check does not flag this file
    text = redact(f"401 for key sk-test-1234567890; header Authorization: Bearer {token}")
    assert "sk-test-1234567890" not in text and "abcdefabcdef" not in text
    assert "[BASETEN_API_KEY]" in text


def test_model_errors_are_redacted(monkeypatch):
    monkeypatch.setenv("BASETEN_API_KEY", "sk-test-1234567890")
    folder = folder_of("compliant")

    class Leaky:
        def chat(self, messages, tools):
            raise RuntimeError("bad request with key sk-test-1234567890")

    tools = Toolset(Dossier(folder), backend="offline")
    outcome = Agent(tools, client=Leaky())._loop("pre_departure", "STAGE 1", "go")
    assert "sk-test-1234567890" not in outcome.error and "[BASETEN_API_KEY]" in outcome.error


# ---------------------------------------------------------------- third review (fixes to the fixes)

def _bare_tools(folder):
    tools = Toolset(Dossier(folder), backend="offline")
    read_everything(tools)
    tools.get_sensor_curve()
    tools.convoy_notes()
    tools.stage = "investigation"
    return tools


def test_wide_claim_cannot_stand_for_the_deviations():
    folder = folder_of("indeterminate")
    tools = _bare_tools(folder)
    schedule = tools.dossier.record["schedule"]
    rule = next(iter({d["rule"] for d in tools.get_sensor_curve()["deviations"]}))
    card = tools.rules[rule]
    wide = {"id": "C9", "kind": "deviation", "rule": rule, "status": "explained_rule_exceeded",
            "interval": {"start": schedule["loading_start"], "end": schedule["unloading_end"]},
            "statement": "The rule was exceeded during the flight.",
            "evidence": [{"type": "curve_segment", "series": card.check["series"],
                          "start": schedule["loading_start"], "end": schedule["unloading_end"]},
                         {"type": "dossier_field", "path": card.threshold["path"]},
                         {"type": "voice_note", "id": "N1"}]}
    report = tools.write_case_file([wide])
    assert report["accepted"] == []
    assert any("returned by get_sensor_curve" in r for r in report["rejected"][0]["reasons"])
    assert missing_claims(tools.dossier, tools.rules, [wide], tools.observations)


def test_lazy_block_writes_no_record(tmp_path):
    folder = folder_of("compliant")

    class Lazy:
        def chat(self, messages, tools):
            return {"content": '{"decision": "block", "violated_rules": []}', "tool_calls": []}

    result = run_dossier(folder, tmp_path, client=Lazy(), backend="offline")
    assert result["phase1"]["decision"] == "block"
    assert result["case"].startswith("refused") and "could not be checked" in result["case"]
    assert not (tmp_path / "cases" / result["dossier_id"]).exists()


def test_refused_rerun_removes_the_previous_record(tmp_path):
    folder = folder_of("explained_by_handler")
    first = run_dossier(folder, tmp_path, client=ScriptedClient(folder), backend="offline")
    assert first["case"] == "written"
    second = run_dossier(folder, tmp_path, client=Dropping(folder), backend="offline")
    assert second["case"].startswith("refused")
    assert not (tmp_path / "cases" / first["dossier_id"]).exists()


def test_integer_claim_ids_are_rejected():
    folder = folder_of("explained_by_note")
    tools, pre, claims, _ = scripted_run(folder)
    fresh = _bare_tools(folder)
    deviation = dict(next(c for c in claims if c["kind"] == "deviation"), id=1)
    report = fresh.write_case_file([deviation, dict(deviation, id="C2")])
    assert report["accepted"] == ["C2"]
    assert "non-empty string" in report["rejected"][0]["reasons"][0]


def test_non_string_reason_does_not_break_the_record(tmp_path):
    folder = folder_of("explained_by_note")

    class ListReason(ScriptedClient):
        def chat(self, messages, tools):
            reply = super().chat(messages, tools)
            for call in reply["tool_calls"]:
                call["arguments"]["reason"] = ["check", "this"]
            return reply

    result = run_dossier(folder, tmp_path, client=ListReason(folder), backend="offline")
    assert result["case"] == "written"
    assert not list((tmp_path / "cases").glob("*.partial"))


def test_record_shows_no_forbidden_word(tmp_path):
    folder = folder_of("explained_by_handler")

    class Wordy(ScriptedClient):
        def chat(self, messages, tools):
            reply = super().chat(messages, tools)
            for call in reply["tool_calls"]:
                if call["name"] == "ask_handler":
                    call["arguments"]["question"] = "Were any animals injured or dead?"
            return reply

    from lcw.vocab import find_forbidden
    result = run_dossier(folder, tmp_path, client=Wordy(folder, bad_first_submission=True), backend="offline")
    case = tmp_path / "cases" / result["dossier_id"]
    assert result["case"] == "written"
    assert find_forbidden((case / "journal.html").read_text()) == []
    assert find_forbidden((case / "journal.json").read_text()) == []
    raw = (tmp_path / "runs" / f"{result['dossier_id']}.json").read_text()
    assert "injured" in raw  # the raw journal is kept for debugging, outside the record


def test_final_json_ignores_nested_objects():
    text = ('Here is my answer: {"decision": "go", "violated_rules": [], '
            '"checks": [{"rule": "R01", "decision": "satisfied"}]}')
    assert final_json(text, ("decision",))["decision"] == "go"


def test_transcription_failure_falls_back_to_stored_text(monkeypatch, tmp_path):
    import shutil

    from lcw import tools as tools_module
    folder = tmp_path / "D"
    shutil.copytree(folder_of("explained_by_note"), folder)
    (folder / "voice" / "audio").mkdir(parents=True)
    (folder / "voice" / "audio" / "N1.m4a").write_bytes(b"fake")

    def boom(path):
        raise ConnectionError("provider down")

    monkeypatch.setattr(tools_module.models, "transcribe", boom)
    live = Toolset(Dossier(folder), backend="live")
    notes = live.convoy_notes()
    assert [n["text"] for n in notes] == [n["text"] for n in Dossier(folder).convoy_notes()]
    assert any(e["type"] == "error" and "N1" in e["error"] for e in live.journal)

    declared = {"id": "N9", "audio": "voice/audio/missing.m4a"}
    assert live._audio(declared) is None


def test_redact_short_bearer_and_any_key_variable(monkeypatch):
    monkeypatch.setenv("SOME_PROVIDER_API_KEY", "pk-123456789")
    text = redact("Authorization: Bearer sk_live_abcd1234 and pk-123456789")
    assert "sk_live_abcd1234" not in text and "pk-123456789" not in text


def test_ca02_numbers_compare_as_numbers():
    import importlib.util
    import sys

    from lcw import NEW_DIR
    sys.path.insert(0, str(NEW_DIR / "scripts"))
    spec = importlib.util.spec_from_file_location("test_ca02_script", NEW_DIR / "scripts" / "test_ca02.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.same([10, 24], [10.0, 24.0])
    assert not module.same(True, 1) and not module.same("3", 3) and not module.same(1, True)
