"""Live Cargo Witness — black-box investigator agent for live animal air cargo.

Built during the Meta Global AI Developer Hackathon (Oct 27 – Nov 4, 2026).
"""

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
NEW_DIR = PACKAGE_DIR.parent
RULES_DIR = NEW_DIR / "rules"
BENCH_DIR = NEW_DIR / "bench"

# Deviation statuses the agent may assign (EF-12).
STATUSES = (
    "explained_compliant",
    "explained_rule_exceeded",
    "false_positive_dismissed",
    "indeterminate",
)

__all__ = ["BENCH_DIR", "NEW_DIR", "PACKAGE_DIR", "RULES_DIR", "STATUSES"]
