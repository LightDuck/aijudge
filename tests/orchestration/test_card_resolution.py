from aijudge.orchestration.card_resolution import CardResolution, resolve_named_cards


def test_resolve_named_cards_marks_found_card_as_resolved_and_refetches_raw_row():
    # The raw row must come from get_card_by_id, not lookup_card's own
    # trimmed result -- lookup_card's shape lacks `race`, which
    # build_known_facts_context needs for correct spell-speed
    # classification (see CLAUDE.md's cards.race notes).
    raw_row = {"id": "abc", "name": "Tearlaments Scream", "card_text": "...", "race": None}

    def fake_lookup_card(args, **kwargs):
        return {"found": True, "id": "abc", "name": "Tearlaments Scream"}

    def fake_get_card_by_id(card_id):
        assert card_id == "abc"
        return raw_row

    resolutions = resolve_named_cards(
        ["Tearlaments Scream"],
        llm_client=None,
        lookup_card_fn=fake_lookup_card,
        get_card_by_id_fn=fake_get_card_by_id,
    )

    assert resolutions == [CardResolution(name="Tearlaments Scream", status="resolved", card=raw_row)]


def test_resolve_named_cards_marks_missing_card_as_not_found():
    resolutions = resolve_named_cards(
        ["Nonexistent Card"],
        llm_client=None,
        lookup_card_fn=lambda args, **kwargs: {"found": False},
        get_card_by_id_fn=lambda card_id: None,
    )

    assert resolutions == [CardResolution(name="Nonexistent Card", status="not_found")]


def test_resolve_named_cards_downgrades_to_not_found_when_get_card_by_id_returns_none():
    # Narrow race: lookup_card_fn reports the card found, but by the time
    # get_card_by_id_fn re-fetches the raw row (e.g. the row was deleted in
    # between), it comes back None. Reporting status="resolved" with
    # card=None would later crash build_known_facts_context /
    # build_grounded_result with an unguarded TypeError -- this must
    # downgrade to "not_found" instead, which every caller already handles.
    resolutions = resolve_named_cards(
        ["Vanishing Card"],
        llm_client=None,
        lookup_card_fn=lambda args, **kwargs: {"found": True, "id": "abc", "name": "Vanishing Card"},
        get_card_by_id_fn=lambda card_id: None,
    )

    assert resolutions == [CardResolution(name="Vanishing Card", status="not_found")]


def test_resolve_named_cards_marks_ambiguous_match_as_ambiguous():
    resolutions = resolve_named_cards(
        ["Tearlaments"],
        llm_client=None,
        lookup_card_fn=lambda args, **kwargs: {"found": False, "ambiguous": True},
        get_card_by_id_fn=lambda card_id: None,
    )

    assert resolutions == [CardResolution(name="Tearlaments", status="ambiguous")]


def test_resolve_named_cards_resolves_each_name_independently():
    def fake_lookup_card(args, **kwargs):
        if args["name"] == "Tearlaments Scream":
            return {"found": True, "id": "abc", "name": "Tearlaments Scream"}
        return {"found": False}

    resolutions = resolve_named_cards(
        ["Tearlaments Scream", "Tearlaments Scrimm"],
        llm_client=None,
        lookup_card_fn=fake_lookup_card,
        get_card_by_id_fn=lambda card_id: {"id": "abc", "name": "Tearlaments Scream"},
    )

    assert [r.status for r in resolutions] == ["resolved", "not_found"]


def test_resolve_named_cards_threads_online_ingest_enabled_and_on_ingest_start_to_lookup_card():
    captured = {}

    def fake_lookup_card(args, *, llm_client, online_ingest_enabled, on_ingest_start):
        captured["online_ingest_enabled"] = online_ingest_enabled
        captured["on_ingest_start"] = on_ingest_start
        return {"found": False}

    def on_ingest_start(name):
        return None

    resolve_named_cards(
        ["Some Card"],
        llm_client=None,
        online_ingest_enabled=False,
        on_ingest_start=on_ingest_start,
        lookup_card_fn=fake_lookup_card,
        get_card_by_id_fn=lambda card_id: None,
    )

    assert captured["online_ingest_enabled"] is False
    assert captured["on_ingest_start"] is on_ingest_start
