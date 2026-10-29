"""Cross-file consistency: names that must stay identical across modules, prompts and docs.

When one of these tests fails, a file was changed without its counterparts (see the
lcw-consistency skill for the map of what goes with what).
"""
import re
from pathlib import Path

from conftest import dossier_dirs
from lcw import NEW_DIR, STATUSES, casefile, journal_page, prompts, verifier
from lcw.agent import STAGE_TOOLS
from lcw.dossier import load_json
from lcw.rules import load_rules
from lcw.tools import CLAIM_ITEM, EVIDENCE_ITEM, MODEL_FOR_TOOL, TOOL_SCHEMAS, Toolset

REPO = NEW_DIR.parent
CLAUDE_MD = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
FORMAT_MD = (NEW_DIR / "bench" / "FORMAT.md").read_text(encoding="utf-8")
VERIFIER_SRC = Path(verifier.__file__).read_text(encoding="utf-8")


def test_tool_names_agree_everywhere():
    schema_names = {t["name"] for t in TOOL_SCHEMAS}
    assert schema_names == set().union(*STAGE_TOOLS.values())
    assert schema_names <= set(MODEL_FOR_TOOL)
    for name in schema_names:
        assert callable(getattr(Toolset, name, None)), f"Toolset has no method {name}"
        assert f"`{name}`" in CLAUDE_MD, f"tool {name} missing from the CLAUDE.md table"
    for stage, names in STAGE_TOOLS.items():
        prompt = prompts.PRE_DEPARTURE if stage == "pre_departure" else prompts.INVESTIGATION
        for name in names - {"lookup_rule", "draft_notification"}:
            assert name in prompt, f"{name} not explained in the {stage} prompt"


def test_every_tool_takes_a_reason():
    for tool in TOOL_SCHEMAS:
        assert "reason" in tool["parameters"]["properties"], tool["name"]


def test_statuses_agree_everywhere():
    claim_statuses = set(CLAIM_ITEM["properties"]["status"]["enum"])
    assert set(STATUSES) <= claim_statuses
    assert claim_statuses - set(STATUSES) == {"violated", "satisfied"}
    assert set(casefile.STATUS_LABEL) == set(STATUSES)
    assert set(casefile.STATUS_LABEL_FR) == set(STATUSES)
    assert claim_statuses <= set(journal_page.STATUS_LABEL)
    for status in STATUSES:
        assert status in FORMAT_MD, f"status {status} not documented in FORMAT.md"


def test_evidence_types_agree_everywhere():
    schema_types = set(EVIDENCE_ITEM["properties"]["type"]["enum"])
    verifier_types = set(re.findall(r'kind == "([a-z_]+)"', VERIFIER_SRC)) & schema_types
    assert verifier_types == schema_types, "verifier._resolve must handle every evidence type"
    for kind in schema_types:
        assert kind in prompts.COMMON, f"evidence type {kind} not explained to the model"
        assert kind in verifier.__doc__, f"evidence type {kind} not documented in the verifier"
    assert set(EVIDENCE_ITEM["properties"]["series"]["enum"]) == set(verifier.SERIES)


def test_rule_cards_match_the_code():
    rules = load_rules()
    pre_types = {"field_contains", "field_true", "fields_equal", "crate_feature_present",
                 "crate_arrows_up", "crate_awb_matches"}
    curve_types = {"series_within_range", "series_below"}
    for rule in rules.values():
        kind = rule.check["type"]
        assert kind in (pre_types if rule.phase == "pre_departure" else curve_types), rule.id
        if rule.threshold:
            assert rule.threshold["path"].startswith(verifier.DOSSIER_PREFIXES), rule.id
        if rule.phase == "investigation":
            assert rule.check["series"] in verifier.SERIES, rule.id
    assert "R01–R06" in prompts.PRE_DEPARTURE and "R07–R10" in prompts.INVESTIGATION


def test_statement_checks_are_told_to_the_model():
    # Each phrase answers a verifier rejection seen in live runs (night run 2026-10-27).
    for phrase in ("HH:MM UTC",                    # "time ... is not in the evidence"
                   "never paste a full timestamp",  # ISO timestamps split into stray numbers
                   "never as words",                # "spelled-out number ..."
                   "air waybill number"):           # "air waybill number ... is not in the evidence"
        assert phrase in " ".join(prompts.COMMON.split()), f"verifier check not explained to the model: {phrase}"


def test_unreadable_readings_are_explained_to_the_model():
    # Live DEMO-02 (night run 2026-10-27): an empty loading list led to 4 rejected "violated" claims.
    text = " ".join(prompts.PRE_DEPARTURE.split())
    assert "call read_document once more" in text  # an all-null reading is often a one-off
    assert "never claim \"violated\" for a rule you could not check" in text  # verifier: 'unreadable'


def test_format_md_documents_every_dossier_field():
    record = load_json(dossier_dirs()[0] / "dossier.json")
    for key, value in record.items():
        assert f"`{key}" in FORMAT_MD, f"dossier.json key {key} missing from FORMAT.md"
        if isinstance(value, dict) and key in ("declared", "sensor"):
            for sub in value:
                assert f"`{key}.{sub}`" in FORMAT_MD, f"{key}.{sub} missing from FORMAT.md"
    for folder in dossier_dirs():
        for document in ("awb", "certification", "loading_list"):
            truth = load_json(folder / "documents" / f"{document}.truth.json")
            for field in truth["fields"]:
                assert f"`{field}`" in FORMAT_MD, f"{document}.{field} missing from FORMAT.md"


def test_claude_md_lists_every_module_and_script():
    for module in sorted((NEW_DIR / "lcw").glob("*.py")):
        if module.name == "__init__.py":
            continue
        assert f"lcw/{module.name}" in CLAUDE_MD, f"lcw/{module.name} missing from CLAUDE.md"
    for script in sorted((NEW_DIR / "scripts").glob("*.py")):
        if script.name.startswith("_"):
            continue
        assert script.name in CLAUDE_MD, f"{script.name} missing from CLAUDE.md commands"
