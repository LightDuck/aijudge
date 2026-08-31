from aijudge.effect_parser.review_agent import DEFAULT_CONFIDENCE_THRESHOLD
from aijudge.llm.client import LLMClient

_SPLIT_PROMPT_TEMPLATE = (
    "The following is the raw rules text of a Yu-Gi-Oh! Trading Card Game card. "
    "Identify its distinct, independently-activatable effects.\n\n"
    "Rules:\n"
    "- A trailing sentence that only states a usage limit (e.g. 'You can only use this "
    "effect... once per turn.') is NOT its own effect -- keep it attached to the effect "
    "it restricts.\n"
    "- A sentence that only modifies, restricts, or grants an alternate activation method "
    "for an effect already stated (such as an exception allowing activation from the hand) "
    "is NOT its own effect -- keep it attached to that effect.\n"
    "- A bulleted or enumerated list that only clarifies or elaborates a condition, cost, or "
    "effect already stated in the same sentence is NOT a separate effect -- keep it attached "
    "to that sentence.\n"
    "- If the card has only one effect, return the entire text unchanged.\n"
    "- Do not paraphrase, reword, or summarize. Every returned effect must be an exact "
    "verbatim excerpt of the original text.\n\n"
    "Separate each returned effect with a line containing exactly: ---\n\n"
    "Card text:\n{card_text}"
)


def split_effect_clauses(llm_client: LLMClient, card_text: str) -> list[str]:
    prompt = _SPLIT_PROMPT_TEMPLATE.format(card_text=card_text)
    response = llm_client.complete(prompt)
    candidates = [part.strip() for part in response.split("---")]
    candidates = [part for part in candidates if part]
    if candidates and _reconstructs(candidates, card_text):
        return candidates
    return [card_text]


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _reconstructs(candidates: list[str], card_text: str) -> bool:
    return _normalize(" ".join(candidates)) == _normalize(card_text)


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
) -> list[str]:
    candidates = split_effect_clauses(llm_client, card_text)
    if len(candidates) <= 1:
        return candidates
    confidence = score_split_confidence(llm_client, card_text=card_text, effect_texts=candidates)
    if confidence < threshold:
        return [card_text]
    return candidates
