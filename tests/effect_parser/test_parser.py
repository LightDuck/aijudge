from aijudge.effect_parser.parser import classify_effect_type, parse_psct
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


def test_classify_effect_type_for_called_by_the_grave_is_quick_like_via_quick_play_card_type():
    text = (
        "During either player's turn, if a monster(s) is banished, or a card "
        "or effect in the Graveyard is activated: You can target 1 banished "
        "monster; banish it."
    )
    assert classify_effect_type(text, card_type="Quick-Play Spell") == EffectType.QUICK_LIKE


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
    text = (
        "When your opponent Normal or Special Summons a monster(s), or "
        "activates a monster effect that Special Summons a monster(s): Pay "
        "1500 LP; negate the Summon or activation, and if you activated this "
        "card by targeting a Special Summoned monster(s), banish it/them."
    )
    assert classify_effect_type(text, card_type="Counter Trap Card") == EffectType.TRIGGER_LIKE


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
    assert classify_effect_type(text, card_type="Normal Spell") == EffectType.EFFECT
