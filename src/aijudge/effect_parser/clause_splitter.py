from aijudge.effect_parser.review_agent import DEFAULT_CONFIDENCE_THRESHOLD
from aijudge.effect_parser.sentence_splitter import split_sentences
from aijudge.effect_parser.usage_limit import UsageLimitScope, resolve_usage_limit_scopes
from aijudge.llm.client import LLMClient

_SPLIT_REVIEW_PROMPT_TEMPLATE = (
    "The following is the raw rules text of a Yu-Gi-Oh! Trading Card Game card, followed by "
    "a proposed split of that text into separate, independently-activatable effects. Score "
    "how correctly the split identifies genuinely separate effects -- as opposed to "
    "incorrectly splitting one effect into pieces, or merging two effects into one -- from "
    "0.0 to 1.0. Respond with only the number.\n\n"
    "Card text:\n{card_text}\n\n"
    "Proposed effects:\n{numbered_effects}"
)


def score_split_confidence(llm_client: LLMClient, *, card_text: str, effect_texts: list[str]) -> float:
    numbered_effects = "\n".join(f"{i}. {text}" for i, text in enumerate(effect_texts, start=1))
    prompt = _SPLIT_REVIEW_PROMPT_TEMPLATE.format(card_text=card_text, numbered_effects=numbered_effects)
    response = llm_client.complete(prompt)
    confidence = float(response)
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"confidence must be between 0.0 and 1.0, got {confidence!r} (raw response: {response!r})")
    return confidence


def resolve_effect_clauses(
    llm_client: LLMClient, card_text: str, *, threshold: float = DEFAULT_CONFIDENCE_THRESHOLD
) -> tuple[list[str], list[UsageLimitScope]]:
    """Deterministically segment `card_text` (already stripped of any Card
    Material line by the caller) into effect clauses, resolving usage-limit
    scope, then verify the resulting grouping via one LLM confidence call --
    replacing what used to be an LLM-driven split. See design spec sections
    3-5."""
    sentences = split_sentences(card_text)
    if not sentences:
        return [], []

    clauses, scopes = resolve_usage_limit_scopes(sentences)
    if len(clauses) <= 1:
        return clauses, scopes

    confidence = score_split_confidence(llm_client, card_text=card_text, effect_texts=clauses)
    if confidence < threshold:
        return [card_text], []
    return clauses, scopes
