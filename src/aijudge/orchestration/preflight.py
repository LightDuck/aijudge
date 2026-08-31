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
