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
  bench/demo/     the 3 filmed scenarios (DEMO-01 block, DEMO-02 stopover, DEMO-03 false positive)
  bench/FORMAT.md complete dossier format (write real or test dossiers from it)
  bench/reserved/ 5 independent dossiers, encrypted until the freeze (see rule 9)
  scripts/        CLI entry points
  notes/          session reports (night runs), development scores only
  tests/          pytest suite, offline
```

## What is built and what is left

Built offline (no network needed, fully tested):
- `lcw/synth.py` — dossier generator (EF-18): synthetic curves, fake documents, crate images,
  voice-note transcripts, scripted handler answers, `expected.json`.
- `lcw/dossier.py` — dossier loader and UTC time helpers; refuses to open `expected.json`.
- `lcw/rules.py` — rule cards loader.
- `lcw/predeparture.py` — deterministic evaluation of R01–R06 on what the models read.
- `lcw/tools.py` — the agent's tools, their JSON schemas, offline stand-ins, journal logging.
- `lcw/vocab.py` — forbidden (veterinary) vocabulary, matched by stems.
- `lcw/schema.py` — the fields read on each document, with their types (single source).
- `lcw/jsonutil.py` — extracting the JSON object a model was asked for from its answer.
- `lcw/env.py` — minimal `.env` loader (keys never printed).
- `lcw/phases.py` — flight phase segmentation from declared hours (EF-08, fallback mode).
- `lcw/deviations.py` — deterministic deviation detection on a curve (EF-09).
- `lcw/verifier.py` — non-AI verifier (EF-14).
- `lcw/casefile.py`, `lcw/hashing.py` — shared handover record (PV) + SHA-256 manifest (EF-15/16).
- `lcw/journal_page.py` — self-contained investigation journal page, written in every case (EF-13).
- `lcw/agent.py`, `lcw/prompts.py` — the two-stage loop (pre-departure, investigation) and its prompts.
- `lcw/runner.py` — runs the agent on a dossier or a bench, writes results, cases and raw runs.
- `lcw/score.py` — bench scoring against `expected.json`.

Written from the providers' docs, tested offline with a fake transport, NOT yet run live:
- `lcw/models.py` — adapters for Muse Spark Open (Baseten, OpenAI-compatible Chat Completions),
  SAM 3.1 (Meta Model API `/v1/responses`, streamed special-token boxes), Muse Voice Transcribe
  (`/v1/asr/transcribe`, 16 kHz mono WAV), Muse Spark (Meta Model API). Configuration in the module
  docstring and `.env.example`. On Baseten the model id is `meta-models/muse-spark-open` (the
  only Meta id `/v1/models` lists; `meta-models/muse-spark-open-1026` answers 404).

Left for the machine that holds the API keys (with Claude Code or Muse Code):
- Validate the adapters with `python new/scripts/test_ca02.py`; fix any request format against the
  provider's docs — do not guess. If CA-02 fails, set `LCW_ORCHESTRATOR=spark`.
- Then: `python new/scripts/run_agent.py new/bench/dev/DEV-02` (scenario 2), then the whole bench.
- Prompt tuning happens in `lcw/prompts.py`, on `bench/dev` only.

## Agent tools (contract)

| Tool | Backed by | Offline stand-in |
| --- | --- | --- |
| `read_document` | Muse Spark Open (vision) | `documents/*.truth.json` |
| `segment_crate` | SAM 3.1 (finds) + Muse Spark Open (reads the crops) | `photos/*.truth.json` |
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
python new/scripts/test_ca02.py                     # CA-02: tool calling + document reading (live)
python new/scripts/run_agent.py new/bench/dev/DEV-02            # one dossier, live (keys in .env)
python new/scripts/run_bench.py new/bench/dev                   # whole bench, live, then scored
python new/scripts/run_bench.py new/bench/dev --dry-run         # plumbing check, no model
python new/scripts/score_bench.py new/bench/dev <out>/results   # re-score existing results
python new/scripts/seal_bench.py <folder> [--check <seal_file>] # seal of a bench folder
python new/scripts/recording_list.py DEV-02 DEV-07  # sentences to record (voice/audio/<id>.m4a)
python new/scripts/generate_bench.py [--demo]       # regenerate bench/dev (or bench/demo), deterministic
python new/scripts/check_ca06.py                    # CA-06: 5 unsourced claims injected, 5 rejected
python new/scripts/verify_case.py <case_dir>        # recompute the PV hashes
python new/scripts/unseal_bench.py                  # AFTER the freeze only: decrypt + check the seal
python new/scripts/check_release.py                 # before every push: lint, tests, secrets, names, seal
python new/scripts/check_release.py --fast --outputs <out>      # CA-13 on a run's outputs
```

`--dry-run` uses a scripted client that reads `expected.json`: it checks the plumbing and proves
nothing about the agent. Never publish a dry-run score.

## Quality and consistency (skills in `.claude/skills/`)

- `lcw-code-quality` — the definition of done for any code change: test first, `ruff check new`,
  `pytest`, an independent review for `verifier.py`, `agent.py`, `tools.py`, `casefile.py`.
- `lcw-consistency` — the map of what must change together (tools, statuses, evidence types, rule
  cards, prompts, FORMAT.md, this file, README). `new/tests/test_consistency.py` enforces most of it.
- `lcw-night-run` — unattended live session on the keyed machine: run demo and dev benches, fix,
  re-run, write `new/notes/night-<date>.md`. Budget cap and forbidden actions are in the skill.
- `.claude/settings.json` — project permissions: `.env` unreadable, no unseal, no force push,
  `expected.json` and the reserved bench not editable.
- `lcw-release-check` — before every push: `python new/scripts/check_release.py`. Private names
  (real shippers, carriers, handlers) are listed in the git-ignored `.private-names`, one per line;
  create it on each machine, never commit it.

Lint config lives in `pyproject.toml` (ruff, line length 120). Never silence a rule to make a check pass.

## Priorities if time runs short (cut in this order)

1. French version of the PV  2. `draft_notification`  3. rules R09–R10  4. rule R06.
Scenario 3 (false positive dismissed) is never cut.
