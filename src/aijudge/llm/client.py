from typing import Protocol


class LLMClient(Protocol):
    def complete(self, prompt: str) -> str: ...


class MockLLMClient:
    """Deterministic fake LLM client for tests and dev without a real provider.

    Each call to `complete` pops the next response off a FIFO queue,
    regardless of the prompt — this keeps tests decoupled from exact
    prompt wording while still letting each call in a multi-step flow
    be scripted independently.
    """

    def __init__(self) -> None:
        self._queue: list[str] = []

    def queue_response(self, response: str) -> None:
        self._queue.append(response)

    def complete(self, prompt: str) -> str:
        if not self._queue:
            raise AssertionError("MockLLMClient.complete called with no queued response")
        return self._queue.pop(0)
