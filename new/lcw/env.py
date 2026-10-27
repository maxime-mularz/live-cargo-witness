"""Minimal .env loader (no dependency). Values already in the environment win."""

from __future__ import annotations

import os
import re
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


SECRET_VARIABLES = ("META_MODEL_API_KEY", "BASETEN_API_KEY", "MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET",
                    "TIVE_API_KEY", "RESERVED_PASSWORD")
_SECRET_PATTERNS = [
    re.compile(r"(?i)(bearer|token|api[_-]?key|authorization|secret|password)([\"':= ]+)[^\s\"',;&]+"),
    re.compile(r"[A-Za-z0-9_\-]{32,}"),  # long opaque tokens
]


def redact(text: str) -> str:
    """Remove secrets from a message before it reaches the model, the journal or a log file."""
    text = str(text)
    for name in SECRET_VARIABLES:
        value = os.environ.get(name)
        if value and len(value) >= 6:
            text = text.replace(value, f"[{name}]")
    text = _SECRET_PATTERNS[0].sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", text)
    return _SECRET_PATTERNS[1].sub("[redacted]", text)
