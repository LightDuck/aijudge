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


def test_counter_race_is_spell_speed_3():
    """race, not card_type, is the source of truth for Counter Traps --
    YGOPRODeck's real API never folds "Counter" into card_type (that stays
    the generic "Trap Card"); the subtype comes back in a separate `race`
    field."""
    assert spell_speed_for(EffectType.CONDITION, race="Counter") == SpellSpeed.COUNTER


def test_quick_effect_type_is_still_spell_speed_2_when_race_omitted():
    assert spell_speed_for(EffectType.QUICK) == SpellSpeed.QUICK


def test_ignition_effect_type_is_still_spell_speed_1_when_race_omitted():
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


def test_effect_accepts_damage_step_category():
    effect = Effect(
        card_id="1",
        card_name="Effect Veiler",
        effect_type=EffectType.QUICK,
        controller="player_a",
        spell_speed=SpellSpeed.QUICK,
        damage_step_category="atk_def_alter",
    )
    assert effect.damage_step_category == "atk_def_alter"


def test_effect_damage_step_category_defaults_to_none():
    effect = Effect(card_id="1", card_name="Card A", effect_type=EffectType.IGNITION, controller="player_a")
    assert effect.damage_step_category is None


def test_card_material_is_not_activatable():
    assert is_activatable(EffectType.CARD_MATERIAL) is False


def test_summoning_condition_is_not_activatable():
    assert is_activatable(EffectType.SUMMONING_CONDITION) is False
