import sys
from pathlib import Path

import pytest

NEW_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NEW_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lcw import BENCH_DIR  # noqa: E402
from lcw.rules import load_rules  # noqa: E402

DEV = BENCH_DIR / "dev"


@pytest.fixture(scope="session")
def rules():
    return load_rules()


@pytest.fixture(scope="session")
def dev_dir():
    return DEV


def dossier_dirs():
    return sorted(p for p in DEV.iterdir() if (p / "dossier.json").exists())
