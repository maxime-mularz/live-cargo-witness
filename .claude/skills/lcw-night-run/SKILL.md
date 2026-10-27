---
name: lcw-night-run
description: Unattended night session on the keyed machine — run the live agent on the demo and development benches, find why dossiers fail, fix adapters and prompts, re-run, and leave a morning report. Use when Maxime asks for a night run or an unattended live tuning session.
---

# Night run — Live Cargo Witness

You work alone for several hours on Maxime's machine, with the API keys in `.env`. Nobody will
answer a question: take the most reasonable reading, write it down in the report, carry on.
Load `lcw-code-quality` and `lcw-consistency` before changing code, and `lcw-release-check`
before every push.

## Never (stop and write it in the report instead)

- Read, print or echo `.env` or any key; never run `env`/`printenv`. Scripts print key *names* only.
- Touch, decrypt or run the reserved bench (`new/bench/reserved*`); never ask for `RESERVED_PASSWORD`.
- Edit `expected.json`, rule cards' meaning, or the verifier's strictness to make a score go up.
  If a dossier looks wrong, write why in the report; Maxime decides.
- Send anything (mail, message, post) or publish a score in the README.
- Force-push, rewrite history, delete results of earlier passes.
- Send a dossier that is not marked synthetic to any API.

## Budget and stop conditions

- One dossier costs about 0.10–0.30 USD (orchestration dominates). Hard cap for the night:
  **25 USD** of model spend, estimated from the `usage` block of every `results/*.json` you
  produced (Muse Spark Open 1.25 / 4.25 USD per million input / output tokens; SAM 3.1
  0.0025 USD per call; Muse Spark same as Spark Open). Keep the running total in the report.
- Stop when the cap is near, after 6 hours, after 3 full development passes without progress,
  or when every remaining failure needs a decision from Maxime.

## Steps

1. **Setup.** `git pull`; `source .venv/bin/activate`; `python -m pytest new/tests -q` (must pass);
   `python new/scripts/check_release.py --fast`. Note the start time and commit in the report.
2. **Scenario 2 first.** `python new/scripts/run_agent.py new/bench/demo/DEMO-02 --out new/results/night/demo`.
   Expected: GO at stage 1; deviations R07, R09, R10 at the stopover, all
   `explained_rule_exceeded`; the handler asked once; record written. Read
   `new/results/night/demo/runs/DEMO-02.json` (journal) to understand any failure.
3. **Then DEMO-01** (block R03 + R05) **and DEMO-03** (false positive, no handler call), same `--out`.
   Score the three: `python new/scripts/score_bench.py new/bench/demo new/results/night/demo/results`.
4. **Development bench, pass N:** `python new/scripts/run_bench.py new/bench/dev --out new/results/night/pass-N`.
   Read `score.md`.
5. **Classify every failure** from the run journals, one line each in the report:
   - *reading*: a document field or crate feature read wrong (compare with the dossier's
     `*.truth.json` — allowed for diagnosis, never fed to the agent);
   - *orchestration*: wrong tool order, missing call, wrong status, handler asked when not needed
     or not asked when needed, final answer malformed;
   - *verifier loop*: claims rejected again and again (read the reasons);
   - *infrastructure*: HTTP errors, timeouts, rate limits.
6. **Fix the biggest class first.**
   - Adapters (`lcw/models.py`): only against the provider's documentation (dev.meta.ai,
     docs.baseten.co); a fake-transport test for each fix.
   - Prompts (`lcw/prompts.py`): tune on `bench/dev` and `bench/demo` only; prefer telling the
     model what the verifier checks over adding special cases.
   - Crate reading: SAM concept prompts in `SAM_CONCEPTS`; absence must keep needing two models.
   - Code changes: test first, `ruff check new`, `pytest`, then commit (English message, what
     and why) and `python new/scripts/check_release.py` before `git push`.
7. **Re-run only the failures** (`run_bench.py ... --only DEV-xx DEV-yy --out new/results/night/fix-K`),
   then a full pass when a fix touched prompts or adapters. Keep every pass folder.
8. **Morning report**: write `new/notes/night-YYYY-MM-DD.md` (commit and push it) with
   - start/end time, commits, estimated spend;
   - a table of passes: phase 1 correct, investigations correct, CA-03/04/07/08/09/12 values;
   - DEMO-01/02/03 status, with the path of each journal page;
   - what was fixed and why; what failed and is still open;
   - decisions for Maxime (dossiers that look wrong, rule questions, anything you did not do
     because of the rules above).
   Scores in the report are development scores, labelled as such. Never a dry-run score.
