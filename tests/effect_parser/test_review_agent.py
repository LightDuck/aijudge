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
