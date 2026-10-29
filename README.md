# Live Cargo Witness

**The black box for live animals in the cargo hold.**
An investigator agent that checks the paperwork before takeoff, reconstructs the flight after
landing, asks the ground crew when a deviation has no explanation, and produces a handover record
signed by the shipper, the carrier and the ground handler.

Built for the Meta Global AI Developer Hackathon (Oct 27 – Nov 4, 2026), Startups track, by
Marfik Group. Built for live-animal shipments subject to the IATA Live Animals Regulations; not
affiliated with or endorsed by IATA.

> **Status: work in progress (day 2).** The deterministic core, the evaluation benches, the agent
> loop and the journal page are in place and tested offline. The Meta model adapters are being wired next.

## Why

Livestock flies in the dark, with no connection. When something goes wrong between loading and
arrival, nobody can say what happened, and the paperwork is reconstructed hours later, if at all.
Live Cargo Witness does nothing in flight: like an accident investigator reading the flight
recorders, it works at the first network contact, from the sensor log, the convoy attendant's
voice notes and the ground crew's answers.

## How it works

1. **Before departure** — reads the air waybill, the Shipper's Certification and the loading list,
   segments every crate photo, and gives a go or a block, each citing a rule card and its evidence.
2. **In flight** — nothing. The sensor records locally; the attendant may dictate notes.
3. **At first contact** — cuts the sensor log into flight phases, finds deviations from the rule
   cards, matches them with the notes, and decides on its own when to ask the ground handler.
   Each deviation ends up explained, dismissed as a false positive, or **indeterminate** — the
   agent is allowed to say it does not know.
4. **Handover record** — every statement goes through a **non-AI verifier**. It rejects any claim
   without a rule card and a piece of evidence, checks that the cited sensor interval really breaks
   the rule, and checks that the numbers, times, dates and identifiers in the statement come from
   the evidence. Whether a ground handler's answer actually explains a deviation stays the agent's
   judgement: the answer is quoted verbatim in the record, for the three signatories to see.
   Every file of the record is listed with its SHA-256; publishing or signing the root hash makes
   any later change detectable. The record is written in English (`pv.md`, the reference) and in
   French (`pv.fr.md`), the French one rendered from the same data with fixed labels — no model
   translates it, and the verified statements stay in English, quoted.

## Meta models

| Model | Role | Code |
| --- | --- | --- |
| Muse Spark Open (Baseten, open weights) | Orchestrates the tools; reads document images and SAM's crops | `new/lcw/models.py` (`chat`, `read_document_image`), `new/lcw/agent.py` |
| SAM 3.1 (Meta Model API) | Finds the label, the orientation arrows and the air waybill plate on each crate photo | `new/lcw/models.py` (`segment_crate_image`, `sam_boxes`) |
| Muse Voice Transcribe (Meta Model API) | Transcribes the convoy attendant's notes and the ground handler's answers | `new/lcw/models.py` (`transcribe`), `new/lcw/tools.py` |
| Muse Spark (Meta Model API) | Fallback orchestrator if Muse Spark Open fails the tool-calling test (CA-02); record text writer (optional) | `new/lcw/models.py` (`chat` with `LCW_ORCHESTRATOR=spark`, `write_record_text`) |

The investigation journal of every case names the model behind each step, and says "offline
stand-in" when a step was answered from a dossier's ground-truth file instead of a model.

## Built during the hackathon

Everything under [`new/`](new/) was written during the event (see the dated git history).

| Part | File | Status |
| --- | --- | --- |
| 10 rule cards, no hard-coded thresholds, no LAR text | `new/rules/` | done |
| Synthetic dossier generator (documents, crates, sensor curves, notes, answers) | `new/lcw/synth.py` | done |
| Development bench: 20 fictitious dossiers + expected outcomes | `new/bench/dev/` | done |
| Flight phases, deviation detection | `new/lcw/phases.py`, `new/lcw/deviations.py` | done |
| Non-AI verifier | `new/lcw/verifier.py` | done |
| Handover record (English `pv.md`, French `pv.fr.md`) + SHA-256 manifest | `new/lcw/casefile.py` | done |
| Bench scoring | `new/lcw/score.py` | done |
| Two-stage agent loop and prompts | `new/lcw/agent.py`, `new/lcw/prompts.py` | done, tested with a scripted client |
| Investigation journal page | `new/lcw/journal_page.py` | done |
| Meta model adapters (written from the providers' docs, tested offline; live validation pending) | `new/lcw/models.py` | in progress |
| The three filmed scenarios as fictitious dossiers | `new/bench/demo/` | done |
| Acceptance checks: CA-02 tool calling, CA-06 unsourced claims, CA-12 time and cost, CA-13 outputs scan | `new/scripts/test_ca02.py`, `check_ca06.py`, `score.py`, `check_release.py --outputs` | done offline |
| Dossier format specification | `new/bench/FORMAT.md` | done |
| Reserved bench (5 independent dossiers, encrypted until the code freeze) | `new/bench/reserved.*` | sealed, opened after the freeze |
| Quality gates: lint, cross-file consistency tests, pre-push release check | `pyproject.toml`, `new/tests/test_consistency.py`, `new/scripts/check_release.py` | done |

## Evaluation

Two scores will be published side by side:
- the **development bench**: 20 generated dossiers, the ones the agent was tuned on;
- the **reserved bench**: 5 dossiers written by an independent agent instance that was given only
  the [dossier format](new/bench/FORMAT.md) and the rule cards. They are committed encrypted, with a
  seal (SHA-256) published before the code freeze, decrypted once after the freeze, and their
  score is published as is.

Until the agent is wired, the only score here is a plumbing check of the scoring code itself.

All data in this repository is **fictitious and labelled SYNTHETIC**. No real shipment, client,
document or photo is used.

## Run it

```bash
pip install -r requirements.txt
ruff check new
python -m pytest new/tests -q
python new/scripts/check_release.py        # before every push
python new/scripts/generate_bench.py               # bench/dev; add --demo for bench/demo
python new/scripts/check_ca06.py                    # the verifier rejects 5 unsourced claims out of 5
python new/scripts/run_bench.py new/bench/demo --dry-run   # plumbing only, no model
python new/scripts/score_bench.py new/bench/dev new/results/dev
python new/scripts/verify_case.py <case_dir>
```

## License

[Apache License 2.0](LICENSE). Copyright 2026 Marfik Group — see [NOTICE](NOTICE).
