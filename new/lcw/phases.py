"""Flight phase segmentation (EF-08).

Two modes, chosen per dossier in ``phase_model.mode``:

* ``schedule`` — phases cut from the actual times entered by people (departure in the entry
  record, stopover and arrival at reception). Takeoff and landing are windows of
  ``takeoff_window_min`` / ``landing_window_min`` minutes, a Marfik configuration parameter
  recorded in the dossier with its source. This is the fallback when the sensor does not measure
  pressure, acceleration or position.
* ``sensor`` — reserved for sensors that measure pressure or position; not implemented until the
  sensor model is known (see the spec, task of Oct 27).
"""

from __future__ import annotations

from datetime import timedelta

from .dossier import format_ts, parse_ts

PHASES = ("ground_departure", "takeoff", "cruise", "landing", "stopover", "ground_arrival")


def segment(record: dict) -> list[dict]:
    """Return the ordered list of phases ``{name, leg, start, end}`` (end exclusive)."""
    model = record.get("phase_model", {})
    mode = model.get("mode", "schedule")
    if mode != "schedule":
        raise NotImplementedError(f"phase mode {mode!r} not implemented yet")

    schedule = record["schedule"]
    takeoff_window = timedelta(minutes=model["takeoff_window_min"])
    landing_window = timedelta(minutes=model["landing_window_min"])

    legs = []
    for index in (1, 2):
        takeoff = schedule.get(f"takeoff_{index}")
        landing = schedule.get(f"landing_{index}")
        if takeoff and landing:
            legs.append((index, parse_ts(takeoff), parse_ts(landing)))
    if not legs:
        raise ValueError("schedule has no flight leg")

    phases = []

    def add(name: str, leg: int | None, start, end) -> None:
        if end > start:
            phases.append({"name": name, "leg": leg, "start": format_ts(start), "end": format_ts(end)})

    add("ground_departure", None, parse_ts(schedule["loading_start"]), legs[0][1])
    for position, (leg, takeoff, landing) in enumerate(legs):
        climb_end = min(takeoff + takeoff_window, landing)
        descent_start = max(landing - landing_window, climb_end)
        add("takeoff", leg, takeoff, climb_end)
        add("cruise", leg, climb_end, descent_start)
        add("landing", leg, descent_start, landing)
        if position + 1 < len(legs):
            add("stopover", None, landing, legs[position + 1][1])
    add("ground_arrival", None, legs[-1][2], parse_ts(schedule["unloading_end"]))
    return phases


def phase_at(phases: list[dict], timestamp: str) -> str | None:
    """Name of the phase containing ``timestamp`` (None if outside the recorded journey)."""
    moment = parse_ts(timestamp)
    for phase in phases:
        if parse_ts(phase["start"]) <= moment < parse_ts(phase["end"]):
            return phase["name"]
    if phases and moment == parse_ts(phases[-1]["end"]):
        return phases[-1]["name"]
    return None
