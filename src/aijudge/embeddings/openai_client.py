from typing import Callable

import requests

from .client import EMBEDDING_DIM

API_URL = "https://api.openai.com/v1/embeddings"
DEFAULT_MODEL = "text-embedding-3-small"


class OpenAIEmbeddingClient:
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

    def embed(self, text: str) -> list[float]:
        response = self._http_post(
            API_URL,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self._model,
                "input": text,
                "dimensions": EMBEDDING_DIM,
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()["data"][0]["embedding"]
