"""Recompute every SHA-256 of a shared handover record folder.

Usage: python new/scripts/verify_case.py <case_dir>
Exit code 0 = intact, 1 = something was modified, added or removed.
"""
import sys
from pathlib import Path

import _path  # noqa: F401
from lcw.casefile import verify_case
from lcw.dossier import load_json


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    case_dir = Path(sys.argv[1])
    problems = verify_case(case_dir)
    root = load_json(case_dir / "manifest.json")["root"]
    if problems:
        print("NOT INTACT")
        for problem in problems:
            print(" -", problem)
        sys.exit(1)
    print(f"INTACT — root {root}")


if __name__ == "__main__":
    main()
