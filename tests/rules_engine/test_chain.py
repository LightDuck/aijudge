import pytest

from aijudge.rules_engine.chain import Chain
from aijudge.rules_engine.models import Effect, EffectType


def _effect(name: str, controller: str = "player_a") -> Effect:
    return Effect(card_id=name, card_name=name, effect_type=EffectType.IGNITION, controller=controller)


def test_add_link_assigns_increasing_link_numbers():
    chain = Chain()
    link1 = chain.add_link(_effect("Card A"))
    link2 = chain.add_link(_effect("Card B"))
    assert link1.link_number == 1
    assert link2.link_number == 2


def test_resolution_order_is_lifo():
    chain = Chain()
    chain.add_link(_effect("Card A"))
    chain.add_link(_effect("Card B"))
    chain.add_link(_effect("Card C"))
    order = chain.resolution_order()
    assert [link.effect.card_name for link in order] == ["Card C", "Card B", "Card A"]


def test_resolve_next_pops_highest_link_first():
    chain = Chain()
    chain.add_link(_effect("Card A"))
    chain.add_link(_effect("Card B"))
    first = chain.resolve_next()
    second = chain.resolve_next()
    assert first.effect.card_name == "Card B"
    assert second.effect.card_name == "Card A"
    assert chain.pending_links == []


def test_resolve_next_raises_when_chain_is_empty():
    chain = Chain()
    with pytest.raises(ValueError):
        chain.resolve_next()
