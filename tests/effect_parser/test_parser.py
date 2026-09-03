from aijudge.effect_parser.parser import classify_damage_step_category, classify_effect_type, extract_usage_limit_text, parse_psct
from aijudge.rules_engine.models import EffectType


def test_splits_condition_cost_and_effect_on_colon_and_semicolon():
    text = "Once per turn: You can banish 1 card from your hand; add 1 card from your Deck to your hand."
    parsed = parse_psct(text)
    assert parsed.activation_condition == "Once per turn"
    assert parsed.effect == "add 1 card from your Deck to your hand."


def test_no_colon_means_no_activation_condition():
    text = "You can target 1 banished monster; banish it."
    parsed = parse_psct(text)
    assert parsed.activation_condition is None
    assert parsed.targeting == "target 1 banished monster"
    assert parsed.effect == "banish it."


def test_no_semicolon_means_the_whole_remainder_is_the_effect():
    text = "As long as this card is on the field, all monsters you control gain 100 ATK."
    parsed = parse_psct(text)
    assert parsed.activation_condition is None
    assert parsed.cost is None
    assert parsed.targeting is None
    assert parsed.effect == text


def test_cost_before_targeting_is_split_on_a_cost_keyword():
    text = "Once per turn: You can banish 1 card from your hand, then target 1 monster on the field; destroy it."
    parsed = parse_psct(text)
    assert parsed.cost == "You can banish 1 card from your hand"
    assert parsed.targeting == "target 1 monster on the field"


def test_targeting_only_segment_with_no_cost_keyword_has_no_cost():
    text = "You can target 1 banished monster; banish it."
    parsed = parse_psct(text)
    assert parsed.cost is None


def test_ultimate_slayer_style_cost_then_target_split_on_connector():
    text = (
        "Once per turn: Send 1 monster from your Extra Deck to the GY, then target "
        "1 monster your opponent controls with the same Type as that monster; "
        "destroy it."
    )
    parsed = parse_psct(text)
    assert parsed.cost == "Send 1 monster from your Extra Deck to the GY"
    assert parsed.targeting == "target 1 monster your opponent controls with the same Type as that monster"


def test_and_if_you_do_connector_is_matched_as_one_phrase_not_split_on_bare_and():
    text = "Discard 1 card, and if you do, target 1 monster your opponent controls; destroy it."
    parsed = parse_psct(text)
    assert parsed.cost == "Discard 1 card"
    assert parsed.targeting == "target 1 monster your opponent controls"


def test_bare_and_can_ambiguously_misparse_a_single_targeting_clause():
    """Known limitation: 'and' inside a single targeting clause (listing two
    things targeted, not a cost-then-target split) is indistinguishable from
    a real cost/target connector by this heuristic. The review agent (Task
    15) is what's supposed to catch cases like this, not the code parser."""
    text = "Once per turn: You can target 1 monster and 1 Spell/Trap Card; destroy them."
    parsed = parse_psct(text)
    assert parsed.cost == "1 Spell/Trap Card"
    assert parsed.targeting == "You can target 1 monster"


def test_connector_present_but_neither_side_mentions_target_treats_whole_segment_as_cost():
    text = "Once per turn: Send 1 card from your Deck to the GY, then draw 1 card; that resolves."
    parsed = parse_psct(text)
    assert parsed.cost == "Send 1 card from your Deck to the GY, then draw 1 card"
    assert parsed.targeting is None


def test_cost_keyword_before_target_with_no_connector_is_split_via_target_keyword_scan():
    text = "Once per turn: You can discard 1 card to target 1 monster on the field; destroy it."
    parsed = parse_psct(text)
    assert parsed.cost == "You can discard 1 card to"
    assert parsed.targeting == "target 1 monster on the field"


def test_classify_effect_type_for_a_monster_trigger_effect():
    text = "If this card is Normal Summoned: You can add 1 \"Junk\" card from your Deck to your hand."
    assert classify_effect_type(text, card_type="Effect Monster") == EffectType.TRIGGER


def test_classify_effect_type_for_a_monster_quick_effect():
    text = "During your Main Phase (Quick Effect): You can target 1 monster; destroy it."
    assert classify_effect_type(text, card_type="Effect Monster") == EffectType.QUICK


def test_classify_effect_type_for_a_quick_effect_that_also_starts_with_if():
    """Real Quick Effects very commonly start with 'If...' or 'When...' AND
    contain '(Quick Effect)' — e.g. Ash Blossom & Joyous Spring's actual
    printed text. These must classify as QUICK, not TRIGGER."""
    text = (
        'If a card or effect is activated that includes any of these effects '
        '(Quick Effect): You can discard this card; negate the activation, '
        'and if you do, banish it. You can only use this effect of "Ash '
        'Blossom & Joyous Spring" once per turn.'
    )
    assert classify_effect_type(text, card_type="Effect Monster") == EffectType.QUICK


def test_classify_effect_type_for_a_continuous_effect():
    text = "While this card is face-up on the field, as long as you control no other monsters, this card gains 500 ATK."
    assert classify_effect_type(text, card_type="Effect Monster") == EffectType.CONTINUOUS


def test_classify_effect_type_for_ash_blossom_is_quick_even_though_it_starts_with_if():
    text = (
        'If a card or effect is activated that includes any of these effects '
        '(Quick Effect): You can discard this card; negate the activation, '
        'and if you do, banish it. You can only use this effect of "Ash '
        'Blossom & Joyous Spring" once per turn.'
    )
    assert classify_effect_type(text, card_type="Effect Monster") == EffectType.QUICK


def test_classify_effect_type_for_called_by_the_grave_is_quick_like_via_quick_play_race():
    """Real YGOPRODeck API shape: card_type is the generic 'Spell Card' /
    'Trap Card' string; the Quick-Play/Normal/Continuous/Counter subtype
    lives in a separate 'race' field, never folded into card_type. This must
    be read from race, not guessed via a card_type substring that the real
    API never populates."""
    text = (
        "During either player's turn, if a monster(s) is banished, or a card "
        "or effect in the Graveyard is activated: You can target 1 banished "
        "monster; banish it."
    )
    assert classify_effect_type(text, card_type="Spell Card", race="Quick-Play") == EffectType.QUICK_LIKE


def test_classify_effect_type_for_a_normal_spell_with_no_race_match_is_effect():
    text = "Target 1 monster on the field; destroy it."
    assert classify_effect_type(text, card_type="Spell Card", race="Normal") == EffectType.EFFECT


def test_classify_effect_type_for_infinite_impermanence_is_quick_like_via_trap_card_type():
    text = (
        "Target 1 face-up monster on the field; negate its effects, as well "
        "as its Trigger and Ignition Effects, until this card leaves the "
        "field. If this card is in the GY: You can banish it, except during "
        "the turn it was sent to the GY; negate the effects of all face-up "
        "monsters your opponent currently controls, until the end of this turn."
    )
    assert classify_effect_type(text, card_type="Trap Card") == EffectType.QUICK_LIKE


def test_classify_effect_type_for_effect_veiler_is_quick():
    text = (
        "During your opponent's Main Phase (Quick Effect): You can send this "
        "card from your hand to the GY; until the end of this turn, negate "
        "the effects of 1 Effect Monster your opponent controls, also its "
        'ATK becomes 0. You can only use this effect of "Effect Veiler" once '
        "per turn."
    )
    assert classify_effect_type(text, card_type="Effect Monster") == EffectType.QUICK


def test_classify_effect_type_for_solemn_strike_is_trigger_like():
    """Real API shape: card_type is the generic 'Trap Card', race is
    'Counter' -- classify_effect_type reaches TRIGGER_LIKE via the leading
    "When " check before ever consulting card_type/race, so the Counter
    subtype (which only matters for spell_speed_for, not effect_type) need
    not be present here for this to pass."""
    text = (
        "When your opponent Normal or Special Summons a monster(s), or "
        "activates a monster effect that Special Summons a monster(s): Pay "
        "1500 LP; negate the Summon or activation, and if you activated this "
        "card by targeting a Special Summoned monster(s), banish it/them."
    )
    assert classify_effect_type(text, card_type="Trap Card", race="Counter") == EffectType.TRIGGER_LIKE


def test_classify_effect_type_no_colon_no_semicolon_with_restriction_is_condition():
    text = 'You can only Special Summon "X" Monster(s) from your Extra Deck once per turn.'
    assert classify_effect_type(text, card_type="Effect Monster") == EffectType.CONDITION


def test_classify_effect_type_no_colon_no_semicolon_without_restriction_is_continuous():
    text = "As long as this card is face-up on the field, all monsters you control gain 100 ATK."
    assert classify_effect_type(text, card_type="Effect Monster") == EffectType.CONTINUOUS


def test_classify_effect_type_monster_with_colon_and_no_trigger_language_is_ignition():
    text = "Once per turn: You can target 1 card on the field; destroy it."
    assert classify_effect_type(text, card_type="Effect Monster") == EffectType.IGNITION


def test_classify_effect_type_spell_with_colon_and_non_quick_type_is_effect():
    text = "Target 1 monster on the field; destroy it."
    assert classify_effect_type(text, card_type="Spell Card") == EffectType.EFFECT


def test_classify_effect_type_for_a_trigger_with_a_leading_damage_step_timing_phrase():
    """Borreload Dragon's third effect: the condition names the Damage Step
    directly but doesn't literally start with "if"/"when" ("At the start of
    the Damage Step, if..."), so the plain startswith check misses it. Must
    still classify as TRIGGER so classify_damage_step_category can reach
    explicit_permission instead of falling through to IGNITION and losing
    it. Scoped narrowly to condition text naming "damage step"/"damage
    calculation" specifically -- NOT a general "comma + if" heuristic, since
    that would wrongly reclassify e.g. Called by the Grave's "During either
    player's turn, if..." condition (see the quick-play race test above),
    which must stay QUICK_LIKE for its spell speed to come out correct."""
    text = (
        "At the start of the Damage Step, if this card attacks an opponent's "
        "monster: You can place that opponent's monster in a zone this card "
        "points to and take control of it, but send it to the GY during the "
        "End Phase of the next turn."
    )
    assert classify_effect_type(text, card_type="Link Monster") == EffectType.TRIGGER


def test_classify_effect_type_leading_timing_phrase_without_damage_step_stays_ignition():
    """A leading timing phrase that does NOT name the Damage Step must not
    trigger the new branch -- e.g. Called by the Grave's condition, or any
    other "During X, if Y" phrasing that isn't Damage-Step-specific."""
    text = "During either player's turn, if you control no cards: You can Special Summon this card from your hand."
    assert classify_effect_type(text, card_type="Effect Monster") == EffectType.IGNITION


def test_classify_damage_step_category_detects_negates_activation():
    text = "negate the activation of that card or effect, and if you do, destroy it."
    assert classify_damage_step_category(text) == "negates_activation"


def test_classify_damage_step_category_detects_atk_def_alter():
    text = "until the end of this turn, negate the effects of 1 Effect Monster your opponent controls, also its ATK becomes 0."
    assert classify_damage_step_category(text) == "atk_def_alter"


def test_classify_damage_step_category_prefers_negates_activation_when_both_phrases_present():
    text = "negate the activation of that card or effect; also, the ATK of that monster becomes 0."
    assert classify_damage_step_category(text) == "negates_activation"


def test_classify_damage_step_category_returns_none_when_neither_pattern_matches():
    text = "target 1 banished monster; banish it."
    assert classify_damage_step_category(text) is None


def test_classify_damage_step_category_returns_none_for_a_bare_atk_mention_with_no_change_verb():
    text = "You can target 1 monster; if that monster's ATK is higher than 1000, banish it."
    assert classify_damage_step_category(text) is None


def test_classify_damage_step_category_detects_negates_activation_with_a_possessive_variant():
    text = "you can negate its activation, and if you do, destroy it."
    assert classify_damage_step_category(text) == "negates_activation"


def test_classify_damage_step_category_does_not_confuse_negate_effects_with_negate_activation():
    text = "negate the effects of 1 Effect Monster your opponent controls."
    assert classify_damage_step_category(text) is None


def test_classify_damage_step_category_detects_explicit_permission_mentioning_damage_step():
    text = "you can Special Summon 1 monster from your GY."
    assert (
        classify_damage_step_category(
            text,
            activation_condition="If this card would be destroyed by battle, during damage calculation",
            effect_type=EffectType.TRIGGER,
        )
        == "explicit_permission"
    )


def test_classify_damage_step_category_detects_explicit_permission_mentioning_damage_calculation_as_damage_step():
    text = "you can activate 1 of these effects."
    assert (
        classify_damage_step_category(
            text,
            activation_condition="This effect can be activated during damage calculation",
            effect_type=EffectType.QUICK,
        )
        == "explicit_permission"
    )


def test_classify_damage_step_category_detects_card_moved_trigger_for_self_destruction():
    text = "you can add 1 card from your Deck to your hand."
    assert (
        classify_damage_step_category(
            text,
            activation_condition="If this card is destroyed by battle",
            effect_type=EffectType.TRIGGER,
        )
        == "card_moved_trigger"
    )


def test_classify_damage_step_category_detects_card_moved_trigger_for_self_special_summon():
    text = "you can add 1 'Salamangreat' card from your Deck to your hand, except this card."
    assert (
        classify_damage_step_category(
            text,
            activation_condition="If this card is Special Summoned",
            effect_type=EffectType.TRIGGER,
        )
        == "card_moved_trigger"
    )


def test_classify_damage_step_category_detects_card_moved_trigger_for_self_sent_to_gy():
    # "sent" is the irregular past tense of "send" (e.g. Tearlaments Kitkallos:
    # "If this card is sent to the GY by card effect") -- must match alongside
    # the regular "send"/"sends"/"sending" forms already covered by \w*.
    text = "you can send the top 5 cards of your Deck to the GY."
    assert (
        classify_damage_step_category(
            text,
            activation_condition="If this card is sent to the GY by card effect",
            effect_type=EffectType.TRIGGER,
        )
        == "card_moved_trigger"
    )


def test_classify_damage_step_category_does_not_match_card_moved_trigger_for_a_non_self_card():
    text = "you can banish it instead."
    assert (
        classify_damage_step_category(
            text,
            activation_condition="If a 'Salamangreat' monster you control would be sent from the field or your hand to the GY",
            effect_type=EffectType.TRIGGER,
        )
        is None
    )


def test_classify_damage_step_category_respects_an_explicit_damage_step_exception():
    text = "you can Special Summon 1 monster from your GY."
    assert (
        classify_damage_step_category(
            text,
            activation_condition="If this card is destroyed by battle (except during the Damage Step)",
            effect_type=EffectType.TRIGGER,
        )
        is None
    )


def test_classify_damage_step_category_gates_card_moved_trigger_by_effect_type():
    text = "you can add 1 card from your Deck to your hand."
    assert (
        classify_damage_step_category(
            text,
            activation_condition="If this card is destroyed by battle",
            effect_type=EffectType.IGNITION,
        )
        is None
    )


def test_card_moved_trigger_matches_fusion_summoned_card_self_reference():
    """Tearlaments Rulkallos: 'If this Fusion Summoned card is sent to the
    GY by a card effect' -- Extra Deck monsters commonly self-refer via
    their summon-mechanic name instead of bare 'this card'."""
    result = classify_damage_step_category(
        "You can Special Summon this card.",
        activation_condition="If this Fusion Summoned card is sent to the GY by a card effect",
        effect_type=EffectType.TRIGGER,
    )

    assert result == "card_moved_trigger"


def test_card_moved_trigger_matches_xyz_monster_self_reference():
    result = classify_damage_step_category(
        "You can Special Summon this card from your GY.",
        activation_condition="If this Xyz Monster is destroyed by battle",
        effect_type=EffectType.TRIGGER,
    )

    assert result == "card_moved_trigger"


def test_card_moved_trigger_still_matches_bare_this_card():
    """Regression: the existing literal 'this card' match must keep working."""
    result = classify_damage_step_category(
        "You can add 1 card to your hand.",
        activation_condition="If this card is Tribute Summoned",
        effect_type=EffectType.TRIGGER,
    )

    assert result == "card_moved_trigger"


def test_extract_usage_limit_text_finds_a_trailing_once_per_turn_sentence():
    text = (
        "During your opponent's Main Phase (Quick Effect): You can send this "
        "card from your hand to the GY; until the end of this turn, negate "
        "the effects of 1 Effect Monster your opponent controls, also its "
        'ATK becomes 0. You can only use this effect of "Effect Veiler" once '
        "per turn."
    )
    assert extract_usage_limit_text(text) == 'You can only use this effect of "Effect Veiler" once per turn.'


def test_extract_usage_limit_text_finds_a_bare_restriction_sentence():
    text = 'You can only Special Summon "X" Monster(s) from your Extra Deck once per turn.'
    assert extract_usage_limit_text(text) == text


def test_extract_usage_limit_text_returns_none_when_absent():
    text = "You can target 1 banished monster; banish it."
    assert extract_usage_limit_text(text) is None


def test_summoning_condition_classified_for_must_be_fusion_summoned():
    """Elemental HERO Mudballman."""
    from aijudge.effect_parser.parser import classify_effect_type
    from aijudge.rules_engine.models import EffectType

    result = classify_effect_type(
        "Must be Fusion Summoned and cannot be Special Summoned by other ways.",
        card_type="Fusion Monster",
    )

    assert result == EffectType.SUMMONING_CONDITION


def test_summoning_condition_cannot_be_normal_summoned_or_set():
    from aijudge.effect_parser.parser import classify_effect_type
    from aijudge.rules_engine.models import EffectType

    result = classify_effect_type(
        "Cannot be Normal Summoned or Set.",
        card_type="Ritual Effect Monster",
    )

    assert result == EffectType.SUMMONING_CONDITION


def test_active_voice_special_summon_restriction_stays_continuous():
    """Artmage Power Patron: 'You cannot Special Summon from the Extra
    Deck, except Fusion Monsters.' is a field-wide lockdown (active voice),
    not a restriction on how *this card* is summoned (passive voice) --
    must NOT match the Summoning Condition patterns."""
    from aijudge.effect_parser.parser import classify_effect_type
    from aijudge.rules_engine.models import EffectType

    result = classify_effect_type(
        "You cannot Special Summon from the Extra Deck, except Fusion Monsters.",
        card_type="Effect Monster",
    )

    assert result == EffectType.CONTINUOUS


def test_you_can_only_still_wins_over_default_continuous():
    """Regression: existing CONDITION classification unaffected."""
    from aijudge.effect_parser.parser import classify_effect_type
    from aijudge.rules_engine.models import EffectType

    result = classify_effect_type(
        "You can only control 1 face-up.",
        card_type="Effect Monster",
    )

    assert result == EffectType.CONDITION
