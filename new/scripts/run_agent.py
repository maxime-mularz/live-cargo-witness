"""Run the agent on one dossier.

Usage:
  python new/scripts/run_agent.py new/bench/dev/DEV-02              # live: Meta models, keys in .env
  python new/scripts/run_agent.py new/bench/dev/DEV-02 --dry-run    # plumbing check, no model

Writes <out>/results/<id>.json, <out>/cases/<id>/ (record, journal.html, manifest) and
<out>/runs/<id>.json. Default out: new/results/live (or new/results/dry-run).
"""
import argparse
import json
import sys
from pathlib import Path

import _path  # noqa: F401
from lcw import NEW_DIR
from lcw.env import load_dotenv
from lcw.runner import run_dossier


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dossier", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--dry-run", action="store_true",
                        help="scripted client + offline tools (reads expected.json): plumbing only")
    parser.add_argument("--max-steps", type=int, default=40)
    args = parser.parse_args()
    if "reserved" in args.dossier.resolve().parts and args.dry_run:
        raise SystemExit("No dry run on the reserved bench.")
    if args.dry_run:
        sys.path.insert(0, str(NEW_DIR / "tests"))
        from fake_model import ScriptedClient
        out = args.out or NEW_DIR / "results" / "dry-run"
        result = run_dossier(args.dossier, out, client=ScriptedClient(args.dossier), backend="offline",
                             max_steps=args.max_steps)
    else:
        loaded = load_dotenv()
        print(f"Loaded from .env: {', '.join(loaded) or 'nothing'}")
        out = args.out or NEW_DIR / "results" / "live"
        result = run_dossier(args.dossier, out, backend="live", max_steps=args.max_steps)
    print(json.dumps(result, indent=2))
    print(f"Journal page: {out / 'cases' / result['dossier_id'] / 'journal.html'}")


if __name__ == "__main__":
    main()
