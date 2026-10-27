"""Acceptance-criteria scripts, run offline."""
import importlib.util
import sys

from lcw import NEW_DIR

sys.path.insert(0, str(NEW_DIR / "scripts"))


def load(name):
    spec = importlib.util.spec_from_file_location(f"script_{name}", NEW_DIR / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ca06_five_unsourced_claims_are_rejected():
    ok, outcomes = load("check_ca06").run()
    assert ok and len(outcomes) == 5
    assert all(reasons for _, reasons in outcomes)


def test_output_scan_finds_forbidden_words_in_records(tmp_path):
    release = load("check_release")
    (tmp_path / "cases" / "X").mkdir(parents=True)
    (tmp_path / "cases" / "X" / "pv.md").write_text("The heifers looked sick.")
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "X.json").write_text('{"content": "sick"}')  # raw run, outside the record
    report = release.Report()
    release.check_outputs(report, tmp_path)
    assert report.failures == ["cases/X/pv.md: forbidden vocabulary ['sick']"]
