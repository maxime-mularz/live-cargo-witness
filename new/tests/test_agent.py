import json

from conftest import DEV, dossier_dirs
from fake_model import ScriptedClient
from lcw.agent import Agent
from lcw.casefile import verify_case
from lcw.dossier import Dossier, load_json
from lcw.runner import run_bench, run_dossier
from lcw.score import score_bench
from lcw.tools import Toolset


def folder_of(category):
    return next(f for f in dossier_dirs() if load_json(f / "expected.json")["category"] == category)


def test_loop_plumbing_scores_perfectly(tmp_path):
    run_bench(DEV, tmp_path, client_factory=ScriptedClient, backend="offline")
    metrics = score_bench(DEV, tmp_path / "results")["metrics"]
    assert metrics["phase 1 decisions correct"] == {"passed": 20, "total": 20}
    assert metrics["investigations fully correct"] == {"passed": 14, "total": 14}
    for result in (tmp_path / "results").iterdir():
        data = load_json(result)
        assert data["case"] == "written", (result.name, data["case"])
        assert data["errors"] == []
    for case in (tmp_path / "cases").iterdir():
        assert verify_case(case) == []
        assert (case / "journal.html").exists()


def test_rejected_claim_is_fixed_and_shown_in_journal(tmp_path):
    folder = folder_of("explained_by_handler")
    result = run_dossier(folder, tmp_path, client=ScriptedClient(folder, bad_first_submission=True),
                         backend="offline")
    assert result["case"] == "written"
    page = (tmp_path / "cases" / result["dossier_id"] / "journal.html").read_text()
    assert "rejected C1" in page and "number 37" in page
    assert "SAM 3.1 · offline stand-in" in page and "stored transcript (no recording)" in page
    assert "Offline run" in page and "scripted test client" in page
    assert "SYNTHETIC" in page and "Ground handler asked" in page


def test_blocked_consignment_is_not_investigated(tmp_path):
    folder = folder_of("defect_R03")
    result = run_dossier(folder, tmp_path, client=ScriptedClient(folder), backend="offline")
    assert result["phase1"] == {"decision": "block", "violated_rules": ["R03"]}
    assert result["investigation"] is None
    run = load_json(tmp_path / "runs" / f"{result['dossier_id']}.json")
    assert all(e.get("stage") != "investigation" for e in run["journal"])


def test_tool_errors_go_back_to_the_model(tmp_path):
    folder = folder_of("compliant")

    class Clumsy:
        def __init__(self):
            self.seen_error = False

        def chat(self, messages, tools):
            if messages[-1]["role"] == "tool":
                self.seen_error = "error" in messages[-1]["content"]
                return {"content": json.dumps({"decision": "block", "violated_rules": []}), "tool_calls": []}
            return {"content": None, "tool_calls": [{"id": "1", "name": "read_document",
                                                     "arguments": {"document": "passport"}}]}

    clumsy = Clumsy()
    tools = Toolset(Dossier(folder), backend="offline")
    Agent(tools, client=clumsy).run()
    assert clumsy.seen_error
    assert any(e.get("type") == "error" for e in tools.journal)


def test_stage_tools_are_enforced(tmp_path):
    folder = folder_of("compliant")

    class Sneaky:
        def chat(self, messages, tools):
            names = {t["name"] for t in tools}
            assert "ask_handler" not in names if "STAGE 1" in messages[0]["content"] else True
            if messages[-1]["role"] == "tool":
                return {"content": json.dumps({"decision": "go", "violated_rules": []}), "tool_calls": []}
            return {"content": None, "tool_calls": [{"id": "1", "name": "ask_handler",
                                                     "arguments": {"question": "?", "start": "x", "end": "y"}}]}

    tools = Toolset(Dossier(folder), backend="offline")
    Agent(tools, client=Sneaky(), max_steps=3)._loop("pre_departure", "STAGE 1", "go")
    assert any(e.get("type") == "error" and "not available" in e["error"] for e in tools.journal)


def test_non_json_final_answer_is_an_error(tmp_path):
    folder = folder_of("compliant")

    class Chatty:
        def chat(self, messages, tools):
            return {"content": "All good, ship it!", "tool_calls": []}

    result = run_dossier(folder, tmp_path, client=Chatty(), backend="offline")
    assert result["errors"] and result["case"].startswith("not written")


def test_agent_never_sees_ground_truth(tmp_path):
    folder = folder_of("indeterminate")

    class Spy:
        def __init__(self):
            self.text = ""

        def chat(self, messages, tools):
            self.text += json.dumps(messages, default=str)
            if len([m for m in messages if m["role"] == "assistant"]) == 0 and "STAGE 1" in messages[0]["content"]:
                return {"content": json.dumps({"decision": "go", "violated_rules": []}), "tool_calls": []}
            return {"content": json.dumps({"summary": "x"}), "tool_calls": []}

    spy = Spy()
    run_dossier(folder, tmp_path, client=spy, backend="offline")
    assert "handler_call_expected" not in spy.text and '"category"' not in spy.text
