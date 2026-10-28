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
    module = load("check_ca06")
    ok, outcomes = module.run()
    assert ok and len(outcomes) == 5
    claim = module.base_claim(module.Toolset(module.Dossier(module.DEFAULT), backend="offline"))
    assert [name for name, _, _ in module.injected(claim)] == [name for name, _ in outcomes]


def test_output_scan_finds_forbidden_words_in_records(tmp_path):
    release = load("check_release")
    (tmp_path / "cases" / "X").mkdir(parents=True)
    (tmp_path / "cases" / "X" / "pv.md").write_text("The heifers looked sick.")
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "X.json").write_text('{"content": "sick"}')  # raw run, outside the record
    report = release.Report()
    release.check_outputs(report, tmp_path)
    assert report.failures == ["cases/X/pv.md: forbidden vocabulary ['sick']"]


def test_recording_list_covers_the_demo_dossiers(monkeypatch, capsys):
    # DEMO-02's handler answer is filmed: it must be on the list of sentences to record.
    monkeypatch.setattr(sys, "argv", ["recording_list.py", "DEMO-02", "DEV-02"])
    load("recording_list").main()
    out = capsys.readouterr().out
    assert "| DEMO-02 | new/bench/demo/DEMO-02/voice/audio/H1.m4a | ground handler |" in out
    assert "| DEV-02 | new/bench/dev/DEV-02/voice/audio/H1.m4a | ground handler |" in out
