from aijudge.rules_engine.chain import Chain
from aijudge.rules_engine.models import Effect, EffectType, SpellSpeed
from aijudge.rules_engine.priority import can_activate_now


def test_any_spell_speed_can_activate_when_chain_is_empty():
    chain = Chain()
    assert can_activate_now(SpellSpeed.NORMAL, chain) is True
    assert can_activate_now(SpellSpeed.QUICK, chain) is True


def test_normal_speed_effect_cannot_respond_to_a_chain_in_progress():
    chain = Chain()
    chain.add_link(Effect(card_id="1", card_name="Card A", effect_type=EffectType.IGNITION, controller="player_a"))
    assert can_activate_now(SpellSpeed.NORMAL, chain) is False


def test_quick_speed_effect_can_respond_to_a_chain_in_progress():
    chain = Chain()
    chain.add_link(Effect(card_id="1", card_name="Card A", effect_type=EffectType.IGNITION, controller="player_a"))
    assert can_activate_now(SpellSpeed.QUICK, chain) is True


def test_quick_can_respond_to_quick():
    chain = Chain()
    chain.add_link(
        Effect(
            card_id="1",
            card_name="Card A",
            effect_type=EffectType.QUICK,
            controller="player_a",
            spell_speed=SpellSpeed.QUICK,
        )
    )
    assert can_activate_now(SpellSpeed.QUICK, chain) is True


def test_quick_cannot_respond_to_counter():
    chain = Chain()
    chain.add_link(
        Effect(
            card_id="1",
            card_name="Card A",
            effect_type=EffectType.CONDITION,
            controller="player_a",
            spell_speed=SpellSpeed.COUNTER,
        )
    )
    assert can_activate_now(SpellSpeed.QUICK, chain) is False


def test_counter_can_respond_to_counter():
    chain = Chain()
    chain.add_link(
        Effect(
            card_id="1",
            card_name="Card A",
            effect_type=EffectType.CONDITION,
            controller="player_a",
            spell_speed=SpellSpeed.COUNTER,
        )
    )
    assert can_activate_now(SpellSpeed.COUNTER, chain) is True


def test_counter_can_respond_to_quick():
    chain = Chain()
    chain.add_link(
        Effect(
            card_id="1",
            card_name="Card A",
            effect_type=EffectType.QUICK,
            controller="player_a",
            spell_speed=SpellSpeed.QUICK,
        )
    )
    assert can_activate_now(SpellSpeed.COUNTER, chain) is True


def test_prevents_response_blocks_everything_regardless_of_speed():
    chain = Chain()
    chain.add_link(
        Effect(
            card_id="1",
            card_name="Card A",
            effect_type=EffectType.QUICK,
            controller="player_a",
            spell_speed=SpellSpeed.QUICK,
            prevents_response=True,
        )
    )
    assert can_activate_now(SpellSpeed.COUNTER, chain) is False
