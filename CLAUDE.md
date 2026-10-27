# Live Cargo Witness — rules for coding agents

Live Cargo Witness is a black-box investigator agent for live animal air cargo, built for the
Meta Global AI Developer Hackathon (build window Oct 27 – Nov 4, 2026, submission Nov 4, 9 PM ET).
The full spec (in French) lives outside the repo; this file is the part a coding agent must follow.

## Hard rules (never break them)

1. **New work only, in `new/`.** Everything built during the hackathon lives under `new/`. Judges must
   be able to tell what was built during the event. Do not import code from other Marfik projects.
2. **No client data.** No document, photo, curve, name or number from a real shipper, carrier or
   handler — not in the repo, not in prompts sent to any API.
   Every dossier in `new/bench/` is fictitious and says so.
3. **No secrets in code or chat.** Keys live in `.env` (git-ignored). Read them with `os.environ`.
   `.env.example` lists the variable names only.
4. **No invented values.** Every number the agent writes in a case file must come from a rule card,
   a dossier field or a piece of evidence. The verifier (`lcw/verifier.py`) enforces this; do not
   weaken it to make a demo pass.
5. **No veterinary vocabulary.** The agent reports deviations from rules. It never assesses the
   health or condition of animals. `lcw/vocab.py` holds the forbidden-word list used by tests.
6. **The agent never sends anything.** It drafts; a human signs and sends.
7. **IATA wording.** Say "built for live-animal shipments subject to the IATA LAR". Never "IATA
   specialist", "certified" or "approved", never the IATA logo, never text copied from the LAR.
8. **Synthetic data is labelled.** Synthetic curves carry `synthetic: true` in their metadata and a
   `SYNTHETIC` banner wherever they are displayed.
9. **The reserved bench is sealed.** Five dossiers written by an independent agent instance that only
   had `new/bench/FORMAT.md` and the rule cards — never the generator nor the development bench.
   They are committed **encrypted** (`new/bench/reserved.tar.gz.enc`) with their seal
   (`new/bench/reserved.seal`). Never decrypt, open or tune against them before the code freeze
   (Nov 3, 6 PM Paris). After the freeze: `new/scripts/unseal_bench.py`, run once, publish the
   score as is. Never edit `expected.json` files to make a score go up.

## Layout

```
new/
  lcw/            Python package (tools, verifier, case file, scoring)
  rules/          10 rule cards R01–R10 (YAML)
  bench/dev/      20 generated dossiers + expected.json (do not hand-edit; regenerate)
  bench/FORMAT.md complete dossier format (write real or test dossiers from it)
  bench/reserved/ 5 independent dossiers, encrypted until the freeze (see rule 9)
  scripts/        CLI entry points
  tests/          pytest suite, offline
```

## What is built and what is left

Built offline (no network needed, fully tested):
- `lcw/synth.py` — dossier generator (EF-18): synthetic curves, fake documents, crate images,
  voice-note transcripts, scripted handler answers, `expected.json`.
- `lcw/rules.py` — rule cards loader.
- `lcw/phases.py` — flight phase segmentation from declared hours (EF-08, fallback mode).
- `lcw/deviations.py` — deterministic deviation detection on a curve (EF-09).
- `lcw/verifier.py` — non-AI verifier (EF-14).
- `lcw/casefile.py`, `lcw/hashing.py` — shared handover record (PV) + SHA-256 manifest (EF-15/16).
- `lcw/score.py` — bench scoring against `expected.json`.

Left for the machine that holds the API keys (with Claude Code or Muse Code):
- `lcw/models.py` — adapters for Muse Spark Open (Baseten), SAM 3.1, Muse Voice Transcribe,
  Muse Spark (Meta Model API). The function signatures are fixed; the bodies raise
  `NotImplementedError` until wired. Check each provider's docs for the request format — do not guess.
  On Baseten the hackathon model id is `meta-models/muse-spark-open-1026`.
- `lcw/agent.py` — the investigation loop (orchestrated by Muse Spark Open, tools below).
- The journal web page (EF-13).

## Agent tools (contract)

| Tool | Backed by | Offline stand-in |
| --- | --- | --- |
| `read_document` | Muse Spark Open (vision) | `documents/*.truth.json` |
| `segment_crate` | SAM 3.1 | `photos/*.truth.json` |
| `get_sensor_curve` | Tive API or CSV export | `sensor/curve.csv` |
| `lookup_rule` | `lcw.rules` | same |
| `ask_handler` | recorded answer + Voice Transcribe | `voice/handler_answers.json` |
| `draft_notification` (optional) | template | same |
| `write_case_file` | `lcw.casefile` after `lcw.verifier` | same |

The offline stand-ins exist for tests and scoring plumbing only. The demo and the submitted scores
must come from the real models; say so in the README.

## Commands

```bash
pip install -r requirements.txt
python -m pytest new/tests -q                       # full offline suite
python new/scripts/generate_bench.py                # regenerate bench/dev (deterministic seeds)
python new/scripts/score_bench.py new/bench/dev new/results/dev
python new/scripts/verify_case.py <case_dir>        # recompute the PV hashes
python new/scripts/unseal_bench.py                 # AFTER the freeze only: decrypt + check the seal
```

## Priorities if time runs short (cut in this order)

1. French version of the PV  2. `draft_notification`  3. rules R09–R10  4. rule R06.
Scenario 3 (false positive dismissed) is never cut.
