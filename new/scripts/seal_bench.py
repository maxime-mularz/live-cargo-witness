"""Print (or check) the seal of a bench folder: one SHA-256 over every file it contains.

Usage:
  python new/scripts/seal_bench.py new/bench/reserved            # print the seal
  python new/scripts/seal_bench.py new/bench/reserved --check new/bench/reserved.seal

The seal of the reserved bench is committed in new/bench/reserved.seal BEFORE the code freeze.
After the freeze, --check (or unseal_bench.py) proves the dossiers were not changed since.
README.md and .gitkeep are ignored.
"""
import argparse
import sys
from pathlib import Path

import _path  # noqa: F401
from lcw.hashing import seal_folder


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--check", type=Path, help="file holding the committed seal")
    args = parser.parse_args()
    seal = seal_folder(args.folder)
    if args.check:
        committed = args.check.read_text(encoding="utf-8").split()[0]
        if committed != seal:
            print(f"MISMATCH\n committed {committed}\n computed  {seal}")
            sys.exit(1)
        print(f"MATCH — {seal}")
        return
    print(seal)


if __name__ == "__main__":
    main()
