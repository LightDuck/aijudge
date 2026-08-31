from aijudge.rules_engine.models import Effect, EffectType, SpellSpeed, is_activatable, spell_speed_for


def test_quick_and_quick_like_effects_are_spell_speed_2():
    assert spell_speed_for(EffectType.QUICK) == SpellSpeed.QUICK
    assert spell_speed_for(EffectType.QUICK_LIKE) == SpellSpeed.QUICK


def test_other_effect_types_default_to_spell_speed_1():
    assert spell_speed_for(EffectType.IGNITION) == SpellSpeed.NORMAL
    assert spell_speed_for(EffectType.TRIGGER) == SpellSpeed.NORMAL
    assert spell_speed_for(EffectType.CONTINUOUS) == SpellSpeed.NORMAL
    assert spell_speed_for(EffectType.UNCLASSIFIED) == SpellSpeed.NORMAL


def test_effect_is_constructible():
    effect = Effect(
        card_id="1",
        card_name="Called by the Grave",
        effect_type=EffectType.QUICK_LIKE,
        controller="player_a",
    )
    assert effect.controller == "player_a"


def test_counter_trap_card_type_is_spell_speed_3():
    assert spell_speed_for(EffectType.CONDITION, card_type="Counter Trap Card") == SpellSpeed.COUNTER


def test_quick_effect_type_is_still_spell_speed_2_when_card_type_omitted():
    assert spell_speed_for(EffectType.QUICK) == SpellSpeed.QUICK


def test_ignition_effect_type_is_still_spell_speed_1_when_card_type_omitted():
    assert spell_speed_for(EffectType.IGNITION) == SpellSpeed.NORMAL


def test_effect_accepts_explicit_spell_speed_and_prevents_response():
    effect = Effect(
        card_id="1",
        card_name="Solemn Judgment",
        effect_type=EffectType.CONDITION,
        controller="player_a",
        spell_speed=SpellSpeed.COUNTER,
        prevents_response=True,
    )
    assert effect.spell_speed == SpellSpeed.COUNTER
    assert effect.prevents_response is True


def test_is_activatable_returns_false_for_continuous_and_condition():
    assert is_activatable(EffectType.CONTINUOUS) is False
    assert is_activatable(EffectType.CONDITION) is False


def test_is_activatable_returns_true_for_other_effect_types():
    assert is_activatable(EffectType.TRIGGER) is True
    assert is_activatable(EffectType.TRIGGER_LIKE) is True
    assert is_activatable(EffectType.IGNITION) is True
    assert is_activatable(EffectType.QUICK) is True
    assert is_activatable(EffectType.QUICK_LIKE) is True
    assert is_activatable(EffectType.EFFECT) is True
