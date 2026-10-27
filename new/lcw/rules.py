"""Rule cards loader (R01–R10) and threshold resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import RULES_DIR

REQUIRED_KEYS = ("id", "title", "phase", "check", "threshold", "source", "evidence_expected",
                 "action", "status")


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    title_fr: str
    phase: str
    check: dict
    threshold: dict | None
    source: dict
    evidence_expected: str
    action: str
    status: str
    raw: dict = field(repr=False, compare=False, default_factory=dict)

    @property
    def active(self) -> bool:
        return self.status == "active"


def _validate(card: dict, path: Path) -> None:
    missing = [k for k in REQUIRED_KEYS if k not in card]
    if missing:
        raise ValueError(f"{path.name}: missing keys {missing}")
    if card["phase"] not in ("pre_departure", "investigation"):
        raise ValueError(f"{path.name}: unknown phase {card['phase']!r}")
    if card["action"] not in ("block", "flag"):
        raise ValueError(f"{path.name}: unknown action {card['action']!r}")
    if card["status"] not in ("active", "disabled"):
        raise ValueError(f"{path.name}: unknown status {card['status']!r}")
    threshold = card["threshold"]
    # Rule cards never hard-code a value: a threshold always points into the dossier.
    if threshold is not None and (set(threshold) != {"from", "path"} or threshold["from"] != "dossier"):
        raise ValueError(f"{path.name}: threshold must be {{from: dossier, path: ...}}")


def load_rules(rules_dir: Path | str = RULES_DIR) -> dict[str, Rule]:
    """Load every ``R*.yaml`` card, keyed by id, in id order."""
    rules: dict[str, Rule] = {}
    for path in sorted(Path(rules_dir).glob("R*.yaml")):
        card = yaml.safe_load(path.read_text(encoding="utf-8"))
        _validate(card, path)
        if card["id"] in rules:
            raise ValueError(f"duplicate rule id {card['id']}")
        rules[card["id"]] = Rule(
            id=card["id"], title=card["title"], title_fr=card.get("title_fr", ""),
            phase=card["phase"], check=card["check"], threshold=card["threshold"],
            source=card["source"], evidence_expected=card["evidence_expected"],
            action=card["action"], status=card["status"], raw=card,
        )
    return rules


def get_path(data: Any, path: str) -> Any:
    """Read a dotted path such as ``declared.temperature_range_c`` or ``a.b[0].c``."""
    current = data
    for part in path.replace("]", "").split("."):
        name, _, index = part.partition("[")
        if name:
            if not isinstance(current, dict) or name not in current:
                raise KeyError(path)
            current = current[name]
        if index:
            current = current[int(index)]
    return current


def resolve_threshold(rule: Rule, dossier: dict) -> tuple[Any, str] | None:
    """Return ``(value, source_path)`` for a rule's threshold, or None if it cannot be resolved.

    A rule whose threshold is unresolved triggers no decision (no invented values).
    """
    if rule.threshold is None:
        return None
    try:
        value = get_path(dossier, rule.threshold["path"])
    except (KeyError, IndexError, TypeError):
        return None
    if value is None:
        return None
    return value, rule.threshold["path"]
