from dataclasses import dataclass

from aijudge.call_log import call_site
from aijudge.llm.client import LLMClient

DEFAULT_CONFIDENCE_THRESHOLD = 0.75


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
    other_effects: list[str] | None = None,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> ReviewResult:
    """Temporarily disabled (pipeline instability): makes zero LLM calls and
    always returns a default ReviewResult with auto_confirmed=True, so
    seed.py's confirm/pending decision always confirms. The real
    implementation is preserved, unused, in _review_parsed_effect_via_llm --
    restore this function's body to call it (passing through all the same
    arguments) to re-enable real scoring."""
    return ReviewResult(confidence=1.0, auto_confirmed=True)


def _review_parsed_effect_via_llm(
    llm_client: LLMClient,
    *,
    raw_text: str,
    activation_condition: str | None,
    cost: str | None,
    targeting: str | None,
    effect: str,
    damage_step_category: str | None = None,
    other_effects: list[str] | None = None,
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
    if other_effects:
        numbered = "\n".join(f"{i}. {text}" for i, text in enumerate(other_effects, start=1))
        prompt += (
            "\n\nThis effect shares a usage-limit restriction with other effects on "
            "the same card. Verify the restriction's scope is consistent across all "
            "of them. Other effects on this card:\n" + numbered
        )
    with call_site("review_agent"):
        response = llm_client.complete(prompt)
    confidence = float(response)
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"confidence must be between 0.0 and 1.0, got {confidence!r} (raw response: {response!r})")
    return ReviewResult(confidence=confidence, auto_confirmed=confidence >= threshold)
