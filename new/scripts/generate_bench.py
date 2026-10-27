"""Regenerate the development bench (20 fictitious dossiers) — EF-18.

Usage: python new/scripts/generate_bench.py [--out new/bench/dev] [--seed 20261027]
Deterministic: the same seed always gives the same dossiers. Never point it at bench/reserved.
"""
import argparse
import shutil
from collections import Counter
from pathlib import Path

import _path  # noqa: F401
from lcw import BENCH_DIR
from lcw.synth import build_bench


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=BENCH_DIR / "dev")
    parser.add_argument("--seed", type=int, default=20261027)
    args = parser.parse_args()
    if "reserved" in args.out.resolve().parts:
        raise SystemExit("Refusing to generate into the reserved bench.")
    if args.out.exists():
        shutil.rmtree(args.out)
    expected = build_bench(args.out, seed=args.seed)
    counts = Counter(e["category"] for e in expected)
    print(f"{len(expected)} dossiers written to {args.out}")
    for category, count in sorted(counts.items()):
        print(f"  {category:24s} {count}")


if __name__ == "__main__":
    main()
