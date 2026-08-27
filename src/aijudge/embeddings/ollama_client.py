import os
from typing import Callable

import requests
from dotenv import load_dotenv

load_dotenv()

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "all-minilm"


class OllamaEmbeddingClient:
    """EmbeddingClient backed by a local Ollama server — $0 cost, no API key.

    Defaults to `all-minilm`, which natively outputs 384-dim vectors —
    exactly `EMBEDDING_DIM` — so it matches the pgvector schema's
    `VECTOR(384)` columns with no truncation or migration needed.
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 30.0,
        http_post: Callable[..., "requests.Response"] = requests.post,
    ) -> None:
        self.model = model or os.environ.get("OLLAMA_EMBEDDING_MODEL") or DEFAULT_MODEL
        self.base_url = (base_url or os.environ.get("OLLAMA_BASE_URL") or DEFAULT_OLLAMA_BASE_URL).rstrip("/")
        self.timeout = timeout
        self._http_post = http_post

    def embed(self, text: str) -> list[float]:
        response = self._http_post(
            f"{self.base_url}/api/embeddings",
            json={"model": self.model, "prompt": text},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()["embedding"]
