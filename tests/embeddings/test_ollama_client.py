import requests
import pytest

from aijudge.embeddings.ollama_client import DEFAULT_MODEL, OllamaEmbeddingClient


class FakeResponse:
    def __init__(self, json_data: dict, status_code: int = 200):
        self._json_data = json_data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")

    def json(self) -> dict:
        return self._json_data


def test_embed_posts_prompt_to_embeddings_endpoint_and_returns_vector():
    captured = {}
    fake_vector = [0.1, 0.2, 0.3]

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse({"embedding": fake_vector})

    client = OllamaEmbeddingClient(model=DEFAULT_MODEL, base_url="http://localhost:11434", http_post=fake_post)

    result = client.embed("what does Ash Blossom do?")

    assert result == fake_vector
    assert captured["url"] == "http://localhost:11434/api/embeddings"
    assert captured["json"]["model"] == DEFAULT_MODEL
    assert captured["json"]["prompt"] == "what does Ash Blossom do?"


def test_embed_uses_custom_model_when_given():
    captured = {}

    def fake_post(url, json, timeout):
        captured["json"] = json
        return FakeResponse({"embedding": [0.0]})

    client = OllamaEmbeddingClient(model="nomic-embed-text", http_post=fake_post)
    client.embed("text")

    assert captured["json"]["model"] == "nomic-embed-text"


def test_embed_raises_on_http_error():
    def fake_post(url, json, timeout):
        return FakeResponse({}, status_code=500)

    client = OllamaEmbeddingClient(http_post=fake_post)

    with pytest.raises(requests.HTTPError):
        client.embed("text")


def test_embed_defaults_model_and_base_url_from_env(monkeypatch):
    monkeypatch.setenv("OLLAMA_EMBEDDING_MODEL", "custom-embed")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://otherhost:11434")
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse({"embedding": [0.0]})

    client = OllamaEmbeddingClient(http_post=fake_post)
    client.embed("text")

    assert captured["url"] == "http://otherhost:11434/api/embeddings"
    assert captured["json"]["model"] == "custom-embed"


def test_embed_falls_back_to_defaults_when_env_vars_are_set_but_empty(monkeypatch):
    monkeypatch.setenv("OLLAMA_EMBEDDING_MODEL", "")
    monkeypatch.setenv("OLLAMA_BASE_URL", "")
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse({"embedding": [0.0]})

    client = OllamaEmbeddingClient(http_post=fake_post)
    client.embed("text")

    assert captured["url"] == "http://localhost:11434/api/embeddings"
    assert captured["json"]["model"] == DEFAULT_MODEL
