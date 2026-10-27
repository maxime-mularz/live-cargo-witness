from lcw.rules import resolve_threshold


def test_ten_active_cards(rules):
    assert list(rules) == [f"R{i:02d}" for i in range(1, 11)]
    assert all(rule.active for rule in rules.values())
    assert [r for r in rules if rules[r].phase == "pre_departure"] == [f"R0{i}" for i in range(1, 7)]


def test_no_hard_coded_threshold(rules):
    for rule in rules.values():
        if rule.threshold is not None:
            assert rule.threshold["from"] == "dossier"


def test_no_lar_text(rules):
    for rule in rules.values():
        if rule.source["kind"] == "lar_reference":
            assert "no text" in rule.source["lar_section"]


def test_unresolved_threshold_triggers_nothing(rules):
    assert resolve_threshold(rules["R07"], {"declared": {}}) is None
    assert resolve_threshold(rules["R07"], {"declared": {"temperature_range_c": [1, 2]}}) == (
        [1, 2], "declared.temperature_range_c")
