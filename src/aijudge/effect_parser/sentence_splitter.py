import re

# A sentence boundary is a period followed by whitespace and the start of
# the next sentence -- a capital letter, or an opening quote around a
# quoted card name. The whitespace itself is consumed by the split (and
# each part is stripped), matching the existing project convention of
# normalizing whitespace rather than preserving it verbatim (see
# clause_splitter._normalize, which this replaces the LLM-facing half of).
_SENTENCE_BOUNDARY = re.compile(r'(?<=[.])\s+(?=[A-Z"])')

_EXTRA_DECK_TYPE_MARKERS = ("fusion", "synchro", "xyz", "link")


def split_sentences(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    return [part.strip() for part in _SENTENCE_BOUNDARY.split(text) if part.strip()]


def extract_card_material(card_text: str, *, card_type: str) -> tuple[str | None, str]:
    """For Fusion/Synchro/Xyz/Link monsters, split the materials line (the
    first line of card_text) from the rest. Matching is case-insensitive --
    YGOPRODeck's real `type` field renders Xyz monsters as "XYZ Monster"
    (all-caps), not "Xyz Monster".

    Returns (None, card_text) for every other card_type: no material line
    to extract. For an Extra Deck monster whose entire text *is* the
    materials line (a vanilla monster with no effect at all -- see
    Gem-Knight Pearl), remainder is "".
    """
    lowered_type = card_type.lower()
    if not any(marker in lowered_type for marker in _EXTRA_DECK_TYPE_MARKERS):
        return None, card_text

    normalized = card_text.replace("\r\n", "\n")
    lines = normalized.split("\n", 1)
    material = lines[0].strip()
    remainder = lines[1].strip() if len(lines) > 1 else ""
    return material, remainder
