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
