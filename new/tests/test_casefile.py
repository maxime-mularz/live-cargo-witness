import pytest

from lcw.casefile import RejectedClaims, verify_case, write_case
from lcw.dossier import load_json

from conftest import dossier_dirs
from helpers import scripted_run


def handler_folder():
    return next(f for f in dossier_dirs()
                if load_json(f / "expected.json")["category"] == "explained_by_handler")


def build(tmp_path):
    tools, pre, claims, result = scripted_run(handler_folder())
    case = tmp_path / "case"
    manifest = write_case(case, tools.dossier, tools.rules, claims, tools.observations, pre, tools.journal)
    return case, manifest, tools, pre, claims


def test_case_is_written_and_intact(tmp_path):
    case, manifest, *_ = build(tmp_path)
    assert verify_case(case) == []
    text = (case / "pv.md").read_text()
    assert "SYNTHETIC" in text and "Signatures" in text and "Ground handler" in text
    assert "expected.json" not in " ".join(manifest["files"])
    assert not list(case.rglob("*.truth.json"))
    journal = load_json(case / "journal.json")
    assert {entry["tool"] for entry in journal} >= {"read_document", "segment_crate",
                                                     "get_sensor_curve", "ask_handler"}


def test_tampering_is_detected(tmp_path):
    case, *_ = build(tmp_path)
    curve = case / "pieces" / "sensor" / "curve.csv"
    curve.write_text(curve.read_text().replace("timestamp", "timestamp "))
    (case / "pieces" / "extra.txt").write_text("added later")
    problems = verify_case(case)
    assert "modified: pieces/sensor/curve.csv" in problems
    assert "not in manifest: pieces/extra.txt" in problems


def test_rejected_claim_never_enters_the_record(tmp_path):
    tools, pre, claims, result = scripted_run(handler_folder())
    claims[0]["statement"] += " About 99 animals were affected."
    with pytest.raises(RejectedClaims):
        write_case(tmp_path / "case", tools.dossier, tools.rules, claims, tools.observations, pre,
                   tools.journal)
    assert not (tmp_path / "case").exists()
