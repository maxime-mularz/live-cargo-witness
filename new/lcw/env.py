"""Minimal .env loader (no dependency). Values already in the environment win."""

from __future__ import annotations

import os
from pathlib import Path

from . import NEW_DIR


def load_dotenv(path: Path | str | None = None) -> list[str]:
    """Load ``KEY=VALUE`` lines from the repository's ``.env``. Returns the keys loaded
    (never their values)."""
    path = Path(path) if path else NEW_DIR.parent / ".env"
    loaded = []
    if not path.exists():
        return loaded
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded
