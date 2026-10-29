"""Notification drafts (the optional ``draft_notification`` tool, CLAUDE.md rule 6).

A draft is a fixed English template filled only with facts already in the record: the dossier
id and, for each claim accepted by the verifier, its rule id, the rule card title, the status
label, its interval (HH:MM UTC) and its verified statement. No model text enters a draft, so a
draft cannot carry a value the verifier has not checked (rule 4) nor a forbidden word (rule 5).

Nothing is ever sent: a draft opens with ``DRAFT_HEADER`` and a human reviews, signs and sends.
``write_case`` re-renders the drafts from the final record's claims into ``drafts/<recipient>.md``,
so a draft in the case folder always matches the record it sits next to and is in the manifest.
"""

from __future__ import annotations

from pathlib import Path

from .journal_page import STATUS_LABEL
from .rules import Rule

RECIPIENTS = {"shipper": "Shipper", "carrier": "Carrier", "ground_handler": "Ground handler"}
DRAFT_HEADER = "DRAFT — NOT SENT. A human reviews, signs and sends."


def _when(claim: dict) -> str:
    interval = claim.get("interval") or {}
    if interval.get("start") and interval.get("end"):
        return f"{interval['start'][11:16]}–{interval['end'][11:16]} UTC"
    return "pre-departure check"


def render_draft(recipient: str, dossier_id: str, synthetic: bool, claims: list[dict],
                 rules: dict[str, Rule]) -> str:
    """The draft body. ``claims`` must be claims the verifier accepted."""
    if recipient not in RECIPIENTS:
        raise ValueError(f"recipient must be one of {', '.join(RECIPIENTS)}, got {recipient!r}")
    if not claims:
        raise ValueError("no claim accepted by the verifier yet: a draft can only report verified "
                         "claims; submit them with write_case_file first")
    lines = [DRAFT_HEADER, "", f"To: {RECIPIENTS[recipient]}", f"Dossier: {dossier_id}", ""]
    if synthetic:
        lines += ["SYNTHETIC — fictitious dossier generated for testing. Not a real shipment.", ""]
    lines += ["The shared handover record of this dossier holds the following claims, each checked "
              "by the non-AI verifier:", ""]
    for claim in claims:
        rule = rules[claim["rule"]]
        lines.append(f"- {claim['rule']} — {rule.title} — {STATUS_LABEL[claim['status']]} — {_when(claim)}")
        lines.append(f"  {claim['statement']}")
    lines += ["", "The record is valid only once signed by the shipper, the carrier and the ground handler.", ""]
    return "\n".join(lines)


def write_drafts(case_dir: Path, recipients: list[str], dossier_id: str, synthetic: bool,
                 claims: list[dict], rules: dict[str, Rule]) -> None:
    """Write ``drafts/<recipient>.md`` for each recipient asked for (none = no folder). An
    optional draft never blocks the record: with no claim there is nothing to draft."""
    if not claims:
        return
    for recipient in sorted(set(recipients)):
        text = render_draft(recipient, dossier_id, synthetic, claims, rules)
        target = Path(case_dir) / "drafts" / f"{recipient}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
