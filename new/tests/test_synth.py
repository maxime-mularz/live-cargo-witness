from collections import Counter

from lcw.dossier import load_json
from lcw.hashing import sha256_file
from lcw.synth import build_bench

from conftest import dossier_dirs


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
