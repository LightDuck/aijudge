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


class SpellSpeed(int, Enum):
    NORMAL = 1
    QUICK = 2


_QUICK_EFFECT_TYPES = {EffectType.QUICK, EffectType.QUICK_LIKE}


def spell_speed_for(effect_type: EffectType) -> SpellSpeed:
    return SpellSpeed.QUICK if effect_type in _QUICK_EFFECT_TYPES else SpellSpeed.NORMAL


@dataclass
class Effect:
    card_id: str
    card_name: str
    effect_type: EffectType
    controller: str


@dataclass
class ChainLink:
    link_number: int
    effect: Effect
