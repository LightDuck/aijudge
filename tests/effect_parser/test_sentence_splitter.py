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
