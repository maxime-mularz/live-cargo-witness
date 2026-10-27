"""Minimal .env loader (no dependency). Values already in the environment win."""

from __future__ import annotations

import os
import re
from pathlib import Path

from . import NEW_DIR

_LOADED: set[str] = set()
_SECRET_NAME = re.compile(r"(?i)(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)")


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
    _LOADED.update(loaded)
    return loaded


SECRET_VARIABLES = ("META_MODEL_API_KEY", "BASETEN_API_KEY", "MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET",
                    "TIVE_API_KEY", "RESERVED_PASSWORD")
_SECRET_PATTERNS = [
    re.compile(r"(?i)\b(bearer|basic)(\s+)[^\s\"',;&]+"),
    re.compile(r"(?i)(token|api[_-]?key|authorization|secret|password)([\"':= ]+)(?!bearer\b|basic\b)[^\s\"',;&]+"),
    re.compile(r"[A-Za-z0-9_\-]{32,}"),  # long opaque tokens
]


def redact(text: str) -> str:
    """Remove secrets from a message before it reaches the model, the journal or a log file."""
    text = str(text)
    names = set(SECRET_VARIABLES) | _LOADED | {n for n in os.environ if _SECRET_NAME.search(n)}
    for name in sorted(names, key=lambda n: -len(os.environ.get(n, ""))):
        value = os.environ.get(name)
        if value and len(value) >= 6:
            text = text.replace(value, f"[{name}]")
    for pattern in _SECRET_PATTERNS[:2]:
        text = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", text)
    return _SECRET_PATTERNS[2].sub("[redacted]", text)
