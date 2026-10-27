"""Dossier loading and time helpers.

A dossier is a folder:

    dossier.json                 entry record + pointers to the pieces
    documents/<name>.png         air waybill, certification, loading list
    documents/<name>.truth.json  offline stand-in for read_document (tests only)
    photos/crate_NN.png          crate photos
    photos/crate_NN.truth.json   offline stand-in for segment_crate (tests only)
    sensor/curve.csv             sensor export (absent when departure was blocked)
    voice/convoy_notes.json      transcribed notes dictated by the convoy attendant
    voice/handler_answers.json   offline stand-in for ask_handler (recorded answers)
    expected.json                ground truth, read only by lcw.score
"""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def parse_ts(value: str) -> datetime:
    """Parse an ISO 8601 timestamp (``Z`` or ``+00:00`` offsets, models emit both) into UTC.
    A timestamp without offset is taken as UTC."""
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def format_ts(value: datetime) -> str:
    return value.astimezone(UTC).strftime(ISO_FORMAT)


def load_json(path: Path) -> dict | list:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class Dossier:
    """Read-only view of a dossier folder. Never exposes ``expected.json`` to the agent."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.record: dict = load_json(self.root / "dossier.json")
        self.id: str = self.record["id"]

    @property
    def synthetic(self) -> bool:
        return bool(self.record.get("synthetic"))

    def path(self, relative: str) -> Path:
        resolved = (self.root / relative).resolve()
        if self.root.resolve() not in resolved.parents and resolved != self.root.resolve():
            raise ValueError(f"path escapes the dossier: {relative}")
        if resolved.name == "expected.json":
            raise PermissionError("expected.json is ground truth, not agent input")
        return resolved

    def curve(self) -> list[dict] | None:
        relative = self.record.get("sensor_curve")
        if not relative:
            return None
        rows = []
        with self.path(relative).open(encoding="utf-8", newline="") as handle:
            lines = [line for line in handle if not line.startswith("#")]
        for row in csv.DictReader(lines):
            rows.append({
                "timestamp": row["timestamp"],
                "temperature_c": float(row["temperature_c"]),
                "light_lux": float(row["light_lux"]),
                "shock_g": float(row["shock_g"]),
            })
        return rows

    def convoy_notes(self) -> list[dict]:
        relative = self.record.get("voice_notes")
        return load_json(self.path(relative)) if relative else []

    def handler_answers(self) -> list[dict]:
        relative = self.record.get("handler_answers")
        return load_json(self.path(relative)) if relative else []

    def document_truth(self, name: str) -> dict:
        image = self.record["documents"][name]
        return load_json(self.path(image.replace(".png", ".truth.json")))

    def photo_truths(self) -> list[dict]:
        return [load_json(self.path(p.replace(".png", ".truth.json")))
                for p in self.record.get("photos", [])]
