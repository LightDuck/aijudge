from aijudge.llm.client import MockLLMClient


def test_resolve_effect_clauses_single_effect_skips_confidence_check():
    from aijudge.effect_parser.clause_splitter import resolve_effect_clauses

    llm_client = MockLLMClient()  # no queued response -- must not be called

    clauses, scopes = resolve_effect_clauses(llm_client, "Must be Fusion Summoned and cannot be Special Summoned by other ways.")

    assert clauses == ["Must be Fusion Summoned and cannot be Special Summoned by other ways."]
    assert scopes == []


def test_resolve_effect_clauses_multi_effect_with_usage_limit_scope():
    """Tearlaments Rulkallos remainder (post-material-extraction)."""
    from aijudge.effect_parser.clause_splitter import resolve_effect_clauses

    card_text = (
        'Other Aqua monsters you control cannot be destroyed by battle. You can only use '
        'each of the following effects of "Tearlaments Rulkallos" once per turn. When your '
        'opponent activates a card or effect that includes an effect that Special Summons a '
        'monster(s) (Quick Effect): You can negate the activation, and if you do, destroy '
        'it, then, send 1 "Tearlaments" card from your hand or face-up field to the GY. If '
        'this Fusion Summoned card is sent to the GY by a card effect: You can Special '
        'Summon this card.'
    )
    llm_client = MockLLMClient()
    llm_client.queue_response("0.95")  # score_split_confidence

    clauses, scopes = resolve_effect_clauses(llm_client, card_text)

    assert len(clauses) == 3
    assert clauses[0].startswith("Other Aqua monsters")
    assert clauses[1].startswith("When your opponent activates")
    assert clauses[2].startswith("If this Fusion Summoned card")
    assert len(scopes) == 1
    assert scopes[0].applies_to == [1, 2]


def test_resolve_effect_clauses_falls_back_below_threshold():
    from aijudge.effect_parser.clause_splitter import resolve_effect_clauses

    card_text = "Clause A. Clause B."
    llm_client = MockLLMClient()
    llm_client.queue_response("0.1")  # below DEFAULT_CONFIDENCE_THRESHOLD

    clauses, scopes = resolve_effect_clauses(llm_client, card_text)

    assert clauses == [card_text]
    assert scopes == []


def test_resolve_effect_clauses_empty_text_returns_nothing():
    from aijudge.effect_parser.clause_splitter import resolve_effect_clauses

    llm_client = MockLLMClient()

    clauses, scopes = resolve_effect_clauses(llm_client, "")

    assert clauses == []
    assert scopes == []
