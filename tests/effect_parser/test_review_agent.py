import pytest

from aijudge.effect_parser.review_agent import review_parsed_effect
from aijudge.llm.client import MockLLMClient


def test_confidence_at_or_above_threshold_auto_confirms():
    llm_client = MockLLMClient()
    llm_client.queue_response("0.95")

    result = review_parsed_effect(
        llm_client,
        raw_text="You can target 1 banished monster; banish it.",
        activation_condition=None,
        cost=None,
        targeting="target 1 banished monster",
        effect="banish it.",
    )

    assert result.confidence == 0.95
    assert result.auto_confirmed is True


def test_confidence_below_threshold_does_not_auto_confirm():
    llm_client = MockLLMClient()
    llm_client.queue_response("0.4")

    result = review_parsed_effect(
        llm_client,
        raw_text="banish 1 card from your hand and target 1 face-up monster; negate it.",
        activation_condition=None,
        cost="ambiguous 'and' — could be a second cost or part of the effect",
        targeting="target 1 face-up monster",
        effect="negate it.",
    )

    assert result.confidence == 0.4
    assert result.auto_confirmed is False


def test_custom_threshold_is_respected():
    llm_client = MockLLMClient()
    llm_client.queue_response("0.92")

    result = review_parsed_effect(
        llm_client,
        raw_text="text",
        activation_condition=None,
        cost=None,
        targeting=None,
        effect="text",
        threshold=0.95,
    )

    assert result.auto_confirmed is False


def test_out_of_range_confidence_raises_value_error():
    llm_client = MockLLMClient()
    llm_client.queue_response("95")  # percent instead of fraction

    with pytest.raises(ValueError):
        review_parsed_effect(
            llm_client,
            raw_text="text",
            activation_condition=None,
            cost=None,
            targeting=None,
            effect="text",
        )


def test_damage_step_category_is_included_in_the_review_prompt():
    captured = {}

    class _CapturingLLMClient:
        def complete(self, prompt, *, system=None):
            captured["prompt"] = prompt
            return "0.9"

    review_parsed_effect(
        _CapturingLLMClient(),
        raw_text="its ATK becomes 0.",
        activation_condition=None,
        cost=None,
        targeting=None,
        effect="its ATK becomes 0.",
        damage_step_category="atk_def_alter",
    )

    assert "Damage Step category: atk_def_alter" in captured["prompt"]


def test_review_parsed_effect_includes_other_effects_in_prompt_when_provided():
    captured = {}

    class _CapturingLLMClient:
        def complete(self, prompt, *, system=None):
            captured["prompt"] = prompt
            return "0.9"

    review_parsed_effect(
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


def test_review_parsed_effect_omits_other_effects_section_when_none():
    captured = {}

    class _CapturingLLMClient:
        def complete(self, prompt, *, system=None):
            captured["prompt"] = prompt
            return "0.9"

    review_parsed_effect(
        _CapturingLLMClient(),
        raw_text="Effect A text.",
        activation_condition=None,
        cost=None,
        targeting=None,
        effect="Effect A text.",
    )

    assert "shares a usage-limit restriction" not in captured["prompt"]
