from dataclasses import dataclass

from aijudge.llm.client import LLMClient

DEFAULT_CONFIDENCE_THRESHOLD = 0.9


@dataclass
class ReviewResult:
    confidence: float
    auto_confirmed: bool


def review_parsed_effect(
    llm_client: LLMClient,
    *,
    raw_text: str,
    activation_condition: str | None,
    cost: str | None,
    targeting: str | None,
    effect: str,
    damage_step_category: str | None = None,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> ReviewResult:
    prompt = (
        "Score how accurately this structured breakdown captures the raw "
        "card text, from 0.0 to 1.0. Respond with only the number.\n\n"
        f"Raw text: {raw_text}\n\n"
        f"Activation condition: {activation_condition}\n"
        f"Cost: {cost}\n"
        f"Targeting: {targeting}\n"
        f"Effect: {effect}\n"
        f"Damage Step category: {damage_step_category}"
    )
    response = llm_client.complete(prompt)
    confidence = float(response)
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"confidence must be between 0.0 and 1.0, got {confidence!r} (raw response: {response!r})")
    return ReviewResult(confidence=confidence, auto_confirmed=confidence >= threshold)
