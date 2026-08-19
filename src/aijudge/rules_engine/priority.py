from .chain import Chain
from .models import SpellSpeed


def can_activate_now(spell_speed: SpellSpeed, chain: Chain) -> bool:
    """Whether an effect of the given spell speed may be added to the
    chain right now.

    Spell Speed 1 may only activate when the chain is empty -- it can
    never respond, not even to another Spell Speed 1 effect. Spell
    Speed 2/3 may respond if their spell speed is at or above the top
    chain link's (an empty chain counts as speed 0), never below.
    Regardless of speed, a top chain link whose effect prevents
    response (e.g. "players cannot respond to this card's activation")
    blocks any response outright.

    SEGOC placement of simultaneous triggers does not go through this
    check at all -- apply_segoc adds links to the chain directly, since
    placing simultaneous triggers is not "responding," it's the
    player ordering their own triggers under a separate rule.
    """
    pending = chain.pending_links
    if not pending:
        return True
    if spell_speed == SpellSpeed.NORMAL:
        return False
    top_link = chain.resolution_order()[0]
    if top_link.effect.prevents_response:
        return False
    return spell_speed >= top_link.effect.spell_speed
