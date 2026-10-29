"""French version of the shared handover record (pv.fr.md), rendered deterministically."""
import re

from conftest import dossier_dirs
from helpers import scripted_run
from lcw.casefile import STATUS_LABEL_FR, _basis_fr, render_markdown_fr, verify_case, write_case
from lcw.dossier import load_json
from lcw.vocab import find_forbidden

# The only digits the French template itself writes: the hash algorithm's name (SHA-256),
# also written by the English record.
TEMPLATE_NUMBERS = {"256"}
IATA_FORBIDDEN_FR = re.compile(r"(?i)certifi[ée]|approuv[ée]|sp[ée]cialiste|agr[ée][ée]")


def folder_of(category):
    return next(f for f in dossier_dirs() if load_json(f / "expected.json")["category"] == category)


def build(tmp_path, category="explained_by_handler"):
    tools, pre, claims, _ = scripted_run(folder_of(category))
    case = tmp_path / "case"
    manifest = write_case(case, tools.dossier, tools.rules, claims, tools.observations, pre, tools.journal)
    return case, manifest, tools


def test_french_record_is_written_and_in_the_manifest(tmp_path):
    case, manifest, _ = build(tmp_path)
    assert (case / "pv.fr.md").is_file()
    assert "pv.fr.md" in manifest["files"]
    assert verify_case(case) == []
    french = case / "pv.fr.md"
    french.write_text(french.read_text(encoding="utf-8") + "\najout", encoding="utf-8")
    assert verify_case(case) == ["modified: pv.fr.md"]


def test_french_record_is_rendered_from_pv_json_alone(tmp_path):
    case, _, _ = build(tmp_path)
    pv = load_json(case / "pv.json")
    assert (case / "pv.fr.md").read_text(encoding="utf-8") == render_markdown_fr(pv)


def test_every_number_in_the_french_record_comes_from_pv_json(tmp_path):
    for category in ("explained_by_handler", "defect_R03"):
        case, _, _ = build(tmp_path / category, category)
        source = (case / "pv.json").read_text(encoding="utf-8")
        french = (case / "pv.fr.md").read_text(encoding="utf-8")
        for number in set(re.findall(r"\d+", french)) - TEMPLATE_NUMBERS:
            assert number in source, f"{number} in pv.fr.md but not in pv.json ({category})"
        for time in re.findall(r"\d{2}:\d{2}(?= UTC)", french):
            assert time in source
        for rule_id in re.findall(r"\bR\d{2}\b", french):
            assert rule_id in source


def test_french_labels_titles_and_signatures(tmp_path):
    case, _, tools = build(tmp_path)
    pv = load_json(case / "pv.json")
    french = (case / "pv.fr.md").read_text(encoding="utf-8")
    assert french.startswith(f"# Procès-verbal de remise partagé — {pv['dossier_id']}")
    for heading in ("## Contrôles avant départ", "## Écarts constatés à l'investigation",
                    "## Règles citées", "## Signatures"):
        assert heading in french
    for party in ("Expéditeur", "Transporteur", "Agent d'escale"):
        assert f"- {party} : nom" in french
    assert "version anglaise (`pv.md`) fait foi" in french
    deviations = [c for c in pv["claims"] if c["kind"] == "deviation"]
    assert deviations
    for claim in deviations:
        assert STATUS_LABEL_FR[claim["status"]] in french
        start, end = claim["interval"]["start"][11:16], claim["interval"]["end"][11:16]
        assert f"{start}–{end} UTC" in french
        # The verified statement is English model text: shown verbatim, quoted, labelled as such.
        assert f"Énoncé vérifié (anglais) : « {claim['statement']} »" in french
    for cited in pv["rules_cited"]:
        assert tools.rules[cited["id"]].title_fr in french
        assert cited["title_fr"] == tools.rules[cited["id"]].title_fr


def test_french_pre_departure_outcomes(tmp_path):
    case, _, _ = build(tmp_path, "defect_R03")
    french = (case / "pv.fr.md").read_text(encoding="utf-8")
    assert "Décision avant départ : **BLOQUÉ**" in french
    assert "| R03 | non respectée |" in french


def test_french_record_keeps_the_synthetic_banner_and_has_no_forbidden_word(tmp_path):
    case, _, _ = build(tmp_path)
    french = (case / "pv.fr.md").read_text(encoding="utf-8")
    assert "> **SYNTHETIC** — dossier fictif" in french
    assert find_forbidden(french) == []
    assert not IATA_FORBIDDEN_FR.search(french)


def test_french_template_alone_is_clean():
    pv = {"dossier_id": "X", "synthetic": False, "awb_number": None, "route": "A → B → C",
          "created_at": "T", "pre_departure": {"decision": "go", "violated_rules": []}, "claims": [],
          "unresolved_rules": [], "rules_cited": []}
    text = render_markdown_fr(pv)
    assert "SYNTHETIC" not in text
    assert find_forbidden(text) == []
    assert not IATA_FORBIDDEN_FR.search(text)
    assert set(re.findall(r"\d+", text)) <= TEMPLATE_NUMBERS


def test_french_basis_keeps_every_line_of_the_english_basis(tmp_path):
    # Convoy notes, handler answers and inspection reasons are English dossier text: the French
    # basis quotes each of them verbatim and drops none, on every development dossier.
    kinds_seen = set()
    for folder in dossier_dirs():
        tools, pre, claims, _ = scripted_run(folder)
        case = tmp_path / folder.name
        write_case(case, tools.dossier, tools.rules, claims, tools.observations, pre, tools.journal)
        pv = load_json(case / "pv.json")
        french = (case / "pv.fr.md").read_text(encoding="utf-8")
        for claim in pv["claims"]:
            assert len(_basis_fr(claim)) == len(claim["basis"]), (folder.name, claim["id"])
            kinds_seen.update(item["type"] for item in claim["evidence"])
        for quoted in re.findall("“(.*?)”", (case / "pv.md").read_text(encoding="utf-8")):
            assert f"« {quoted} »" in french
    assert {"voice_note", "handler_answer", "inspection_window"} <= kinds_seen


def test_a_basis_line_that_cannot_be_rebuilt_in_french_is_kept_in_english():
    # Review of 2026-10-29: a handler answer id with a space ("H 1") vanished from pv.fr.md.
    from lcw.casefile import _basis_fr

    claim = {"evidence": [{"type": "handler_answer", "id": "H 1"}],
             "basis": ['Ground handler answer H 1: "ok"']}
    lines = _basis_fr(claim)
    assert len(lines) == 1 and 'Ground handler answer H 1: "ok"' in lines[0] and "anglais" in lines[0]
