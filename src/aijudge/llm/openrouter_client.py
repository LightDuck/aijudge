from typing import Callable

import requests

API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"


class OpenRouterLLMClient:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        *,
        http_post: Callable[..., "requests.Response"] = requests.post,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._http_post = http_post

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        messages = []
        if system is not None:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = self._http_post(
            API_URL,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self._model,
                "messages": messages,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise RuntimeError(f"OpenRouter error: {payload['error'].get('message', payload['error'])}")
        content = payload["choices"][0]["message"]["content"]
        return content or ""
