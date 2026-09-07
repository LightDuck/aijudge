from aijudge.llm.client import MockLLMClient
from aijudge.orchestration.confidence import SignalState
from aijudge.orchestration.verify import (
    VerificationResult,
    build_verification_prompt,
    parse_verification_response,
    verify_structured_grounding,
)


def test_build_verification_prompt_includes_effect_text_and_answer():
    prompt = build_verification_prompt(
        "It negates the effect of a spell or trap card.",
        [{"effect": "Target 1 Effect Monster your opponent controls; negate its effects."}],
    )
    assert "Target 1 Effect Monster your opponent controls; negate its effects." in prompt
    assert "It negates the effect of a spell or trap card." in prompt


def test_parse_verification_response_accepts_yes_variants():
    assert parse_verification_response("YES") is True
    assert parse_verification_response("yes") is True
    assert parse_verification_response("  Yes  ") is True


def test_parse_verification_response_rejects_anything_else():
    assert parse_verification_response("NO") is False
    assert parse_verification_response("") is False
    assert parse_verification_response("I think so") is False


def test_verify_structured_grounding_skips_when_nothing_to_check():
    llm = MockLLMClient()  # empty queue -- would raise AssertionError if complete() were called
    state = SignalState()

    result = verify_structured_grounding("Some answer.", {"card:abc"}, state, llm)

    assert result == VerificationResult(ok=True, mismatches=[])


def test_verify_structured_grounding_passes_on_yes():
    llm = MockLLMClient()
    llm.queue_response("YES")
    state = SignalState()
    state.structured_effects["card:abc"] = [{"effect": "Target 1 Effect Monster; negate its effects."}]

    result = verify_structured_grounding("It negates a targeted Effect Monster.", {"card:abc"}, state, llm)

    assert result.ok is True
    assert result.mismatches == []


def test_verify_structured_grounding_flags_mismatch_on_no():
    llm = MockLLMClient()
    llm.queue_response("NO")
    state = SignalState()
    state.structured_effects["card:abc"] = [{"effect": "Target 1 Effect Monster; negate its effects."}]

    result = verify_structured_grounding("It negates a targeted spell or trap card.", {"card:abc"}, state, llm)

    assert result.ok is False
    assert result.mismatches == [
        {"card_id": "card:abc", "effect_text": "Target 1 Effect Monster; negate its effects."}
    ]


def test_verify_structured_grounding_dedupes_id_and_passcode_alias_for_same_card():
    # card:abc and card:32896829 are the SAME card cited under two aliases --
    # state.structured_effects stores the identical list object under both
    # keys (see Task 1), so this must not double-count into two LLM calls
    # or two mismatch entries.
    llm = MockLLMClient()
    llm.queue_response("YES")
    state = SignalState()
    effects = [{"effect": "Target 1 Effect Monster; negate its effects."}]
    state.structured_effects["card:abc"] = effects
    state.structured_effects["card:32896829"] = effects

    result = verify_structured_grounding("Answer.", {"card:abc", "card:32896829"}, state, llm)

    assert result.ok is True


def test_verify_structured_grounding_uses_the_verifier_system_prompt():
    from aijudge.orchestration.verify import VERIFIER_SYSTEM_PROMPT

    llm = MockLLMClient()
    llm.queue_response("YES")
    state = SignalState()
    state.structured_effects["card:abc"] = [{"effect": "..."}]

    verify_structured_grounding("Answer.", {"card:abc"}, state, llm)

    assert llm.system_prompts == [VERIFIER_SYSTEM_PROMPT]
