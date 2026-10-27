"""SHA-256 helpers: file hashes, folder seals, case-file manifests (EF-16)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

CHUNK = 1 << 16


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(data) -> bytes:
    """Stable JSON encoding: sorted keys, no extra spaces, UTF-8."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def tree_hashes(root: Path | str, exclude: tuple[str, ...] = ()) -> dict[str, str]:
    """``{relative_path: sha256}`` for every file under ``root`` (POSIX paths, sorted)."""
    root = Path(root)
    hashes = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative in exclude:
            continue
        hashes[relative] = sha256_file(path)
    return hashes


def seal_folder(root: Path | str, exclude: tuple[str, ...] = ("README.md", ".gitkeep")) -> str:
    """One SHA-256 for a whole folder: hash of the canonical list of (path, file hash)."""
    return sha256_bytes(canonical_json(tree_hashes(root, exclude=exclude)))
