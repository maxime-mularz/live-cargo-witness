from lcw.dossier import Dossier, load_json
from lcw.tools import Toolset

from conftest import dossier_dirs
from helpers import read_everything


def test_pre_departure_decisions_match_expected(rules):
    for folder in dossier_dirs():
        tools = Toolset(Dossier(folder), rules=rules)
        result = read_everything(tools)
        expected = load_json(folder / "expected.json")["phase1"]
        assert result["decision"] == expected["decision"], folder.name
        assert result["violated_rules"] == expected["violated_rules"], folder.name


def test_unreadable_document_blocks(rules):
    folder = dossier_dirs()[0]
    tools = Toolset(Dossier(folder), rules=rules)
    read_everything(tools)
    del tools.observations["documents"]["certification"]["signed"]
    from lcw.predeparture import evaluate
    assert evaluate(rules, tools.observations)["decision"] == "block"


def test_agent_cannot_read_ground_truth(rules):
    import pytest
    tools = Toolset(Dossier(dossier_dirs()[0]), rules=rules)
    with pytest.raises(PermissionError):
        tools.dossier.path("expected.json")
