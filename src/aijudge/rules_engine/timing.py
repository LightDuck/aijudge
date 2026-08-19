from enum import Enum

from .models import SpellSpeed


class TimingEventType(str, Enum):
    """What kind of thing most recently happened, for missing-timing checks."""
    RESOLVED = "resolved"        # a chain link fully resolved
    GAME_ACTION = "game_action"  # a non-chain game action (Summon, phase change, etc.)
    ACTIVATED = "activated"      # a chain link was activated (added to the chain)


def check_missing_timing(
    trigger_step: int,
    current_step: int,
    *,
    last_event_type: TimingEventType,
    spell_speed: SpellSpeed,
) -> bool:
    """Whether a "when"-conditioned effect has missed its activation timing.

    The effect's activation window is the moment immediately after the
    event its condition names (trigger_step). Any other step passing
    means timing is missed (current_step > trigger_step).

    At trigger_step itself, whether the window is open depends on the
    checking effect's own spell speed and what kind of event
    last_event_type describes:
    - Spell Speed 1: the window is open only if the last event was a
      chain link fully RESOLVING, or a non-chain GAME_ACTION. A Spell
      Speed 1 effect cannot trigger off a bare ACTIVATION.
    - Spell Speed 2/3 (Quick Effects, Counter Traps): the window is
      open only if the last event was the specific chain link
      ACTIVATING that matches the condition -- quick effects can
      respond to an activation itself, before it resolves.
    """
    if current_step < trigger_step:
        raise ValueError("current_step cannot precede trigger_step")
    if current_step > trigger_step:
        return True

    if spell_speed == SpellSpeed.NORMAL:
        return last_event_type not in (TimingEventType.RESOLVED, TimingEventType.GAME_ACTION)
    return last_event_type != TimingEventType.ACTIVATED
