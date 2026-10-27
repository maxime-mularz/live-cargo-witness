"""Score agent results against a bench.

Usage: python new/scripts/score_bench.py <bench_dir> <results_dir> [--md score.md] [--json score.json]
"""
import argparse
import json
from pathlib import Path

import _path  # noqa: F401
from lcw.score import score_bench, to_markdown


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bench", type=Path)
    parser.add_argument("results", type=Path)
    parser.add_argument("--md", type=Path, help="write the markdown table here")
    parser.add_argument("--json", type=Path, help="write the full report here")
    parser.add_argument("--title", default=None)
    args = parser.parse_args()
    report = score_bench(args.bench, args.results)
    markdown = to_markdown(report, args.title or f"Score — {args.bench.name}")
    print(markdown)
    if args.md:
        args.md.write_text(markdown, encoding="utf-8")
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
