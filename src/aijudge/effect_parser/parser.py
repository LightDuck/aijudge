import re
from dataclasses import dataclass

from aijudge.rules_engine.models import EffectType

_COST_KEYWORDS = ("banish", "discard", "pay", "send", "tribute", "remove", "reveal", "shuffle")

# Checked in this order (longest/most specific first) so that, e.g., "and if
# you do" is matched as one phrase rather than being cut short at "and".
_PSCT_CONNECTORS = ("and if you do", "then", "also", "and")
_CONNECTOR_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(word) for word in _PSCT_CONNECTORS) + r")\b",
    re.IGNORECASE,
)


@dataclass
class ParsedEffect:
    activation_condition: str | None
    cost: str | None
    targeting: str | None
    effect: str


def parse_psct(card_text: str) -> ParsedEffect:
    """Split PSCT-formatted card text using its formal grammar:
    `[Condition] : [Cost/Target] ; [Effect]`, where the Condition and
    Cost/Target segments are optional.
    """
    text = card_text.strip()

    if ":" in text:
        activation_condition, remainder = text.split(":", 1)
        activation_condition = activation_condition.strip() or None
        remainder = remainder.strip()
    else:
        activation_condition = None
        remainder = text

    if ";" in remainder:
        cost_and_targeting, effect = remainder.split(";", 1)
        cost_and_targeting = cost_and_targeting.strip()
        effect = effect.strip()
    else:
        cost_and_targeting = None
        effect = remainder

    cost, targeting = _split_cost_and_targeting(cost_and_targeting)

    return ParsedEffect(activation_condition=activation_condition, cost=cost, targeting=targeting, effect=effect)


def _split_cost_and_targeting(segment: str | None) -> tuple[str | None, str | None]:
    if not segment:
        return None, None

    connector_match = _CONNECTOR_PATTERN.search(segment)
    if connector_match:
        left = segment[: connector_match.start()].strip(" ,")
        right = segment[connector_match.end():].strip(" ,")
        if "target" in right.lower():
            return (left or None), (right or None)
        if "target" in left.lower():
            return (right or None), (left or None)
        return segment, None

    return _split_on_target_keyword(segment)


def _split_on_target_keyword(segment: str) -> tuple[str | None, str | None]:
    lowered = segment.lower()
    target_index = lowered.find("target")
    if target_index == -1:
        return segment, None

    before_target = segment[:target_index]
    targeting = segment[target_index:].strip()
    has_cost_keyword = any(keyword in before_target.lower() for keyword in _COST_KEYWORDS)
    if not has_cost_keyword:
        return None, targeting

    cost = before_target.strip().rstrip(",")
    return (cost or None), targeting


def classify_effect_type(card_text: str, *, card_type: str) -> EffectType:
    """Classify a card's effect type from its raw PSCT text and card type.

    Checked in this order:
    1. "(Quick Effect)" anywhere in the text -> QUICK (monster) /
       QUICK_LIKE (spell-trap). Checked first since real Quick Effects
       very commonly also start with "If"/"When".
    2. No colon AND no semicolon anywhere in the text (no PSCT
       activation grammar at all): a restriction pattern ("you can
       only") -> CONDITION; otherwise -> CONTINUOUS.
    3. Text starts with "if " or "when " (a game-action-fulfilled or
       effect-just-resolved condition) -> TRIGGER (monster) /
       TRIGGER_LIKE (spell-trap).
    4. Otherwise (has PSCT grammar, didn't match above): for a
       monster, IGNITION (an activation condition that lacks
       conditional/triggering terms). For a spell/trap: QUICK_LIKE if
       card_type contains "Quick-Play" or "Trap" (both are inherently
       Spell Speed 2 by game rule, regardless of text pattern) --
       otherwise EFFECT (e.g. a Normal Spell, Continuous Spell not
       caught by the no-colon-no-semicolon check, Field Spell, etc.).

    is_monster is derived internally from card_type (whether it
    contains the substring "Monster") rather than taken as a separate
    parameter.
    """
    is_monster = "Monster" in card_type
    text = card_text.strip()
    lowered = text.lower()

    if "(quick effect)" in lowered:
        return EffectType.QUICK if is_monster else EffectType.QUICK_LIKE

    if ":" not in text and ";" not in text:
        if "you can only" in lowered:
            return EffectType.CONDITION
        return EffectType.CONTINUOUS

    if lowered.startswith("if ") or lowered.startswith("when "):
        return EffectType.TRIGGER if is_monster else EffectType.TRIGGER_LIKE

    if is_monster:
        return EffectType.IGNITION
    if "Quick-Play" in card_type or "Trap" in card_type:
        return EffectType.QUICK_LIKE
    return EffectType.EFFECT
