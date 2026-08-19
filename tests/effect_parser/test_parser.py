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
    assert classify_effect_type(text, is_monster=True) == EffectType.TRIGGER


def test_classify_effect_type_for_a_monster_quick_effect():
    text = "During your Main Phase (Quick Effect): You can target 1 monster; destroy it."
    assert classify_effect_type(text, is_monster=True) == EffectType.QUICK


def test_classify_effect_type_for_a_continuous_effect():
    text = "While this card is face-up on the field, as long as you control no other monsters, this card gains 500 ATK."
    assert classify_effect_type(text, is_monster=True) == EffectType.CONTINUOUS
