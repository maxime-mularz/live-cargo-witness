"""Run the agent on every dossier of a bench, then score it.

Usage:
  python new/scripts/run_bench.py new/bench/dev                    # live, Meta models
  python new/scripts/run_bench.py new/bench/dev --only DEV-02 DEV-07
  python new/scripts/run_bench.py new/bench/dev --dry-run          # plumbing check, no model

The reserved bench is run once, after the code freeze, live only.
"""
import argparse
import sys
from pathlib import Path

import _path  # noqa: F401
from lcw import NEW_DIR
from lcw.env import load_dotenv
from lcw.runner import run_bench
from lcw.score import score_bench, to_markdown


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("bench", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    reserved = "reserved" in args.bench.resolve().parts
    if reserved and args.dry_run:
        raise SystemExit("No dry run on the reserved bench.")
    name = args.bench.resolve().name
    if args.dry_run:
        sys.path.insert(0, str(NEW_DIR / "tests"))
        from fake_model import ScriptedClient
        out = args.out or NEW_DIR / "results" / f"dry-run-{name}"
        run_bench(args.bench, out, client_factory=ScriptedClient, backend="offline", only=args.only)
        title = f"Plumbing check on {name} (scripted client, NOT the agent)"
    else:
        load_dotenv()
        out = args.out or NEW_DIR / "results" / f"live-{name}"
        run_bench(args.bench, out, backend="live", only=args.only)
        title = f"Live Cargo Witness on {name} (Meta models)"
    report = score_bench(args.bench, out / "results")
    markdown = to_markdown(report, title)
    (out / "score.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"Written to {out}")


if __name__ == "__main__":
    main()
