"""Extracting the JSON object a model was asked for from its free-text answer."""

from __future__ import annotations

import json
import re


def final_json(text: str | None, keys: tuple[str, ...]) -> dict | None:
    """Extract the model's final JSON object, even when wrapped in prose or code fences.
    Prefers the last object that carries one of ``keys``."""
    if not text:
        return None
    stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        value = json.loads(stripped)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    found: list[dict] = []
    position = 0
    while (start := text.find("{", position)) != -1:  # top-level objects only, never nested ones
        try:
            value, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            position = start + 1
            continue
        if isinstance(value, dict):
            found.append(value)
        position = end
    with_keys = [v for v in found if any(k in v for k in keys)]
    return (with_keys or found or [None])[-1]
