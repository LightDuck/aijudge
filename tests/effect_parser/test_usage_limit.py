def test_each_of_following_effects_scopes_to_both_trailing_clauses():
    """Tearlaments Rulkallos: 'each of the following effects' (plural) is
    an independently-budgeted positional-plural reference -- scopes to
    every clause after it, not the Continuous clause before it."""
    from aijudge.effect_parser.usage_limit import resolve_usage_limit_scopes

    sentences = [
        "Other Aqua monsters you control cannot be destroyed by battle.",
        'You can only use each of the following effects of "Tearlaments Rulkallos" once per turn.',
        "When your opponent activates a card...(Quick Effect): You can negate the activation.",
        "If this Fusion Summoned card is sent to the GY by a card effect: You can Special Summon this card.",
    ]

    clauses, scopes = resolve_usage_limit_scopes(sentences)

    assert clauses == [sentences[0], sentences[2], sentences[3]]
    assert len(scopes) == 1
    assert scopes[0].applies_to == [1, 2]
    assert scopes[0].ambiguous is False


def test_positional_singular_following_scopes_to_one_clause():
    from aijudge.effect_parser.usage_limit import resolve_usage_limit_scopes

    sentences = [
        "Clause A.",
        "You can only use the following effect of \"Card\" once per turn.",
        "Clause B.",
        "Clause C.",
    ]

    clauses, scopes = resolve_usage_limit_scopes(sentences)

    assert clauses == ["Clause A.", "Clause B.", "Clause C."]
    assert scopes[0].applies_to == [1]  # just "Clause B.", not "Clause C." too


def test_positional_plural_preceding_scopes_to_all_prior_clauses():
    from aijudge.effect_parser.usage_limit import resolve_usage_limit_scopes

    sentences = [
        "Clause A.",
        "Clause B.",
        "You can only use the preceding effects of \"Card\" once per turn.",
        "Clause C.",
    ]

    clauses, scopes = resolve_usage_limit_scopes(sentences)

    assert clauses == ["Clause A.", "Clause B.", "Clause C."]
    assert scopes[0].applies_to == [0, 1]


def test_positional_singular_preceding_scopes_to_immediately_prior_clause():
    from aijudge.effect_parser.usage_limit import resolve_usage_limit_scopes

    sentences = [
        "Clause A.",
        "Clause B.",
        "You can only use the preceding effect of \"Card\" once per turn.",
    ]

    clauses, scopes = resolve_usage_limit_scopes(sentences)

    assert scopes[0].applies_to == [1]


def test_self_scoped_default_attaches_to_immediately_preceding_clause():
    from aijudge.effect_parser.usage_limit import resolve_usage_limit_scopes

    sentences = [
        "Clause A.",
        'You can only use this effect of "Card" once per turn.',
        "Clause B.",
    ]

    clauses, scopes = resolve_usage_limit_scopes(sentences)

    assert clauses == ["Clause A.", "Clause B."]
    assert scopes[0].applies_to == [0]


def test_bare_these_effects_is_ambiguous():
    from aijudge.effect_parser.usage_limit import resolve_usage_limit_scopes

    sentences = [
        "Clause A.",
        "Clause B.",
        'You can only use 1 of these effects of "Card" per turn.',
    ]

    clauses, scopes = resolve_usage_limit_scopes(sentences)

    assert scopes[0].ambiguous is True
    assert scopes[0].applies_to == []


def test_group_select_with_positional_pointer_is_not_ambiguous():
    """'1 of following effect' (singular) collapses to exactly the one
    adjacent clause -- not the bare-'these effects' ambiguous case."""
    from aijudge.effect_parser.usage_limit import resolve_usage_limit_scopes

    sentences = [
        "Clause A.",
        "You can only use 1 of following effect of \"Card\" per turn, and only once that turn.",
        "Clause B.",
    ]

    clauses, scopes = resolve_usage_limit_scopes(sentences)

    assert scopes[0].ambiguous is False
    assert scopes[0].applies_to == [1]


def test_named_card_restriction_without_effect_word_scopes_to_all_clauses():
    from aijudge.effect_parser.usage_limit import resolve_usage_limit_scopes

    sentences = [
        "Clause A.",
        'You can only activate 1 "Card Name" per turn.',
        "Clause B.",
    ]

    clauses, scopes = resolve_usage_limit_scopes(sentences)

    assert clauses == ["Clause A.", "Clause B."]
    assert scopes[0].applies_to == [0, 1]
    assert scopes[0].ambiguous is False


def test_named_card_restriction_without_effect_word_fans_out_to_every_other_clause():
    """A bare named-card restriction (no 'effect' word) restricts the whole
    card, not one clause by position -- it should scope to every other
    clause in a realistic multi-clause card, not just the adjacent one."""
    from aijudge.effect_parser.usage_limit import resolve_usage_limit_scopes

    sentences = [
        "If this card is Normal or Special Summoned: You can target 1 card on the field; destroy it.",
        'You can only activate 1 "Card Name" per turn.',
        "During your Main Phase: You can banish this card from your GY to add 1 card to your hand.",
        "If this card is destroyed by battle: You can Special Summon it during your next Standby Phase.",
    ]

    clauses, scopes = resolve_usage_limit_scopes(sentences)

    assert clauses == [sentences[0], sentences[2], sentences[3]]
    assert len(scopes) == 1
    assert scopes[0].applies_to == [0, 1, 2]
    assert scopes[0].ambiguous is False


def test_sentence_without_usage_limit_phrase_is_untouched():
    from aijudge.effect_parser.usage_limit import resolve_usage_limit_scopes

    sentences = ["Clause A.", "Clause B."]

    clauses, scopes = resolve_usage_limit_scopes(sentences)

    assert clauses == sentences
    assert scopes == []


def test_extract_verb_width():
    from aijudge.effect_parser.usage_limit import extract_verb_width

    assert extract_verb_width('You can only activate 1 "Card" per turn.') == "narrow"
    assert extract_verb_width('You can only use 1 "Card" per turn.') == "broad"
    assert extract_verb_width("Clause with no restriction.") is None


def test_resolve_ambiguous_scope_parses_comma_separated_indices():
    from aijudge.effect_parser.usage_limit import resolve_ambiguous_scope
    from aijudge.llm.client import MockLLMClient

    llm_client = MockLLMClient()
    llm_client.queue_response("1,2")

    result = resolve_ambiguous_scope(
        llm_client,
        usage_limit_text='You can only use 1 of these effects of "Card" per turn.',
        clauses=["Effect A.", "Effect B.", "Effect C."],
    )

    assert result == [0, 1]


def test_resolve_ambiguous_scope_all_means_every_clause():
    from aijudge.effect_parser.usage_limit import resolve_ambiguous_scope
    from aijudge.llm.client import MockLLMClient

    llm_client = MockLLMClient()
    llm_client.queue_response("all")

    result = resolve_ambiguous_scope(
        llm_client,
        usage_limit_text='You can only use 1 of these effects of "Card" per turn.',
        clauses=["Effect A.", "Effect B."],
    )

    assert result == [0, 1]
