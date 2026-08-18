from .chain import Chain
from .models import Effect


def apply_segoc(chain: Chain, *, turn_player: str, triggered_effects: list[Effect]) -> Chain:
    """Add simultaneously-triggered effects to the chain per SEGOC.

    The turn player's effects are chained first (in the order given —
    ordering *within* one player's simultaneous effects is that
    player's choice, not a rule this function decides). Because chain
    resolution is LIFO, chaining first means resolving LAST. The
    non-turn player's effects are chained second and so resolve first.
    """
    turn_player_effects = [e for e in triggered_effects if e.controller == turn_player]
    non_turn_player_effects = [e for e in triggered_effects if e.controller != turn_player]

    for effect in turn_player_effects:
        chain.add_link(effect)
    for effect in non_turn_player_effects:
        chain.add_link(effect)

    return chain
