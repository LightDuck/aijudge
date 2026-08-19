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
    COUNTER = 3


_QUICK_EFFECT_TYPES = {EffectType.QUICK, EffectType.QUICK_LIKE}


def spell_speed_for(effect_type: EffectType, *, card_type: str | None = None) -> SpellSpeed:
    if card_type and "Counter" in card_type:
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


@dataclass
class ChainLink:
    link_number: int
    effect: Effect
