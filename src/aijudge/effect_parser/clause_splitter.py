from aijudge.effect_parser.review_agent import DEFAULT_CONFIDENCE_THRESHOLD
from aijudge.effect_parser.sentence_splitter import split_sentences
from aijudge.effect_parser.usage_limit import UsageLimitScope, resolve_usage_limit_scopes
from aijudge.llm.client import LLMClient

_SPLIT_REVIEW_PROMPT_TEMPLATE = (
    "The following is the raw rules text of a Yu-Gi-Oh! Trading Card Game card, followed by "
    "a proposed split of that text into separate, independently-activatable effects. Score "
    "how correctly the split identifies genuinely separate effects -- as opposed to "
    "incorrectly splitting one effect into pieces, or merging two effects into one -- from "
    "0.0 to 1.0. Respond with only the number. A \"You can only activate/use ... per turn\" "
    "usage-limit restriction sentence, if present in the card text, is deliberately excluded "
    "from the numbered list below -- it's tracked separately from the effect split, not as "
    "its own clause -- so its absence from the list is not itself a sign of an incomplete or "
    "incorrect split.\n\n"
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
    scope. See design spec sections 3-5.

    The LLM confidence check (score_split_confidence, step 5 of the pipeline
    review) is temporarily disabled -- for now, every deterministic split of
    2+ clauses is accepted unconditionally (equivalent to a hardcoded
    confidence of 1.0), so the rest of the pipeline can be verified
    independent of that scoring step. `threshold` is unused while this is
    disabled; re-enable by restoring the score_split_confidence call below.
    """
    sentences = split_sentences(card_text)
    if not sentences:
        return [], []

    clauses, scopes = resolve_usage_limit_scopes(sentences)
    return clauses, scopes
