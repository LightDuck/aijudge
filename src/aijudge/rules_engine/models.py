from dataclasses import dataclass
from enum import Enum


class EffectType(str, Enum):
    TRIGGER = "trigger"
    IGNITION = "ignition"
    QUICK = "quick"
    CONTINUOUS = "continuous"
    UNCLASSIFIED = "unclassified"
    CONDITION = "condition"
    EFFECT = "effect"
    TRIGGER_LIKE = "trigger-like"
    QUICK_LIKE = "quick-like"
    CARD_MATERIAL = "card_material"
    SUMMONING_CONDITION = "summoning_condition"


class SpellSpeed(int, Enum):
    NORMAL = 1
    QUICK = 2
    COUNTER = 3


_QUICK_EFFECT_TYPES = {EffectType.QUICK, EffectType.QUICK_LIKE}

_NON_ACTIVATABLE_EFFECT_TYPES = {
    EffectType.CONTINUOUS,
    EffectType.CONDITION,
    EffectType.CARD_MATERIAL,
    EffectType.SUMMONING_CONDITION,
}


def is_activatable(effect_type: EffectType) -> bool:
    """Whether an effect of this type can ever be "activated" at all.

    Continuous and Condition effects are never activated in the game-rules
    sense -- they apply automatically or describe a standing restriction.
    Every other EffectType can be activated. This is independent of
    timing/priority legality, which `can_activate_now` and
    `can_activate_during_damage_step` handle separately.
    """
    return effect_type not in _NON_ACTIVATABLE_EFFECT_TYPES


def spell_speed_for(effect_type: EffectType, *, race: str | None = None) -> SpellSpeed:
    """race is the card's YGOPRODeck `race` field ("Counter" for Counter
    Traps), not `card_type` -- the real API never folds the Trap subtype
    into `card_type` (which stays the generic "Trap Card"), so a
    `card_type` substring check can never actually see "Counter"."""
    if race == "Counter":
        return SpellSpeed.COUNTER
    return SpellSpeed.QUICK if effect_type in _QUICK_EFFECT_TYPES else SpellSpeed.NORMAL


@dataclass
class Effect:
    card_id: str
    card_name: str
    effect_type: EffectType
    controller: str
    spell_speed: SpellSpeed = SpellSpeed.NORMAL
    prevents_response: bool = False
    damage_step_category: str | None = None


@dataclass
class ChainLink:
    link_number: int
    effect: Effect
