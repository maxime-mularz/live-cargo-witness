import copy

from lcw.dossier import write_json
from lcw.score import score_bench

from conftest import DEV, dossier_dirs
from helpers import scripted_run


def write_results(tmp_path, transform=None):
    out = tmp_path / "results"
    for folder in dossier_dirs():
        result = scripted_run(folder)[3]
        if transform:
            result = transform(copy.deepcopy(result))
        if result is not None:
            write_json(out / f"{result['dossier_id']}.json", result)
    return out


def test_scripted_run_scores_perfectly(tmp_path):
    report = score_bench(DEV, write_results(tmp_path))
    metrics = report["metrics"]
    assert metrics["missing_results"] == 0
    assert metrics["CA-03 defects blocked with the right rule"] == {"passed": 6, "total": 6}
    assert metrics["CA-04 false blocks on compliant dossiers"] == {"count": 0, "total": 4}
    assert metrics["CA-07 handler called when (and only when) needed"] == {"passed": 10, "total": 10}
    assert metrics["CA-08 false positives dismissed"] == {"passed": 2, "total": 2}
    assert metrics["CA-09 indeterminate after asking"] == {"passed": 2, "total": 2}


def test_errors_are_counted(tmp_path):
    def always_call_and_go(result):
        result["phase1"] = {"decision": "go", "violated_rules": []}
        if result["investigation"]:
            result["investigation"]["handler_called"] = True
        return result
    metrics = score_bench(DEV, write_results(tmp_path, always_call_and_go))["metrics"]
    assert metrics["CA-03 defects blocked with the right rule"]["passed"] == 0
    assert metrics["CA-07 handler called when (and only when) needed"]["passed"] == 5


def test_missing_results_are_reported(tmp_path):
    metrics = score_bench(DEV, tmp_path / "nothing")["metrics"]
    assert metrics["missing_results"] == 20
