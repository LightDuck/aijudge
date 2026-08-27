import os
import re
from typing import Callable, Protocol

import requests
from dotenv import load_dotenv

load_dotenv()

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "qwen3:8b"

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


class LLMClient(Protocol):
    def complete(self, prompt: str, *, system: str | None = None) -> str: ...


class MockLLMClient:
    """Deterministic fake LLM client for tests and dev without a real provider.

    Each call to `complete` pops the next response off a FIFO queue,
    regardless of the prompt — this keeps tests decoupled from exact
    prompt wording while still letting each call in a multi-step flow
    be scripted independently. Each call's `system` argument is recorded
    in `system_prompts`, in order, so callers can assert on it.
    """

    def __init__(self) -> None:
        self._queue: list[str] = []
        self.system_prompts: list[str | None] = []

    def queue_response(self, response: str) -> None:
        self._queue.append(response)

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        self.system_prompts.append(system)
        if not self._queue:
            raise AssertionError("MockLLMClient.complete called with no queued response")
        return self._queue.pop(0)


class OllamaLLMClient:
    """LLMClient backed by a local Ollama server running Qwen3-8B — $0 cost, no API key.

    When `system` is given, posts to `/api/chat` with a proper system/user role
    split so the model weights instructions (e.g. "you are a Yu-Gi-Oh! rules
    assistant") more reliably than if they were flattened into one prompt string.
    Without `system`, falls back to `/api/generate` with a single flat prompt --
    used by callers like `review_agent` that don't need role separation.

    Thinking mode is disabled by default (`think: false`) so `complete()` returns a
    plain response suitable for callers like `review_agent` that parse it directly
    (e.g. `float(response)`). Any `<think>...</think>` block is stripped defensively
    in case a model/server combination emits one anyway.
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        base_url: str | None = None,
        think: bool = False,
        timeout: float = 120.0,
        http_post: Callable[..., "requests.Response"] = requests.post,
    ) -> None:
        self.model = model or os.environ.get("OLLAMA_MODEL") or DEFAULT_OLLAMA_MODEL
        self.base_url = (base_url or os.environ.get("OLLAMA_BASE_URL") or DEFAULT_OLLAMA_BASE_URL).rstrip("/")
        self.think = think
        self.timeout = timeout
        self._http_post = http_post

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        if system is not None:
            response = self._http_post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "think": self.think,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            return self._clean(response.json()["message"]["content"])

        response = self._http_post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "think": self.think,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return self._clean(response.json()["response"])

    @staticmethod
    def _clean(text: str) -> str:
        return _THINK_BLOCK_RE.sub("", text).strip()
