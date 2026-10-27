---
name: lcw-release-check
description: Pre-push and pre-submission check for Live Cargo Witness — lint, tests, secrets, private names, sealed reserved bench, synthetic labels, IATA wording, no dry-run output. Use before every git push, before tagging, and before the hackathon submission.
---

# Release check — Live Cargo Witness

The repository is public and judged. One leaked key, one real company name or one opened reserved
dossier can disqualify the project or break a client relationship. Run this before every push.

## 1. Set up once per machine

The private-name list never enters the repo. Create `.private-names` at the repository root (it is
git-ignored), one real shipper, carrier, handler or person name per line, `#` for comments. Ask
Maxime for the list if it is missing; do not guess names and do not write them in chat or commits.

## 2. Run the check

```bash
git fetch                                   # someone else may have pushed
python3 new/scripts/check_release.py        # --fast skips ruff and pytest
```

It checks the files git tracks: ruff and tests green; no `.env`, no key-shaped value; no private
name; the reserved archive and seal unchanged since the sealing commit and no plaintext reserved
dossier on disk; synthetic labels on every dev dossier; IATA wording and vocabulary in public
texts; no results or scripted-client output tracked.

A `[FAIL]` blocks the push: fix the cause, never the check. A `[warn]` is reported to Maxime.
Known warning: a private name in an old commit message — rewriting history needs his explicit
approval (force push); do not do it on your own.

## 3. Read what the script cannot judge

- `git diff --staged` — every hunk is intended; no debug print, no commented-out code, no stray file.
- README claims match the code: anything not proven by a test or a live run says "in progress";
  every published score says model, bench (dev or reserved) and date, and comes from a live run.
- New text shown to judges keeps the hard rules: no veterinary vocabulary, "built for live-animal
  shipments subject to the IATA LAR", synthetic data labelled, the agent drafts and never sends.
- Reserved bench: before the freeze (Nov 3, 18h Paris) nothing under `new/bench/reserved*` changes.
  After the freeze, `unseal_bench.py` is run once and its score is published as is.

## 4. Commit and push

- Commit message in English, imperative, ending with the attribution lines the session gives.
- `git push` (never `--force` without Maxime's explicit approval).
- For the submission: also tag the commit (`git tag submission-2026-11-04`) and put the commit hash
  and the root hash of the demo case file in the submission form.
