import json

import pytest

from aijudge.call_log import CallLogger, LoggingLLMClient
from aijudge.effect_parser.review_agent import ReviewResult, _review_parsed_effect_via_llm, review_parsed_effect
from aijudge.llm.client import MockLLMClient


def test_review_parsed_effect_is_disabled_and_makes_no_llm_call():
    # Temporarily disabled (pipeline instability): review_parsed_effect
    # always returns a default ReviewResult, regardless of what's queued --
    # in fact nothing is queued here, so any LLM call would raise
    # (MockLLMClient's empty-queue AssertionError).
    llm_client = MockLLMClient()

    result = review_parsed_effect(
        llm_client,
        raw_text="You can target 1 banished monster; banish it.",
        activation_condition=None,
        cost=None,
        targeting="target 1 banished monster",
        effect="banish it.",
    )

    assert result == ReviewResult(confidence=1.0, auto_confirmed=True)


def test_review_parsed_effect_ignores_a_queued_low_score_it_never_reads():
    # A queued response is irrelevant -- the disabled public function never
    # reads the queue at all, so even a deliberately low score is ignored.
    llm_client = MockLLMClient()
    llm_client.queue_response("0.1")

    result = review_parsed_effect(
        llm_client,
        raw_text="text",
        activation_condition=None,
        cost=None,
        targeting=None,
        effect="text",
    )

    assert result.confidence == 1.0
    assert result.auto_confirmed is True


def test_review_parsed_effect_via_llm_tags_its_llm_call_with_review_agent_site(tmp_path):
    log_path = tmp_path / "aijudge.jsonl"
    call_logger = CallLogger(str(log_path))
    inner = MockLLMClient()
    inner.queue_response("0.95")
    wrapped = LoggingLLMClient(inner, call_logger)

    _review_parsed_effect_via_llm(
        wrapped,
        raw_text="You can target 1 banished monster; banish it.",
        activation_condition=None,
        cost=None,
        targeting="target 1 banished monster",
        effect="banish it.",
    )

    with open(log_path, encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    assert records[0]["site"] == "review_agent"


def test_review_parsed_effect_via_llm_confidence_at_or_above_threshold_auto_confirms():
    llm_client = MockLLMClient()
    llm_client.queue_response("0.95")

    result = _review_parsed_effect_via_llm(
        llm_client,
        raw_text="You can target 1 banished monster; banish it.",
        activation_condition=None,
        cost=None,
        targeting="target 1 banished monster",
        effect="banish it.",
    )

    assert result.confidence == 0.95
    assert result.auto_confirmed is True


def test_review_parsed_effect_via_llm_confidence_below_threshold_does_not_auto_confirm():
    llm_client = MockLLMClient()
    llm_client.queue_response("0.4")

    result = _review_parsed_effect_via_llm(
        llm_client,
        raw_text="banish 1 card from your hand and target 1 face-up monster; negate it.",
        activation_condition=None,
        cost="ambiguous 'and' — could be a second cost or part of the effect",
        targeting="target 1 face-up monster",
        effect="negate it.",
    )

    assert result.confidence == 0.4
    assert result.auto_confirmed is False


def test_review_parsed_effect_via_llm_custom_threshold_is_respected():
    llm_client = MockLLMClient()
    llm_client.queue_response("0.92")

    result = _review_parsed_effect_via_llm(
        llm_client,
        raw_text="text",
        activation_condition=None,
        cost=None,
        targeting=None,
        effect="text",
        threshold=0.95,
    )

    assert result.auto_confirmed is False


def test_review_parsed_effect_via_llm_out_of_range_confidence_raises_value_error():
    llm_client = MockLLMClient()
    llm_client.queue_response("95")  # percent instead of fraction

    with pytest.raises(ValueError):
        _review_parsed_effect_via_llm(
            llm_client,
            raw_text="text",
            activation_condition=None,
            cost=None,
            targeting=None,
            effect="text",
        )


def test_review_parsed_effect_via_llm_damage_step_category_is_included_in_the_prompt():
    captured = {}

    class _CapturingLLMClient:
        def complete(self, prompt, *, system=None):
            captured["prompt"] = prompt
            return "0.9"

    _review_parsed_effect_via_llm(
        _CapturingLLMClient(),
        raw_text="its ATK becomes 0.",
        activation_condition=None,
        cost=None,
        targeting=None,
        effect="its ATK becomes 0.",
        damage_step_category="atk_def_alter",
    )

    assert "Damage Step category: atk_def_alter" in captured["prompt"]


def test_review_parsed_effect_via_llm_includes_other_effects_in_prompt_when_provided():
    captured = {}

    class _CapturingLLMClient:
        def complete(self, prompt, *, system=None):
            captured["prompt"] = prompt
            return "0.9"

    _review_parsed_effect_via_llm(
        _CapturingLLMClient(),
        raw_text="Effect A text.",
        activation_condition=None,
        cost=None,
        targeting=None,
        effect="Effect A text.",
        other_effects=["Effect B text."],
    )

    assert "Effect B text." in captured["prompt"]
    assert "shares a usage-limit restriction" in captured["prompt"]


def test_review_parsed_effect_via_llm_omits_other_effects_section_when_none():
    captured = {}

    class _CapturingLLMClient:
        def complete(self, prompt, *, system=None):
            captured["prompt"] = prompt
            return "0.9"

    _review_parsed_effect_via_llm(
        _CapturingLLMClient(),
        raw_text="Effect A text.",
        activation_condition=None,
        cost=None,
        targeting=None,
        effect="Effect A text.",
    )

    assert "shares a usage-limit restriction" not in captured["prompt"]
