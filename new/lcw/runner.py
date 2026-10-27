"""Run the agent on one dossier or a whole bench and write everything to disk.

For each dossier:
    <out>/results/<id>.json   result in the scoring format (lcw.score)
    <out>/cases/<id>/         shared handover record + journal page + manifest (lcw.casefile)
    <out>/runs/<id>.json      raw run: stage outcomes, errors, journal (for debugging)
"""

from __future__ import annotations

from pathlib import Path

from .agent import Agent, ModelClient
from .casefile import RejectedClaims, write_case
from .dossier import Dossier, write_json
from .tools import Toolset


def run_dossier(folder: Path | str, out_dir: Path | str, client: ModelClient | None = None,
                backend: str = "live", max_steps: int = 40) -> dict:
    folder, out_dir = Path(folder), Path(out_dir)
    dossier = Dossier(folder)
    tools = Toolset(dossier, backend=backend)
    run = Agent(tools, client=client, max_steps=max_steps).run()
    result = run.result

    case_status = "not written"
    if run.pre_departure.final is not None and result["decision_matches_readings"]:
        try:
            write_case(out_dir / "cases" / dossier.id, dossier, tools.rules, tools.accepted,
                       tools.observations, run.deterministic_pre_departure, tools.journal)
            case_status = "written"
        except RejectedClaims as error:
            case_status = f"refused: {error}"
        except ValueError as error:
            case_status = f"refused: {error}"
    elif run.pre_departure.final is not None:
        case_status = "refused: the agent's decision does not match its own readings"

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


def run_bench(bench_dir: Path | str, out_dir: Path | str, client_factory=None,
              backend: str = "live", only: list[str] | None = None) -> list[dict]:
    """Run every dossier of a bench. ``client_factory(folder)`` builds a client per dossier
    (None = the production Meta client)."""
    results = []
    for folder in sorted(p for p in Path(bench_dir).iterdir() if (p / "dossier.json").exists()):
        if only and folder.name not in only:
            continue
        client = client_factory(folder) if client_factory else None
        results.append(run_dossier(folder, out_dir, client=client, backend=backend))
    return results
