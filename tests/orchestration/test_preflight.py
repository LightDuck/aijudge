from aijudge.orchestration.preflight import find_mentioned_card_names


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


# --- Bullet category line in KNOWN FACTS -------------------------------------
# Real cards (text, type, race and passcode as YGOPRODeck has them) with the
# card_bulleted rows their review produced, shaped as get_card_bulleted returns
# them. The confirmed effect is whatever this project's own parser makes of the
# text, so no effect data is invented for these tests.

_B1 = {
    "code": "B1",
    "name": "Player choice · activation",
    "description": 'Always choose strictly 1 bullet, at activation ("activate 1 of these effects").',
    "category_note": None,
}
_D1 = {
    "code": "D1",
    "name": "Mandatory grant",
    "description": (
        "1 or more bullets, granted as a single indivisible bundle: one binary condition on the card either "
        "grants all of them or none of them. There is no branch and no scale — the bundle is never split "
        "into a subset."
    ),
    "category_note": (
        "Contrast with C: a card whose criteria select a subset of bullets, or move between them as some "
        "value changes, belongs in C, not here, even if the bullets are grant-phrased."
    ),
}

_VARIABLE_FORM = {
    "id": "5c1d3a52-6a7e-4d0f-9a44-0b8f3e2c1a01",
    "name": "Variable Form",
    "card_type": "Trap Card",
    "race": "Continuous",
    "ygoprodeck_id": "64038662",
    "card_text": (
        "Once per turn, you can activate 1 of these effects.\n"
        '● Target 2 face-up "Inzektor" monsters you control; equip one to the other.\n'
        '● Target 1 "Inzektor" monster you control that is an Equip Card; Special Summon that target in '
        "face-up Defense Position."
    ),
}
_VARIABLE_FORM_BULLETED = {
    "ygoprodeck_id": "64038662",
    **_B1,
    "reason": 'activate exactly 1 bullet (activation): "activate 1 of these"',
    "note": None,
}

_ORICHALCOS_SWORD_OF_SEALING = {
    "id": "5c1d3a52-6a7e-4d0f-9a44-0b8f3e2c1a02",
    "name": "Orichalcos Sword of Sealing",
    "card_type": "Spell Card",
    "race": "Equip",
    "ygoprodeck_id": "00847217",
    "card_text": (
        "The equipped monster's effects are negated. You can only use the following effect of \"Orichalcos "
        "Sword of Sealing\" once per turn. If you control a card in your Field Zone: You can target 1 Effect "
        "Monster you control; that Effect Monster gains this effect until the end of your opponent's turn.\n"
        "● Once per turn (Quick Effect): You can send 1 card from your hand to the GY, then target 1 face-up "
        "card on the field; destroy that target."
    ),
}
_ORICHALCOS_BULLETED = {
    "ygoprodeck_id": "00847217",
    **_D1,
    "reason": 'one binary gate grants this bullet once its trigger fires: "gains this effect"',
    "note": None,
}

# Moved from D1 to B1 during review, so its reason is None; the note records that move.
_X_SABER_SOUZA = {
    "id": "5c1d3a52-6a7e-4d0f-9a44-0b8f3e2c1a03",
    "name": "X-Saber Souza",
    "card_type": "Synchro Monster",
    "race": "Warrior",
    "ygoprodeck_id": "63612442",
    "card_text": (
        '1 Tuner + 1 or more non-Tuner "X-Saber" monsters\n'
        'You can Tribute 1 "X-Saber" monster, then choose 1 of these effects; this card gains that effect '
        "until the end of this turn.\n"
        "● At the start of the Damage Step, if this card battles an opponent's monster: Destroy that monster.\n"
        "● This card cannot be destroyed by Trap effects."
    ),
}
_X_SABER_SOUZA_BULLETED = {"ygoprodeck_id": "63612442", **_B1, "reason": None, "note": "moved from D1 during review"}


def _parsed_effects(card):
    from aijudge.effect_parser.parser import classify_effect_type, parse_psct

    parsed = parse_psct(card["card_text"])
    effect_type = classify_effect_type(card["card_text"], card_type=card["card_type"], race=card["race"])
    return [{
        "effect_type": effect_type.value,
        "activation_condition": parsed.activation_condition,
        "cost": parsed.cost,
        "targeting": parsed.targeting,
        "effect": parsed.effect,
        "damage_step_category": None,
        "usage_limit_text": None,
    }]


def _stub(monkeypatch, card, *, bullet_row, effects=None):
    from aijudge.orchestration import preflight

    looked_up = []
    monkeypatch.setattr(
        preflight, "get_confirmed_effects", lambda card_id: _parsed_effects(card) if effects is None else effects
    )

    def fake_get_card_bulleted(passcode):
        looked_up.append(passcode)
        return bullet_row

    monkeypatch.setattr(preflight, "get_card_bulleted", fake_get_card_bulleted)
    return looked_up


def test_known_facts_adds_the_bullet_category_line_last(monkeypatch):
    from aijudge.orchestration.preflight import build_known_facts_context

    looked_up = _stub(monkeypatch, _VARIABLE_FORM, bullet_row=_VARIABLE_FORM_BULLETED)

    context = build_known_facts_context(_VARIABLE_FORM)

    assert looked_up == ["64038662"]
    assert context.splitlines()[-1] == (
        '- Variable Form: bullet list category B1 (Player choice · activation): Always choose strictly 1 bullet, '
        'at activation ("activate 1 of these effects"). On this card: activate exactly 1 bullet (activation): '
        '"activate 1 of these".'
    )


def test_bullet_line_includes_the_category_note_when_present(monkeypatch):
    from aijudge.orchestration.preflight import build_known_facts_context

    _stub(monkeypatch, _ORICHALCOS_SWORD_OF_SEALING, bullet_row=_ORICHALCOS_BULLETED)

    last = build_known_facts_context(_ORICHALCOS_SWORD_OF_SEALING).splitlines()[-1]

    assert last == (
        f"- Orichalcos Sword of Sealing: bullet list category D1 (Mandatory grant): {_D1['description']} "
        f"Note: {_D1['category_note']} On this card: {_ORICHALCOS_BULLETED['reason']}."
    )


def test_bullet_line_omits_a_null_reason_and_includes_the_card_note(monkeypatch):
    from aijudge.orchestration.preflight import build_known_facts_context

    _stub(monkeypatch, _X_SABER_SOUZA, bullet_row=_X_SABER_SOUZA_BULLETED)

    last = build_known_facts_context(_X_SABER_SOUZA).splitlines()[-1]

    assert last == (
        f"- X-Saber Souza: bullet list category B1 (Player choice · activation): {_B1['description']} "
        "Card note: moved from D1 during review"
    )


def test_no_bullet_row_leaves_the_block_unchanged(monkeypatch):
    from aijudge.orchestration.preflight import build_known_facts_context

    _stub(monkeypatch, _VARIABLE_FORM, bullet_row=None)

    context = build_known_facts_context(_VARIABLE_FORM)

    assert "bullet list category" not in context
    # The effect line quotes the multi-line card text, so check how it ends, not where it starts.
    assert context.endswith("choose 1 or more of several listed effects at resolution: False")


def test_card_without_a_passcode_skips_the_lookup(monkeypatch):
    from aijudge.orchestration.preflight import build_known_facts_context

    looked_up = _stub(monkeypatch, _VARIABLE_FORM, bullet_row=_VARIABLE_FORM_BULLETED)
    card = {k: v for k, v in _VARIABLE_FORM.items() if k != "ygoprodeck_id"}

    assert "bullet list category" not in build_known_facts_context(card)
    assert looked_up == []


_EFFECT_VEILER = {
    "id": "8e0b7f2d-3c61-4a9e-b5d2-7f4a1c9e6b02",
    "name": "Effect Veiler",
    "card_type": "Tuner Monster",
    "race": "Spellcaster",
    "ygoprodeck_id": "97268402",
    "card_text": (
        "During your opponent's Main Phase (Quick Effect): You can send this card from your hand to the GY, then "
        "target 1 Effect Monster your opponent controls; negate the effects of that face-up monster your "
        "opponent controls, until the end of this turn."
    ),
}


def test_card_text_without_a_bullet_marker_skips_the_lookup(monkeypatch):
    from aijudge.orchestration.preflight import build_known_facts_context

    # Even a (hypothetical) row for this passcode is never fetched: a card whose
    # printed text has no bulleted list has no bullet category to show.
    looked_up = _stub(monkeypatch, _EFFECT_VEILER, bullet_row=_VARIABLE_FORM_BULLETED)

    context = build_known_facts_context(_EFFECT_VEILER)

    assert looked_up == []
    assert "bullet list category" not in context


def test_card_with_no_confirmed_effects_still_returns_empty(monkeypatch):
    from aijudge.orchestration.preflight import build_known_facts_context

    _stub(monkeypatch, _VARIABLE_FORM, bullet_row=_VARIABLE_FORM_BULLETED, effects=[])

    assert build_known_facts_context(_VARIABLE_FORM) == ""
