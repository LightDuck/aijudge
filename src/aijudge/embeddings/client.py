import hashlib
from typing import Protocol

EMBEDDING_DIM = 384


class EmbeddingClient(Protocol):
    def embed(self, text: str) -> list[float]: ...


class MockEmbeddingClient:
    """Deterministic fake embedding client for tests and dev without a real provider."""

    def embed(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [digest[i % len(digest)] / 255 for i in range(EMBEDDING_DIM)]
