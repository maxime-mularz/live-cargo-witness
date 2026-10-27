from lcw.vocab import find_forbidden


def test_detects_whole_words_only():
    assert find_forbidden("The animal looked sick") == ["sick"]
    assert find_forbidden("Une boiterie a été signalée") == ["boiterie"]
    assert find_forbidden("The crates will be loaded; skill and vetting are fine") == []
