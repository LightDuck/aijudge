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

_NEGATES_ACTIVATION_PATTERN = re.compile(r"negate\w*\s+(?:the|its|that|this)\s+activation", re.IGNORECASE)
# Matches only an ATK/DEF *alteration* (a change-indicating verb within a
# short distance of the ATK/DEF token), not a bare mention/comparison like
# "if that monster's ATK is higher than 1000". ATK/DEF stays case-sensitive
# (official card text always renders these uppercase); the change-verb is
# matched case-insensitively via a scoped inline flag.
_CHANGE_VERBS = r"(?:become|gain|lose|increase|decrease|halve|double)\w*"
_ATK_DEF_PATTERN = re.compile(
    rf"\b(?:ATK|DEF)\b.{{0,20}}?(?i:\b{_CHANGE_VERBS}\b)"
    rf"|(?i:\b{_CHANGE_VERBS}\b).{{0,20}}?\b(?:ATK|DEF)\b"
)

_USAGE_LIMIT_PATTERN = re.compile(r"You can only [^.]*\bper turn\.", re.IGNORECASE)

# Effects that self-declare Damage-Step legality in their own activation
# condition -- "damage calculation" is treated as equivalent to "damage step"
# for this project.
_EXPLICIT_DAMAGE_STEP_PERMISSION_PATTERN = re.compile(r"damage (?:step|calculation)", re.IGNORECASE)

# A card explicitly carving itself OUT of Damage-Step activation (e.g.
# "except during the Damage Step") overrides every other category -- checked
# first in classify_damage_step_category.
_DAMAGE_STEP_EXCEPTION_PATTERN = re.compile(
    r"(?:except|not).{0,20}during the damage (?:step|calculation)"
    r"|cannot be activated during the damage (?:step|calculation)",
    re.IGNORECASE,
)

# A Trigger/Trigger-like/Quick/Quick-like effect whose *own card* undergoes a
# zone-change verb as its activation condition -- e.g. "if this card is
# destroyed by battle" or "if this card is Special Summoned". Deliberately
# requires "this card" (self-reference); a condition about some *other* card
# moving (e.g. "if a Salamangreat monster... is sent to the GY") is not
# reliably Damage-Step-legal (real cards carve such conditions out
# explicitly), so it is intentionally left unmatched rather than guessed.
# "sent" is the irregular past tense of "send" (e.g. Tearlaments Kitkallos:
# "if this card is sent to the GY by card effect") and needs its own bare
# alternative rather than a "send"-plus-\w* stem match, since \w* after
# "sent" would also swallow unrelated words like "sentence".
_SELF_MOVEMENT_VERBS = r"(?:(?:destroy|banish|send)\w*|sent|(?:return|summon|flip|tribute)\w*)"
_CARD_MOVED_TRIGGER_PATTERN = re.compile(
    rf"\bthis card\b.{{0,40}}?\b{_SELF_MOVEMENT_VERBS}\b"
    rf"|\b{_SELF_MOVEMENT_VERBS}\b.{{0,40}}?\bthis card\b",
    re.IGNORECASE,
)

_DAMAGE_STEP_ELIGIBLE_EFFECT_TYPES = {
    EffectType.TRIGGER,
    EffectType.TRIGGER_LIKE,
    EffectType.QUICK,
    EffectType.QUICK_LIKE,
}


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


def classify_damage_step_category(
    effect_text: str,
    *,
    activation_condition: str | None = None,
    effect_type: EffectType | None = None,
) -> str | None:
    """Classify which (if any) Damage-Step-legal category this effect falls
    into: `"negates_activation"` and `"atk_def_alter"` (sourced from the
    official rulebook, checked against `effect_text` -- the resolution
    clause -- since that's where a negation or an ATK/DEF change is actually
    described); `"explicit_permission"` (the card's own `activation_condition`
    names "damage step" or "damage calculation" directly); or
    `"card_moved_trigger"` (a Trigger/Trigger-like/Quick/Quick-like effect
    whose own card is the subject of a zone-change verb in its condition,
    e.g. "if this card is destroyed by battle"). The latter two are checked
    against `activation_condition`, not `effect_text` -- that's where PSCT
    puts a trigger's condition -- and only for effect types that can carry a
    triggering condition at all.

    An explicit exception in the condition (e.g. "except during the Damage
    Step") is checked first and overrides every other category, since the
    card is telling us directly it does not get the exception -- see
    Salamangreat Gazelle's non-self GY-cost effect for a real example of a
    condition that would otherwise look Damage-Step-eligible.

    `negates_activation` is checked before `atk_def_alter` since "negate the
    activation" is the more specific phrase -- an effect can mention ATK/DEF
    changes incidentally while its Damage-Step-relevant behavior is really
    the negation. Returns None when nothing matches, rather than guessing --
    in particular, a condition about some *other* card moving (not "this
    card") is deliberately never classified as `card_moved_trigger`.
    """
    if activation_condition and _DAMAGE_STEP_EXCEPTION_PATTERN.search(activation_condition):
        return None
    if _NEGATES_ACTIVATION_PATTERN.search(effect_text):
        return "negates_activation"
    if _ATK_DEF_PATTERN.search(effect_text):
        return "atk_def_alter"
    if activation_condition and effect_type in _DAMAGE_STEP_ELIGIBLE_EFFECT_TYPES:
        if _EXPLICIT_DAMAGE_STEP_PERMISSION_PATTERN.search(activation_condition):
            return "explicit_permission"
        if _CARD_MOVED_TRIGGER_PATTERN.search(activation_condition):
            return "card_moved_trigger"
    return None


def extract_usage_limit_text(card_text: str) -> str | None:
    """Extract a usage-count restriction sentence ("You can only ... per
    turn.") from raw card text, independent of `parse_psct`'s Condition/
    Cost/Effect split -- this kind of clause is a trailing sentence that
    split doesn't decompose (see Effect Veiler: it follows the semicolon-
    delimited effect clause, not inside it). Stored for reference only;
    never enforced, since this project tracks no live game state.
    """
    match = _USAGE_LIMIT_PATTERN.search(card_text)
    return match.group(0) if match else None
