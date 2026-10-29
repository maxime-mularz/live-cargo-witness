---
name: lcw-consistency
description: Map of what must change together in Live Cargo Witness — tools, claim statuses, evidence types, rule cards, dossier fields, prompts, FORMAT.md, CLAUDE.md, README. Use whenever a change renames, adds or removes any of these, or edits a prompt or a doc.
---

# Consistency map — Live Cargo Witness

The same names live in code, prompts, schemas and docs. A name changed in one place and not the
others gives a model that calls a tool that does not exist, a verifier that rejects valid claims,
or a README that promises what the code does not do. `new/tests/test_consistency.py` enforces
most rows below; when it fails, this table says where to look. When you add a row here, add the
matching assertion there.

## If you change X, update Y

| You change | Also update | Enforced by |
| --- | --- | --- |
| A tool (name, arguments) | `TOOL_SCHEMAS`, `Toolset` method, `MODEL_FOR_TOOL`, `agent.STAGE_TOOLS`, the stage prompt in `prompts.py`, the tools table in `CLAUDE.md`, `journal_page._summary`, `tests/fake_model.py` | `test_tool_names_agree_everywhere`, `test_every_tool_takes_a_reason` |
| A deviation status | `lcw.STATUSES`, `CLAIM_ITEM` enum, `casefile.STATUS_LABEL`, `journal_page.STATUS_LABEL`, verifier `_check_deviation`, `prompts.INVESTIGATION`, `bench/FORMAT.md`, `synth.py`, `score.py` | `test_statuses_agree_everywhere` |
| An evidence type | `EVIDENCE_ITEM` enum, `Verifier._resolve`, the verifier docstring, `prompts.COMMON`, `casefile._basis` | `test_evidence_types_agree_everywhere` |
| A sensor series | `EVIDENCE_ITEM.series`, `verifier.SERIES`, `synth.py` CSV columns, `FORMAT.md` sensor log, rule cards | `test_evidence_types_agree_everywhere`, `test_rule_cards_match_the_code` |
| A rule card (new check type, threshold path) | `predeparture.evaluate_rule` or `deviations.detect`, `verifier.DOSSIER_PREFIXES`, `rules/README.md`, the prompt's rule range (R01–R06 / R07–R10), `synth.py` defects, `FORMAT.md` deviations | `test_rule_cards_match_the_code`, `test_rules.py` |
| A dossier field | `synth.py`, `FORMAT.md` (table), `Toolset.entry_record` if the agent may see it, `dossier.py` loaders | `test_format_md_documents_every_dossier_field` |
| A document or crate field | `synth.py` truth files, `FORMAT.md`, `models.read_document_image` / `segment_crate_image` docstrings, `scripts/test_ca02.py` | `test_format_md_documents_every_dossier_field` |
| A module or a script | `CLAUDE.md` (layout / built list / commands), `README.md` if user-facing | `test_claude_md_lists_every_module_and_script` |
| The result format (`results/<id>.json`) | `agent.run`, `runner.py`, `score.py`, `tests/helpers.scripted_run` | `test_agent.py`, `test_score.py` |
| The record (pv.json / pv.md, drafts/) | `casefile.write_case`, `render_markdown`, `journal_page.render`, `drafts.render_draft`, `verify_case`, `scripts/verify_case.py` | `test_casefile.py`, `test_drafts.py` |
| A metric or acceptance criterion (CA-xx) | `score.py`, `README.md` Evaluation, the CDC in Claude Docs (tell Maxime; do not edit his doc without asking) | `test_score.py` |
| The bench generator | regenerate with `generate_bench.py` (never hand-edit `expected.json`), then run the suite | `test_synth.py` |
| What is built / left | `CLAUDE.md` "What is built and what is left", `README.md` status table | review |

## Rules that are not tests (check them by reading)

- **Prompts match the verifier.** Every check the verifier makes (cite the threshold path, the
  interval inside a cited segment, a note within 10 minutes, default answers never explain, a
  window for a dismissed false positive) is told to the model in `prompts.py`, in the same words
  as the rejection reason where possible. When you tighten the verifier, update the prompt in the
  same commit; when a prompt asks for something, the verifier must accept it.
- **Docs claim only what the code does.** README and CLAUDE.md say "in progress" until a test or a
  live run proves it. Scores in the README come from live runs, never `--dry-run`, and say on
  which bench (dev or reserved) and with which model.
- **One vocabulary.** "Shared handover record" (PV in French docs), "pre-departure check",
  "investigation at first network contact", "deviation detected at investigation" (never
  "in-flight deviation": nothing happens in flight), "ground handler", "convoy attendant".
- **Times.** ISO 8601 UTC with `Z` in data; `HH:MM UTC` in statements; Paris time only in human
  planning notes.
- **Languages.** Code, data, prompts, record: English. The French PV is optional (first cut).

## Procedure

1. Before editing, grep for the name you change across `new/`, `CLAUDE.md`, `README.md`:
   `grep -rn "<name>" new CLAUDE.md README.md --include=*.py --include=*.md --include=*.yaml`
2. Change every place in the table row in the same commit.
3. Run `python3 -m pytest new/tests/test_consistency.py -q`, then the full suite.
4. If you found a coupling the table does not list, add the row and, if possible, the assertion.
