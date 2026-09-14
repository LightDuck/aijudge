from typing import Any

import anthropic

DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_MAX_TOKENS = 16000


class AnthropicLLMClient:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        *,
        client: Any = None,
    ) -> None:
        self._model = model
        self._client = client if client is not None else anthropic.Anthropic(api_key=api_key)

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        kwargs: dict[str, Any] = {}
        if system is not None:
            kwargs["system"] = system

        response = self._client.messages.create(
            model=self._model,
            max_tokens=DEFAULT_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        )
        for block in response.content:
            if block.type == "text":
                return block.text
        return ""
