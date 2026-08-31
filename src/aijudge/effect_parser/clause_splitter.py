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
