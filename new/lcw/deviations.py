"""Deterministic deviation detection on a sensor curve (EF-09).

This is a tool the agent calls; it finds where the curve breaks a rule card. It does not decide
whether a deviation is explained, a false positive or indeterminate: that is the agent's job.
"""

from __future__ import annotations

from datetime import timedelta

from .dossier import parse_ts
from .phases import phase_at
from .rules import Rule, resolve_threshold


def _out_of_bounds(rule: Rule, value: float, threshold) -> bool:
    kind = rule.check["type"]
    if kind == "series_within_range":
        low, high = threshold
        return value < low or value > high
    if kind == "series_below":
        return value > threshold
    raise ValueError(f"{rule.id}: not a curve rule ({kind})")


def _applies(rule: Rule, phase: str | None) -> bool:
    if phase is None:
        return False
    included = rule.check.get("phases")
    excluded = rule.check.get("exclude_phases", [])
    if included is not None and phase not in included:
        return False
    return phase not in excluded


def detect(curve: list[dict], phases: list[dict], rules: dict[str, Rule], record: dict,
           sampling_minutes: int | None = None) -> dict:
    """Return ``{"deviations": [...], "unresolved_rules": [...]}``.

    Each deviation: rule, series, start, end (timestamps of the first and last samples out of
    bounds), phase (phase of the first sample), peak, threshold, threshold_source, samples.
    Consecutive out-of-bounds samples, at most one sampling period apart and in the same phase,
    form one deviation.
    """
    sampling = timedelta(minutes=sampling_minutes or record["sensor"]["sampling_minutes"])
    deviations: list[dict] = []
    unresolved: list[str] = []

    for rule in rules.values():
        if not rule.active or rule.phase != "investigation":
            continue
        resolved = resolve_threshold(rule, record)
        if resolved is None:
            unresolved.append(rule.id)
            continue
        threshold, source = resolved
        series = rule.check["series"]
        current: dict | None = None

        for row in curve:
            phase = phase_at(phases, row["timestamp"])
            value = row[series]
            breach = _applies(rule, phase) and _out_of_bounds(rule, value, threshold)
            if breach:
                contiguous = (
                    current is not None
                    and current["phase"] == phase
                    and parse_ts(row["timestamp"]) - parse_ts(current["end"]) <= sampling
                )
                if contiguous:
                    current["end"] = row["timestamp"]
                    current["samples"] += 1
                    if abs(value - _reference(threshold)) > abs(current["peak"] - _reference(threshold)):
                        current["peak"] = value
                else:
                    if current:
                        deviations.append(current)
                    current = {
                        "rule": rule.id, "series": series, "start": row["timestamp"],
                        "end": row["timestamp"], "phase": phase, "peak": value,
                        "threshold": threshold, "threshold_source": source, "samples": 1,
                    }
            elif current:
                deviations.append(current)
                current = None
        if current:
            deviations.append(current)

    deviations.sort(key=lambda d: (d["start"], d["rule"]))
    return {"deviations": deviations, "unresolved_rules": unresolved}


def _reference(threshold) -> float:
    """Middle of a range, or the limit itself, used to keep the furthest value as the peak."""
    if isinstance(threshold, (list, tuple)):
        return (threshold[0] + threshold[1]) / 2
    return 0.0


def values_in(curve: list[dict], series: str, start: str, end: str) -> list[float]:
    """Values of ``series`` between ``start`` and ``end`` included."""
    first, last = parse_ts(start), parse_ts(end)
    return [row[series] for row in curve if first <= parse_ts(row["timestamp"]) <= last]
