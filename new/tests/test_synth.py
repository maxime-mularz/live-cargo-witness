from collections import Counter

from conftest import dossier_dirs
from lcw.dossier import load_json
from lcw.hashing import sha256_file
from lcw.synth import build_bench


def test_bench_composition(dev_dir):
    expected = [load_json(d / "expected.json") for d in dossier_dirs()]
    counts = Counter(e["category"] for e in expected)
    assert len(expected) == 20
    assert counts["compliant"] == 4
    assert sum(v for k, v in counts.items() if k.startswith("defect_")) == 6
    assert {k for k in counts if k.startswith("defect_")} == {f"defect_R0{i}" for i in range(1, 7)}
    assert (counts["explained_by_note"], counts["explained_by_handler"],
            counts["false_positive"], counts["indeterminate"]) == (3, 3, 2, 2)
    calls = [e for e in expected if e["investigation"] and e["investigation"]["handler_call_expected"]]
    assert len(calls) == 5


def test_every_dossier_is_labelled_synthetic():
    for folder in dossier_dirs():
        record = load_json(folder / "dossier.json")
        assert record["synthetic"] is True and "FICTITIOUS" in record["notice"]
        curve = folder / "sensor" / "curve.csv"
        if curve.exists():
            assert curve.read_text().startswith("# SYNTHETIC")


def test_committed_bench_matches_generator(tmp_path):
    """bench/dev must be exactly what the generator produces (no hand edits). PNGs are skipped:
    their pixels depend on the fonts installed on the machine."""
    build_bench(tmp_path)
    for folder in dossier_dirs():
        for path in folder.rglob("*"):
            if path.is_file() and path.suffix in (".json", ".csv"):
                twin = tmp_path / folder.name / path.relative_to(folder)
                assert twin.exists(), twin
                assert sha256_file(path) == sha256_file(twin), path


def test_demo_dossiers_match_the_storyboard(tmp_path):
    from lcw import BENCH_DIR
    from lcw.synth import build_demo

    demo = BENCH_DIR / "demo"
    build_demo(tmp_path)
    for path in demo.rglob("*"):
        if path.is_file() and path.suffix in (".json", ".csv"):
            assert sha256_file(path) == sha256_file(tmp_path / path.relative_to(demo)), path
    one, two, three = (load_json(demo / f"DEMO-0{i}" / "expected.json") for i in (1, 2, 3))
    # Scenario 1: 12 heads on the air waybill, 10 on the certification, one arrow down.
    assert one["phase1"] == {"decision": "block", "violated_rules": ["R03", "R05"]}
    counts = {d: load_json(demo / "DEMO-01" / "documents" / f"{d}.truth.json")["fields"]["head_count"]["value"]
              for d in ("awb", "certification")}
    assert counts == {"awb": 12, "certification": 10}
    # Scenario 2: stopover temperature, shock and light; the note says no handling; the handler explains.
    assert two["investigation"]["handler_call_expected"] is True
    assert {d["rule"] for d in two["investigation"]["deviations"]} == {"R07", "R09", "R10"}
    assert {d["phase"] for d in two["investigation"]["deviations"]} == {"stopover"}
    notes = load_json(demo / "DEMO-02" / "voice" / "convoy_notes.json")
    assert any("no handling" in n["text"] for n in notes)
    # Scenario 3: a light peak at departure inside the declared inspection, dismissed without a call.
    assert three["investigation"]["handler_call_expected"] is False
    assert [d["status"] for d in three["investigation"]["deviations"]] == ["false_positive_dismissed"]
    for folder in demo.iterdir():
        assert load_json(folder / "dossier.json")["synthetic"] is True
