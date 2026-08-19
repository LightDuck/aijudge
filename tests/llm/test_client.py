import pytest

from aijudge.llm.client import MockLLMClient


def test_complete_returns_the_next_queued_response():
    client = MockLLMClient()
    client.queue_response("first")
    client.queue_response("second")

    assert client.complete("any prompt") == "first"
    assert client.complete("any prompt") == "second"


def test_complete_raises_when_queue_is_empty():
    client = MockLLMClient()
    with pytest.raises(AssertionError):
        client.complete("any prompt")
