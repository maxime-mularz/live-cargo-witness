from lcw.vocab import find_forbidden


def test_detects_whole_words_only():
    assert find_forbidden("The animal looked sick") == ["sick"]
    assert find_forbidden("Une boiterie a été signalée") == ["boiterie"]
    assert find_forbidden("The crates will be loaded; skill and vetting are fine") == []


def test_inflected_forms():
    assert find_forbidden("Two deaths were recorded") == ["death"]
    assert "mort" in find_forbidden("des bêtes mortes")
    assert "blessure" in find_forbidden("blessures constatées")
    assert find_forbidden("The temperature exceeded the declared range") == []


def test_french_equivalents_of_every_english_stem():
    # One French phrase per English concept the list forbids: the list must catch it in French too.
    french = {
        "une plaie sur l'animal": "wound",
        "les plaies visibles": "wound",
        "l'animal pourrait mourir": "die",
        "un veau meurt pendant le vol": "die",
        "deux bêtes meurent": "die",
        "un animal mourant": "die",
        "un signe de détresse": "distress",
        "un animal fiévreux": "fever",
        "appeler le véto": "veterinary",
        "une infection": "infection",
        "l'euthanasie": "euthanasia",
        "une maladie": "disease",
    }
    for phrase, concept in french.items():
        assert find_forbidden(phrase), f"{phrase!r} ({concept}) is not caught"


def test_french_record_words_are_not_forbidden():
    assert find_forbidden("Écart expliqué, règle dépassée ; faux positif écarté ; indéterminé. "
                          "Expéditeur, transporteur, agent d'escale. La version anglaise fait foi.") == []


def test_the_english_word_veto_is_not_forbidden():
    # Review of 2026-10-29: the French stem "véto" also caught the English "veto".
    from lcw.vocab import find_forbidden

    assert find_forbidden("The carrier's veto on loading was recorded at 06:10 UTC.") == []
    assert find_forbidden("appeler le véto") != []
