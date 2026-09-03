from aijudge.orchestration.preflight import extract_mode_marker, find_mentioned_card_names


def test_finds_exact_card_name_mention():
    names = find_mentioned_card_names("Can I activate Effect Veiler here?", ["Effect Veiler", "Solemn Strike"])
    assert names == ["Effect Veiler"]


def test_finds_fuzzy_misspelled_card_name_mention():
    names = find_mentioned_card_names("Can I activate Effect Viler here?", ["Effect Veiler"])
    assert names == ["Effect Veiler"]


def test_no_match_returns_empty_list():
    names = find_mentioned_card_names("Can I attack with my dragon?", ["Effect Veiler", "Solemn Strike"])
    assert names == []


def test_short_name_does_not_false_positive_match_inside_a_longer_word():
    names = find_mentioned_card_names("I control a Gravekeeper's Spy", ["Grave"])
    assert names == []


def test_finds_multiple_mentioned_cards_in_the_order_of_known_names():
    question = "If I chain Effect Veiler to Solemn Strike, what happens?"
    names = find_mentioned_card_names(question, ["Effect Veiler", "Solemn Strike", "Called by the Grave"])
    assert names == ["Effect Veiler", "Solemn Strike"]


def test_extract_mode_marker_detects_card_marker_and_strips_it():
    text, mode = extract_mode_marker("{card} what does Ash Blossom do?")
    assert text == "what does Ash Blossom do?"
    assert mode is True


def test_extract_mode_marker_detects_ruling_marker_and_strips_it():
    text, mode = extract_mode_marker("{ruling} what does Ash Blossom do?")
    assert text == "what does Ash Blossom do?"
    assert mode is False


def test_extract_mode_marker_works_anywhere_in_the_text_not_just_prefix():
    text, mode = extract_mode_marker("what does Ash Blossom do? {ruling}")
    assert text == "what does Ash Blossom do?"
    assert mode is False


def test_extract_mode_marker_is_case_sensitive():
    text, mode = extract_mode_marker("{Card} what does Ash Blossom do?")
    assert text == "{Card} what does Ash Blossom do?"
    assert mode is None


def test_extract_mode_marker_returns_none_when_no_marker_present():
    text, mode = extract_mode_marker("what does Ash Blossom do?")
    assert text == "what does Ash Blossom do?"
    assert mode is None


def test_extract_mode_marker_prefers_card_when_both_markers_present():
    text, mode = extract_mode_marker("{ruling} {card} what does Ash Blossom do?")
    assert text == "{ruling} what does Ash Blossom do?"
    assert mode is True
