from .chain import Chain
from .models import SpellSpeed


def can_activate_now(spell_speed: SpellSpeed, chain: Chain) -> bool:
    """Whether an effect of the given spell speed may be added to the
    chain right now.

    A Spell Speed 1 effect may only be activated when the chain is
    empty — it cannot respond to anything already on the chain. A
    Spell Speed 2 effect may always respond, chain empty or not.
    """
    if not chain.pending_links:
        return True
    return spell_speed == SpellSpeed.QUICK
