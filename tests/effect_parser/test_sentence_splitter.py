def test_splits_four_sentences_tearlaments_rulkallos_remainder():
    from aijudge.effect_parser.sentence_splitter import split_sentences

    text = (
        'Other Aqua monsters you control cannot be destroyed by battle. You can only use '
        'each of the following effects of "Tearlaments Rulkallos" once per turn. When your '
        'opponent activates a card or effect that includes an effect that Special Summons a '
        'monster(s) (Quick Effect): You can negate the activation, and if you do, destroy '
        'it, then, send 1 "Tearlaments" card from your hand or face-up field to the GY. If '
        'this Fusion Summoned card is sent to the GY by a card effect: You can Special '
        'Summon this card.'
    )

    sentences = split_sentences(text)

    assert len(sentences) == 4
    assert sentences[0] == "Other Aqua monsters you control cannot be destroyed by battle."
    assert sentences[1] == (
        'You can only use each of the following effects of "Tearlaments Rulkallos" once per turn.'
    )
    assert sentences[2].startswith("When your opponent activates")
    assert sentences[2].endswith("to the GY.")
    assert sentences[3] == (
        "If this Fusion Summoned card is sent to the GY by a card effect: "
        "You can Special Summon this card."
    )


def test_splits_three_sentences_floowandereeze_empen():
    from aijudge.effect_parser.sentence_splitter import split_sentences

    text = (
        'If this card is Tribute Summoned: You can add 1 "Floowandereeze" Spell/Trap from '
        'your Deck to your hand, then immediately after this effect resolves, you can Normal '
        'Summon 1 monster. While this Tribute Summoned card is in the Monster Zone, your '
        'opponent cannot activate the effects of Special Summoned monsters they control in '
        'Attack Position. Once per battle, during damage calculation, if this card battles '
        "an opponent's monster (Quick Effect): You can banish 1 card from your hand; that "
        "opponent's monster's current ATK/DEF become halved until the end of this turn."
    )

    sentences = split_sentences(text)

    assert len(sentences) == 3
    assert sentences[0].startswith("If this card is Tribute Summoned")
    assert sentences[1].startswith("While this Tribute Summoned card")
    assert sentences[2].startswith("Once per battle")


def test_single_sentence_mudballman_remainder():
    from aijudge.effect_parser.sentence_splitter import split_sentences

    text = "Must be Fusion Summoned and cannot be Special Summoned by other ways."

    assert split_sentences(text) == [text]


def test_empty_text_returns_empty_list():
    from aijudge.effect_parser.sentence_splitter import split_sentences

    assert split_sentences("") == []
    assert split_sentences("   ") == []


def test_extracts_material_for_fusion_monster_tearlaments_rulkallos():
    from aijudge.effect_parser.sentence_splitter import extract_card_material

    card_text = (
        '"Tearlaments Kitkallos" + 1 "Tearlaments" monster\r\n'
        'Other Aqua monsters you control cannot be destroyed by battle.'
    )

    material, remainder = extract_card_material(card_text, card_type="Fusion Monster")

    assert material == '"Tearlaments Kitkallos" + 1 "Tearlaments" monster'
    assert remainder == "Other Aqua monsters you control cannot be destroyed by battle."


def test_extracts_material_case_insensitively_for_xyz_monster():
    """YGOPRODeck's real `type` field for Xyz monsters is 'XYZ Monster'
    (all-caps XYZ), not 'Xyz Monster' -- this must match either way."""
    from aijudge.effect_parser.sentence_splitter import extract_card_material

    material, remainder = extract_card_material("2 Level 4 monsters", card_type="XYZ Monster")

    assert material == "2 Level 4 monsters"
    assert remainder == ""


def test_vanilla_extra_deck_monster_has_empty_remainder():
    """Gem-Knight Pearl: has_effect=0, the entire card_text is the
    materials line."""
    from aijudge.effect_parser.sentence_splitter import extract_card_material

    material, remainder = extract_card_material("2 Level 4 monsters", card_type="XYZ Monster")

    assert material == "2 Level 4 monsters"
    assert remainder == ""


def test_no_material_for_non_extra_deck_monster():
    from aijudge.effect_parser.sentence_splitter import extract_card_material

    card_text = "If this card is Tribute Summoned: You can add 1 card to your hand."

    material, remainder = extract_card_material(card_text, card_type="Effect Monster")

    assert material is None
    assert remainder == card_text


def test_synchro_and_link_also_match():
    from aijudge.effect_parser.sentence_splitter import extract_card_material

    assert extract_card_material("1 Tuner + 1+ non-Tuner monsters", card_type="Synchro Monster")[0] is not None
    assert extract_card_material("2 monsters, including a Tuner", card_type="Link Monster")[0] is not None
