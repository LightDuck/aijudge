import re
from dataclasses import dataclass, field

from aijudge.llm.client import LLMClient

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


_AMBIGUOUS_SCOPE_PROMPT_TEMPLATE = (
    "The following restriction sentence was found on a Yu-Gi-Oh! card, but which "
    "of the card's effects it applies to is not stated by position (no "
    "'preceding'/'following' pointer). Read the card's effects and decide which "
    "ones (by number) the restriction applies to. Respond with only a "
    "comma-separated list of numbers (e.g. '1,2'), or 'all' if it applies to "
    "every effect listed.\n\n"
    "Restriction: {usage_limit_text}\n\n"
    "Card's effects:\n{numbered_effects}"
)


def resolve_ambiguous_scope(llm_client: LLMClient, *, usage_limit_text: str, clauses: list[str]) -> list[int]:
    numbered_effects = "\n".join(f"{i}. {text}" for i, text in enumerate(clauses, start=1))
    prompt = _AMBIGUOUS_SCOPE_PROMPT_TEMPLATE.format(
        usage_limit_text=usage_limit_text, numbered_effects=numbered_effects
    )
    response = llm_client.complete(prompt).strip()
    if response.lower() == "all":
        return list(range(len(clauses)))
    return [int(token.strip()) - 1 for token in response.split(",") if token.strip()]
