"""Deterministic evaluation of the pre-departure rule cards (R01–R06).

Input: what the models read (``observations``), never ground truth. The agent proposes a
decision; the verifier recomputes it with this module from the evidence the agent cites.
"""

from __future__ import annotations

from .rules import Rule


def _field(observations: dict, document: str, name: str):
    return observations.get("documents", {}).get(document, {}).get(name)


def evaluate_rule(rule: Rule, observations: dict) -> dict:
    """Return ``{"rule", "outcome": "satisfied"|"violated"|"unreadable", "details"}``."""
    check = rule.check
    kind = check["type"]
    details: dict = {}
    outcome = "satisfied"

    if kind == "field_contains":
        value = _field(observations, check["document"], check["field"])
        details["value"] = value
        if value is None:
            outcome = "unreadable"
        elif check["value"] not in (value if isinstance(value, list) else str(value).split()):
            outcome = "violated"
    elif kind == "field_true":
        value = _field(observations, check["document"], check["field"])
        details["value"] = value
        if value is None:
            outcome = "unreadable"
        elif value is not True:
            outcome = "violated"
    elif kind == "fields_equal":
        values = {f"{f['document']}.{f['field']}": _field(observations, f["document"], f["field"])
                  for f in check["fields"]}
        details["values"] = values
        if any(v is None for v in values.values()):
            outcome = "unreadable"
        elif len({str(v) for v in values.values()}) > 1:
            outcome = "violated"
    elif kind in ("crate_feature_present", "crate_arrows_up", "crate_awb_matches"):
        crates = observations.get("crates", {})
        expected_crates = set(observations.get("expected_crates") or crates)
        missing = sorted(expected_crates - set(crates))
        if not crates or missing:
            return {"rule": rule.id, "outcome": "unreadable",
                    "details": {"crates": len(crates), "not_segmented": missing}}
        failing, unreadable = [], []
        expected_awb = _field(observations, check.get("document", "awb"), check.get("field", "awb_number"))
        feature_name = {"crate_feature_present": check.get("feature"), "crate_arrows_up": "orientation_arrows",
                        "crate_awb_matches": "awb_number"}[kind]
        for crate_id, features in sorted(crates.items()):
            if (features.get(feature_name) or {}).get("readable") is False:
                unreadable.append(crate_id)  # found but not read: never counted as a violation
                continue
            if kind == "crate_feature_present":
                ok = bool(features.get(check["feature"], {}).get("present"))
            elif kind == "crate_arrows_up":
                arrows = features.get("orientation_arrows", {})
                ok = bool(arrows.get("present")) and arrows.get("direction") == "up"
            else:
                ok = expected_awb is not None and features.get("awb_number", {}).get("value") == expected_awb
            if not ok:
                failing.append(crate_id)
        details["failing_crates"] = failing
        if unreadable:
            details["unreadable_crates"] = unreadable
        if kind == "crate_awb_matches" and expected_awb is None:
            outcome = "unreadable"
        elif failing:
            outcome = "violated"
        elif unreadable:
            outcome = "unreadable"
    else:
        raise ValueError(f"{rule.id}: not a pre-departure check ({kind})")
    return {"rule": rule.id, "outcome": outcome, "details": details}


def evaluate(rules: dict[str, Rule], observations: dict) -> dict:
    """Evaluate every active pre-departure rule. Decision is ``block`` if any rule is violated
    or unreadable (a document that cannot be read is not accepted)."""
    results = [evaluate_rule(rule, observations) for rule in rules.values()
               if rule.active and rule.phase == "pre_departure"]
    violated = [r["rule"] for r in results if r["outcome"] == "violated"]
    unreadable = [r["rule"] for r in results if r["outcome"] == "unreadable"]
    decision = "block" if violated or unreadable else "go"
    return {"decision": decision, "violated_rules": violated, "unreadable_rules": unreadable,
            "results": results}
