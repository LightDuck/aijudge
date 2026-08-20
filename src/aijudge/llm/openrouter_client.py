from typing import Callable

import requests

API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "meta-llama/llama-3.3-70b-instruct:free"


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

    def complete(self, prompt: str) -> str:
        response = self._http_post(
            API_URL,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
