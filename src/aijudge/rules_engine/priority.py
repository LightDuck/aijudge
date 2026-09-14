from .chain import Chain
from .models import DamageStepCategory, Effect, SpellSpeed

# Gated to Spell Speed 2: real cards in these categories are inherently
# Quick Effects/Traps, per the official rulebook.
_DAMAGE_STEP_SPEED_GATED_CATEGORIES = {DamageStepCategory.ATK_DEF_ALTER, DamageStepCategory.NEGATES_ACTIVATION}

# NOT gated by spell speed: a plain Trigger Effect is normally Speed 1, but
# these two categories are Damage-Step-legal specifically despite that --
# either the card says so directly (explicit_permission), or its trigger
# condition is itself a Damage-Step event that couldn't be met any earlier
# (card_moved_trigger).
_DAMAGE_STEP_UNGATED_CATEGORIES = {DamageStepCategory.EXPLICIT_PERMISSION, DamageStepCategory.CARD_MOVED_TRIGGER}


def can_activate_during_damage_step(effect: Effect) -> bool:
    """Whether `effect` may be activated during the Damage Step.

    Per the current official rulebook, the baseline is: Spell Speed 3
    (Counter Trap) cards, or Spell Speed 2 effects that alter ATK/DEF
    or negate an activation. On top of that, two more categories are
    legal regardless of spell speed: an effect whose own activation
    condition names "damage step"/"damage calculation" directly
    (`"explicit_permission"`), and a Trigger-type effect whose own card
    is what moved -- e.g. "if this card is destroyed by battle"
    (`"card_moved_trigger"`) -- since such a condition can only ever be
    met during (or immediately after) the Damage Step itself. This is
    independent of `can_activate_now`'s chain-response priority check
    -- both must pass for a Damage Step activation to be legal.
    """
    if effect.spell_speed == SpellSpeed.COUNTER:
        return True
    if effect.damage_step_category in _DAMAGE_STEP_UNGATED_CATEGORIES:
        return True
    if effect.spell_speed == SpellSpeed.QUICK:
        return effect.damage_step_category in _DAMAGE_STEP_SPEED_GATED_CATEGORIES
    return False


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
