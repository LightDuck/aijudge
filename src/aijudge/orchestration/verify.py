from dataclasses import dataclass, field

from aijudge.llm.client import LLMClient

from .confidence import SignalState

VERIFIER_SYSTEM_PROMPT = (
    "You are a strict fact-checker for a Yu-Gi-Oh! TCG rules assistant. You "
    "are given the verbatim stored text of one or more card effects and a "
    "drafted answer that describes them. Check whether the drafted answer "
    "accurately restates each effect -- the same targets, the same actions, "
    "nothing invented or swapped for something else. Respond with exactly "
    "one word: YES if the answer is accurate, NO if it misstates any of the "
    "effects."
)


@dataclass
class VerificationResult:
    ok: bool
    mismatches: list[dict] = field(default_factory=list)


def build_verification_prompt(answer_text: str, structured_effects: list[dict]) -> str:
    effect_lines = "\n".join(f"- {effect['effect']}" for effect in structured_effects)
    return (
        "STORED EFFECT TEXT (verbatim, ground truth):\n"
        f"{effect_lines}\n\n"
        "DRAFTED ANSWER:\n"
        f"{answer_text}\n\n"
        "Does the drafted answer accurately restate the stored effect text above? "
        "Respond with exactly YES or NO."
    )


def parse_verification_response(response: str) -> bool:
    return response.strip().upper() == "YES"


def verify_structured_grounding(
    answer_text: str,
    cited_ids: set[str],
    state: SignalState,
    llm_client: LLMClient,
) -> VerificationResult:
    # Dedupe by list identity, not by cited id or effect text: the same card
    # cited under both its internal id and passcode alias points to the same
    # `confirmed_effects` list object (see Task 1), and must be counted once.
    # Two different cards that happen to share identical effect text must
    # NOT be collapsed, so identity (not text equality) is the dedup key.
    seen_list_ids: set[int] = set()
    matched: list[dict] = []
    for cited_id in cited_ids:
        effects = state.structured_effects.get(cited_id)
        if not effects or id(effects) in seen_list_ids:
            continue
        seen_list_ids.add(id(effects))
        for effect in effects:
            matched.append({"card_id": cited_id, "effect_text": effect["effect"]})

    if not matched:
        return VerificationResult(ok=True)

    prompt = build_verification_prompt(
        answer_text, [{"effect": m["effect_text"]} for m in matched]
    )
    response = llm_client.complete(prompt, system=VERIFIER_SYSTEM_PROMPT)
    ok = parse_verification_response(response)
    return VerificationResult(ok=ok, mismatches=[] if ok else matched)
