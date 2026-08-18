from aijudge.rules_engine.chain import Chain
from aijudge.rules_engine.models import Effect, EffectType
from aijudge.rules_engine.segoc import apply_segoc


def _triggered(name: str, controller: str) -> Effect:
    return Effect(card_id=name, card_name=name, effect_type=EffectType.TRIGGER, controller=controller)


def test_turn_player_effects_are_chained_first_and_so_resolve_last():
    chain = Chain()
    turn_player_effect = _triggered("Turn Player's Card", "player_a")
    opponent_effect = _triggered("Opponent's Card", "player_b")

    apply_segoc(chain, turn_player="player_a", triggered_effects=[turn_player_effect, opponent_effect])

    assert [link.effect.card_name for link in chain.links] == ["Turn Player's Card", "Opponent's Card"]

    order = chain.resolution_order()
    assert order[0].effect.card_name == "Opponent's Card"
    assert order[1].effect.card_name == "Turn Player's Card"


def test_within_one_players_effects_the_given_order_is_preserved():
    chain = Chain()
    first = _triggered("Turn Player's First Choice", "player_a")
    second = _triggered("Turn Player's Second Choice", "player_a")

    apply_segoc(chain, turn_player="player_a", triggered_effects=[first, second])

    assert [link.effect.card_name for link in chain.links] == [
        "Turn Player's First Choice",
        "Turn Player's Second Choice",
    ]
