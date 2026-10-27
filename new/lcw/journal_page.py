"""Investigation journal page (EF-13).

One self-contained HTML file per case: no external script, font or stylesheet, so it opens from
the case folder and its hash is part of the record. Each row is one step of the agent:
hypothesis (the model's stated reason), tool, Meta model behind it, what came back, and the
verifier's verdict when claims were submitted (rejections are the visible revisions).
"""

from __future__ import annotations

import html
import json

from .vocab import mask_deep, mask_forbidden

STATUS_LABEL = {
    "explained_compliant": "Explained, compliant",
    "explained_rule_exceeded": "Explained, rule exceeded",
    "false_positive_dismissed": "False positive, dismissed",
    "indeterminate": "Indeterminate",
    "violated": "Violated",
    "satisfied": "Satisfied",
}

MODEL_CLASS = {
    "Muse Spark Open": "m-spark-open",
    "SAM 3.1": "m-sam",
    "SAM 3.1 + Muse Spark Open": "m-sam",
    "Muse Voice Transcribe": "m-voice",
    "Muse Spark": "m-spark",
}

CSS = """
:root{--bg:#f6f8fb;--card:#fff;--ink:#0b1b33;--quiet:#5b6b80;--line:#dde3ea;--accent:#14b8b8;
--warn:#b45309;--bad:#b91c1c;--ok:#15803d;--navy:#061b3a}
@media (prefers-color-scheme:dark){:root{--bg:#020817;--card:#0b1730;--ink:#e7edf5;--quiet:#9fb0c4;
--line:#1e2d47;--navy:#e7edf5}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:24px 16px 64px}
.banner{background:var(--warn);color:#fff;font-weight:700;letter-spacing:.06em;text-align:center;
padding:6px 12px;border-radius:6px;margin-bottom:16px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:32px 0 12px}
.sub{color:var(--quiet);margin:0 0 20px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.card b{display:block;font-size:13px;color:var(--quiet);font-weight:600}
.card span{font-size:20px;font-weight:700}
.go{color:var(--ok)}.block{color:var(--bad)}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);
border-radius:10px;overflow:hidden}
th,td{text-align:left;vertical-align:top;padding:9px 10px;border-bottom:1px solid var(--line)}
th{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--quiet);background:var(--bg)}
tr.stage td{background:var(--navy);color:var(--bg);font-weight:700;font-size:13px}
.badge{display:inline-block;border-radius:999px;padding:1px 8px;font-size:12px;font-weight:600;
border:1px solid var(--line);white-space:nowrap}
.m-spark-open{background:#14b8b81f;border-color:#14b8b8}.m-sam{background:#6366f11f;border-color:#6366f1}
.m-voice{background:#f59e0b1f;border-color:#f59e0b}.m-spark{background:#0ea5e91f;border-color:#0ea5e9}
.m-det{color:var(--quiet)}
.reason{font-style:italic}.quote{border-left:3px solid var(--accent);padding-left:8px;margin:4px 0}
.rej{color:var(--bad);font-weight:600}.acc{color:var(--ok);font-weight:600}
.err{color:var(--bad)}code{font-size:13px}
.small{font-size:13px;color:var(--quiet)}
@media (max-width:700px){.hide-sm{display:none}td,th{padding:7px}}
"""


def _e(value) -> str:
    return html.escape(str(value), quote=True)


def _badge(model: str | None, backend: str | None = None) -> str:
    if not model:
        return ""
    css = MODEL_CLASS.get(model, "m-det")
    label = model
    if backend == "offline" and model in MODEL_CLASS:
        label = f"{model} · offline stand-in"
    return f'<span class="badge {css}">{_e(label)}</span>'


def _summary(entry: dict) -> str:
    tool, result = entry.get("tool"), entry.get("result")
    if tool == "read_document":
        fields = {k: v for k, v in (result or {}).items() if not k.startswith("_")}
        keep = ["awb_number", "head_count", "handling_codes", "signed", "handling_information"]
        parts = [f"<code>{_e(k)}</code> = {_e(json.dumps(fields[k], ensure_ascii=False))}"
                 for k in keep if k in fields]
        return f"{_e(entry['arguments'].get('document'))}: " + "; ".join(parts)
    if tool == "segment_crate":
        features = result or {}
        label = features.get("live_animals_label", {}).get("present")
        arrows = features.get("orientation_arrows", {})
        plate = features.get("awb_number", {}).get("value")
        return (f"{_e(entry['arguments'].get('photo'))}: label {'present' if label else 'MISSING'}, "
                f"arrows {_e(arrows.get('direction') or 'MISSING')}, plate {_e(plate)}")
    if tool == "get_sensor_curve":
        if not result or not result.get("available"):
            return "no sensor curve"
        if result.get("window") is not None:
            return f"{len(result['window'])} samples between {_e(entry['arguments'].get('start', '')[11:16])} " \
                   f"and {_e(entry['arguments'].get('end', '')[11:16])} UTC"
        items = [f"{_e(d['rule'])} {_e(d['start'][11:16])}–{_e(d['end'][11:16])} ({_e(d['phase'])}, "
                 f"peak {_e(d['peak'])})" for d in result.get("deviations", [])]
        text = f"{len(items)} deviation(s)" + (": " + "; ".join(items) if items else "")
        if result.get("synthetic"):
            text += ' <span class="small">[SYNTHETIC curve]</span>'
        return text
    if tool == "ask_handler":
        answer = result or {}
        return (f"Asked about {_e(entry['arguments'].get('start', '')[11:16])}–"
                f"{_e(entry['arguments'].get('end', '')[11:16])} UTC: {_e(entry['arguments'].get('question'))}"
                f'<div class="quote">{_e(answer.get("id"))}: “{_e(answer.get("answer"))}”</div>')
    if tool == "convoy_notes":
        notes = result or []
        return "".join(f'<div class="quote">{_e(n["id"])} {_e(n["time"][11:16])} UTC: “{_e(n["text"])}”</div>'
                       for n in notes) or "no notes"
    if tool == "lookup_rule":
        card = result or {}
        return f"{_e(card.get('id'))} — {_e(card.get('title'))}"
    if tool == "write_case_file":
        report = result or {}
        parts = []
        if report.get("accepted"):
            parts.append(f'<span class="acc">accepted {_e(", ".join(map(str, report["accepted"])))}</span>')
        for item in report.get("rejected", []):
            reasons = "; ".join(item.get("reasons", []))
            parts.append(f'<div><span class="rej">rejected {_e(item.get("id"))}</span> — {_e(reasons)}</div>')
        return " ".join(parts) or "nothing submitted"
    if tool == "draft_notification":
        return f"draft for {_e((result or {}).get('recipient'))} — not sent"
    return _e(json.dumps(result, ensure_ascii=False, default=str)[:300])


def _rejected_then_fixed(tool_entries: list[dict]) -> int:
    """Claim ids the verifier rejected and that were accepted in a later submission."""
    rejected: set[str] = set()
    fixed: set[str] = set()
    for entry in tool_entries:
        if entry.get("tool") != "write_case_file":
            continue
        report = entry.get("result") or {}
        fixed |= set(report.get("accepted", [])) & rejected
        rejected |= {str(item.get("id")) for item in report.get("rejected", [])}
    return len(fixed)


def render(pv: dict, journal: list[dict]) -> str:
    stage_names = {"pre_departure": "Stage 1 — pre-departure check (connected)",
                   "investigation": "Stage 2 — investigation at first network contact"}
    journal = mask_deep(journal)  # model text and verifier reasons are shown masked
    rows, current, step = [], object(), 0
    for entry in journal:
        stage = entry.get("stage")
        if stage != current:
            current = stage
            label = stage_names.get(stage, "Setup")
            rows.append(f'<tr class="stage"><td colspan="5">{_e(label)}</td></tr>')
        if entry.get("type") == "message":
            rows.append(f'<tr><td></td><td colspan="4"><b>Model answer</b> {_badge(entry.get("model"))} '
                        f'<span class="small">unverified model text</span>'
                        f'<div class="quote">{_e(mask_forbidden(entry.get("content")))}</div></td></tr>')
            continue
        if entry.get("type") == "error":
            rows.append(f'<tr><td></td><td colspan="4" class="err">Tool error on {_e(entry.get("tool"))}: '
                        f'{_e(entry.get("error"))}</td></tr>')
            continue
        step += 1
        reason = entry.get("reason")
        rows.append(
            f"<tr><td>{step}</td>"
            f'<td class="reason">{_e(mask_forbidden(reason)) if reason else "<span class=small>—</span>"}</td>'
            f"<td><code>{_e(entry.get('tool'))}</code></td>"
            f'<td class="hide-sm">{_badge(entry.get("model"), entry.get("backend"))}</td>'
            f"<td>{_summary(entry)}</td></tr>")

    decision = pv["pre_departure"]["decision"]
    deviations = [c for c in pv["claims"] if c["kind"] == "deviation"]
    counts = {}
    for claim in deviations:
        counts[claim["status"]] = counts.get(claim["status"], 0) + 1
    tool_entries = [e for e in journal if e.get("type") == "tool"]
    asked = sum(1 for e in tool_entries if e.get("tool") == "ask_handler")
    fixed = _rejected_then_fixed(tool_entries)
    offline = any(e.get("backend") == "offline" for e in journal if e.get("type") == "tool")
    offline_note = ('<p class="small"><b>Offline run:</b> tool results come from the dossier\'s '
                    'ground-truth files, not from the Meta models. Plumbing check only.</p>'
                    if offline else "")
    banner = ('<div class="banner">SYNTHETIC — fictitious dossier generated for testing. '
              'Not a real shipment.</div>') if pv.get("synthetic") else ""

    claim_rows = []
    for claim in pv["claims"]:
        interval = ""
        if claim.get("interval"):
            interval = f"{claim['interval']['start'][11:16]}–{claim['interval']['end'][11:16]}"
        basis = "".join(f"<div class='small'>{_e(b)}</div>" for b in claim.get("basis", []))
        claim_rows.append(f"<tr><td>{_e(claim['rule'])}</td><td>{_e(interval)}</td>"
                          f"<td>{_e(STATUS_LABEL.get(claim['status'], claim['status']))}</td>"
                          f"<td>{_e(claim['statement'])}{basis}</td></tr>")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Investigation journal — {_e(pv['dossier_id'])}</title>
<style>{CSS}</style></head>
<body><div class="wrap">
{banner}
<h1>Investigation journal — {_e(pv['dossier_id'])}</h1>
<p class="sub">Air waybill {_e(pv.get('awb_number') or 'not read')} · {_e(pv.get('route'))} ·
every step chosen by the agent, every claim checked by a non-AI verifier.</p>
{offline_note}
<div class="cards">
 <div class="card"><b>Pre-departure</b><span class="{_e(decision)}">{_e(decision.upper())}</span></div>
 <div class="card"><b>Deviations recorded</b><span>{len(deviations)}</span></div>
 <div class="card"><b>Ground handler asked</b><span>{asked}</span></div>
 <div class="card"><b>Claims rejected, then fixed</b><span>{fixed}</span></div>
</div>
<h2>Steps</h2>
<p class="small">Hypotheses are the model's own words, shown as stated and not verified;
only the claims of the record below are checked by the verifier.</p>
<table><thead><tr><th>#</th><th>Hypothesis</th><th>Tool</th><th class="hide-sm">Model</th>
<th>What came back</th></tr></thead><tbody>
{''.join(rows)}
</tbody></table>
<h2>Shared handover record</h2>
<table><thead><tr><th>Rule</th><th>Interval UTC</th><th>Status</th><th>Statement and basis</th></tr></thead>
<tbody>{''.join(claim_rows) or '<tr><td colspan="4">No claim.</td></tr>'}</tbody></table>
<p class="small">Not valid until signed by the shipper, the carrier and the ground handler.
Integrity: see manifest.json in this folder.</p>
</div></body></html>
"""
