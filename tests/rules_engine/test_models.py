from aijudge.rules_engine.models import Effect, EffectType, SpellSpeed, spell_speed_for


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
