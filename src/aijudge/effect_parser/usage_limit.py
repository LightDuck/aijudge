import re
from dataclasses import dataclass, field

_IS_USAGE_LIMIT_SENTENCE = re.compile(r"\byou can only\b", re.IGNORECASE)
_CONTAINS_EFFECT_WORD = re.compile(r"\beffects?\b", re.IGNORECASE)
_POSITIONAL_DIRECTION = re.compile(r"\b(preceding|following)\b", re.IGNORECASE)
_POSITIONAL_SINGULAR = re.compile(r"\b(?:preceding|following) effect\b(?!s)", re.IGNORECASE)
_VERB_WIDTH = re.compile(r"\byou can only (activate|use)\b", re.IGNORECASE)


@dataclass
class UsageLimitScope:
    text: str
    applies_to: list[int] = field(default_factory=list)
    ambiguous: bool = False


def extract_verb_width(sentence: str) -> str | None:
    match = _VERB_WIDTH.search(sentence)
    if not match:
        return None
    return "narrow" if match.group(1).lower() == "activate" else "broad"


def resolve_usage_limit_scopes(sentences: list[str]) -> tuple[list[str], list[UsageLimitScope]]:
    """Split `sentences` into (clause candidates, usage-limit scopes).

    A sentence containing "you can only" is never a clause candidate
    itself -- it's a restriction that scopes to some subset of the
    *other* sentences, resolved by `_resolve_scope` below.
    """
    clauses: list[str] = []
    usage_limit_sentences: list[tuple[str, int]] = []  # (sentence, insertion_point)

    for sentence in sentences:
        if _IS_USAGE_LIMIT_SENTENCE.search(sentence):
            usage_limit_sentences.append((sentence, len(clauses)))
        else:
            clauses.append(sentence)

    scopes = []
    for sentence, insertion_point in usage_limit_sentences:
        num_following = len(clauses) - insertion_point
        applies_to, ambiguous = _resolve_scope(sentence, insertion_point, num_following)
        scopes.append(UsageLimitScope(text=sentence, applies_to=applies_to, ambiguous=ambiguous))

    return clauses, scopes


def _resolve_scope(sentence: str, insertion_point: int, num_following: int) -> tuple[list[int], bool]:
    direction_match = _POSITIONAL_DIRECTION.search(sentence)
    if direction_match:
        direction = direction_match.group(1).lower()
        singular = bool(_POSITIONAL_SINGULAR.search(sentence))
        return _positional_indices(direction, singular, insertion_point, num_following), False

    if not _CONTAINS_EFFECT_WORD.search(sentence):
        # A named-card restriction with no "effect" wording at all (e.g.
        # "You can only activate 1 'Card Name' per turn.") restricts the
        # card by name/copies, not by clause position -- not clause-scoped.
        return [], False

    if "these effects" in sentence.lower():
        # No positional pointer to resolve the set against -- genuinely
        # ambiguous, escalates to LLM concurrence (see resolve_ambiguous_scope).
        return [], True

    # Self-scoped: "this effect" or no reference at all -- attaches to the
    # one clause this sentence trails.
    if insertion_point > 0:
        return [insertion_point - 1], False
    return [], False


def _positional_indices(direction: str, singular: bool, insertion_point: int, num_following: int) -> list[int]:
    if direction == "preceding":
        if singular:
            return [insertion_point - 1] if insertion_point > 0 else []
        return list(range(0, insertion_point))
    # direction == "following"
    if singular:
        return [insertion_point] if num_following > 0 else []
    return list(range(insertion_point, insertion_point + num_following))
