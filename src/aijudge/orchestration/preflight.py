import difflib
import re

_FUZZY_CUTOFF = 0.75


def find_mentioned_card_names(question: str, known_names: list[str]) -> list[str]:
    """Return every name in `known_names` plausibly mentioned in `question`.

    Matches an exact (case-insensitive, word-boundary) substring first, so
    a card name embedded inside an unrelated longer word never falsely
    matches. Falls back to a fuzzy comparison against every equal-length
    word-window of the question, so a slightly misspelled or incomplete
    name still matches (e.g. "Effect Viler" against "Effect Veiler").
    """
    return [name for name in known_names if _mentions_name(name, question)]


def _mentions_name(name: str, question: str) -> bool:
    pattern = r"\b" + re.escape(name.lower()) + r"\b"
    if re.search(pattern, question.lower()):
        return True
    return _fuzzy_mentions_name(name, question)


def _fuzzy_mentions_name(name: str, question: str) -> bool:
    words = question.lower().split()
    name_lower = name.lower()
    name_word_count = len(name_lower.split())
    windows = (
        " ".join(words[i : i + name_word_count])
        for i in range(len(words) - name_word_count + 1)
    )
    return any(
        difflib.SequenceMatcher(None, window, name_lower).ratio() >= _FUZZY_CUTOFF
        for window in windows
    )


from aijudge.db.cards_repo import get_card_by_name, list_card_names
from aijudge.db.effects_repo import get_confirmed_effects
from aijudge.rules_engine.models import Effect, EffectType, is_activatable, spell_speed_for
from aijudge.rules_engine.priority import can_activate_during_damage_step


def find_matched_cards(question: str) -> list[dict]:
    """Return the full card dict (as `get_card_by_name` returns it) for
    every card plausibly mentioned in `question`."""
    names = find_mentioned_card_names(question, list_card_names())
    return [get_card_by_name(name) for name in names]


def build_known_facts_context(card: dict) -> str:
    """Render a deterministic "KNOWN FACTS" block covering every one of a
    card's confirmed effects -- not just one -- so a question about any of
    them can be grounded. Each line's facts (effect type, spell speed,
    activatable, Damage Step legality) come entirely from existing
    `rules_engine` functions; nothing here interprets the question. Returns
    "" if the card has no confirmed effects at all -- callers fall back to
    unaided LLM reasoning in that case, same as before."""
    confirmed_effects = get_confirmed_effects(card["id"])
    if not confirmed_effects:
        return ""
    lines = [
        f"KNOWN FACTS (deterministic -- do not contradict) -- {card['name']} is a "
        f"{card['card_type']}. Printed text: \"{card['card_text']}\". If you answer "
        f"using only these facts, cite {card['name']} as card:{card['id']}:"
    ]
    for index, confirmed in enumerate(confirmed_effects, start=1):
        effect_type = EffectType(confirmed["effect_type"])

        if effect_type == EffectType.CARD_MATERIAL:
            lines.append(f"- {card['name']}: Card Material: \"{confirmed['effect']}\"")
            continue
        if effect_type == EffectType.SUMMONING_CONDITION:
            lines.append(f"- {card['name']}: Summoning Condition: \"{confirmed['effect']}\"")
            continue

        speed = spell_speed_for(effect_type, race=card["race"])
        effect = Effect(
            card_id=card["id"],
            card_name=card["name"],
            effect_type=effect_type,
            controller="unknown",
            spell_speed=speed,
            damage_step_category=confirmed.get("damage_step_category"),
        )
        # Every optional field is shown explicitly, even when absent (as "none"),
        # rather than silently omitted -- so the model can state e.g. "this
        # effect has no cost" as a known fact instead of never being told the
        # field exists at all, and never has to guess whether an unlisted field
        # is truly absent or just left out of this summary.
        line = (
            f"- {card['name']}, effect {index}: effect type {effect_type.value}, spell speed {speed.value}, "
            f"activatable: {is_activatable(effect_type)}, "
            f"damage-step legal: {can_activate_during_damage_step(effect)}, "
            f"activation condition: {confirmed.get('activation_condition') or 'none'}, "
            f"cost: {confirmed.get('cost') or 'none'}, "
            f"targeting: {confirmed.get('targeting') or 'none'}, "
            f"effect: \"{confirmed['effect']}\", "
            f"damage step category: {confirmed.get('damage_step_category') or 'none'}, "
            f"usage limit: {confirmed.get('usage_limit_text') or 'none'}, "
            f"choose 1 or more of several listed effects at resolution: {confirmed.get('has_effect_choice', False)}"
        )
        lines.append(line)
    return "\n".join(lines)


def build_grounded_result(card: dict) -> dict:
    """Build a `lookup_card`-tool-result-shaped dict for a card already
    resolved via preflight matching, so `run_loop` can pre-register its id
    as a legitimate citation source (via `update_signals`) without an
    actual `lookup_card` tool call. Needed because a card whose KNOWN FACTS
    already answer the question gives the LLM no reason to call
    `lookup_card` itself, and without this, the id it's told to cite in
    `build_known_facts_context`'s text would otherwise never appear in
    `SignalState.known_ids` -- indistinguishable from a fabricated one."""
    return {
        "found": True,
        "id": card["id"],
        "ygoprodeck_id": card.get("ygoprodeck_id"),
        "name": card["name"],
        "card_text": card.get("card_text"),
        "confirmed_effects": get_confirmed_effects(card["id"]),
    }
