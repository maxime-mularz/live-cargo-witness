"""Run the agent on one dossier or a whole bench and write everything to disk.

For each dossier:
    <out>/results/<id>.json   result in the scoring format (lcw.score)
    <out>/cases/<id>/         shared handover record + journal page + manifest (lcw.casefile)
    <out>/runs/<id>.json      raw run: stage outcomes, errors, journal (for debugging)
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .agent import Agent, ModelClient
from .casefile import RejectedClaims, write_case
from .dossier import Dossier, write_json
from .env import redact
from .tools import Toolset


def run_dossier(folder: Path | str, out_dir: Path | str, client: ModelClient | None = None,
                backend: str = "live", max_steps: int = 40) -> dict:
    folder, out_dir = Path(folder), Path(out_dir)
    dossier = Dossier(folder)
    tools = Toolset(dossier, backend=backend)
    case_dir = out_dir / "cases" / dossier.id
    if case_dir.exists():  # never leave the record of an earlier run next to this run's result
        shutil.rmtree(case_dir)
    run = Agent(tools, client=client, max_steps=max_steps).run()
    result = run.result

    case_status = case_refusal(run)
    if case_status is None:
        try:
            write_case(case_dir, dossier, tools.rules, tools.accepted,
                       tools.observations, run.deterministic_pre_departure, tools.journal,
                       drafts=[d["recipient"] for d in tools.drafts])
            case_status = "written"
        except (RejectedClaims, ValueError) as error:  # IncompleteCase is a ValueError
            case_status = f"refused: {error}"
        except Exception as error:  # write_case writes atomically: nothing is left behind
            case_status = f"not written: {type(error).__name__}: {redact(error)}"

    result["case"] = case_status
    write_json(out_dir / "results" / f"{dossier.id}.json", result)
    write_json(out_dir / "runs" / f"{dossier.id}.json", {
        "dossier_id": dossier.id,
        "pre_departure": {"final": run.pre_departure.final, "steps": run.pre_departure.steps,
                          "error": run.pre_departure.error},
        "investigation": None if run.investigation is None else {
            "final": run.investigation.final, "steps": run.investigation.steps,
            "error": run.investigation.error},
        "deterministic_pre_departure": run.deterministic_pre_departure,
        "journal": tools.journal,
    })
    return result


def case_refusal(run) -> str | None:
    """Why the record must not be written for this run (None = it may be written)."""
    if run.result["errors"]:
        return "not written: the run did not finish cleanly (" + "; ".join(run.result["errors"]) + ")"
    if run.pre_departure.final is None or run.result["phase1"]["decision"] is None:
        return "not written: no pre-departure decision"
    if not run.result["decision_matches_readings"]:
        return "refused: the agent's decision does not match its own readings"
    if run.result["phase1"]["decision"] == "go" and run.investigation is not None \
            and run.investigation.final is None:
        return "not written: the investigation has no final answer"
    return None


def run_bench(bench_dir: Path | str, out_dir: Path | str, client_factory=None,
              backend: str = "live", only: list[str] | None = None) -> list[dict]:
    """Run every dossier of a bench. ``client_factory(folder)`` builds a client per dossier
    (None = the production Meta client)."""
    results = []
    for folder in sorted(p for p in Path(bench_dir).iterdir() if (p / "dossier.json").exists()):
        if only and folder.name not in only:
            continue
        try:
            client = client_factory(folder) if client_factory else None
            results.append(run_dossier(folder, out_dir, client=client, backend=backend))
        except Exception as error:  # one broken dossier must not stop the bench
            result = {"dossier_id": folder.name, "phase1": None, "investigation": None,
                      "errors": [f"run crashed: {type(error).__name__}: {redact(error)}"],
                      "case": "not written"}
            write_json(Path(out_dir) / "results" / f"{folder.name}.json", result)
            results.append(result)
    return results
