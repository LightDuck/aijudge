from aijudge.embeddings.client import EMBEDDING_DIM
from aijudge.embeddings.openai_client import API_URL, DEFAULT_MODEL, OpenAIEmbeddingClient


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_embed_posts_text_and_returns_embedding_vector():
    captured = {}
    fake_vector = [0.1, 0.2, 0.3]

    def fake_post(url, *, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse(200, {"data": [{"embedding": fake_vector}]})

    client = OpenAIEmbeddingClient("test-key", http_post=fake_post)
    result = client.embed("what does Ash Blossom do?")

    assert result == fake_vector
    assert captured["url"] == API_URL
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["json"]["model"] == DEFAULT_MODEL
    assert captured["json"]["input"] == "what does Ash Blossom do?"
    assert captured["json"]["dimensions"] == EMBEDDING_DIM
    assert captured["timeout"] == 30


def test_embed_uses_custom_model_when_given():
    captured = {}

    def fake_post(url, *, headers, json, timeout):
        captured["json"] = json
        return FakeResponse(200, {"data": [{"embedding": [0.0]}]})

    client = OpenAIEmbeddingClient("test-key", model="text-embedding-3-large", http_post=fake_post)
    client.embed("text")

    assert captured["json"]["model"] == "text-embedding-3-large"


def test_embed_raises_on_http_error():
    def fake_post(url, *, headers, json, timeout):
        return FakeResponse(401, {})

    client = OpenAIEmbeddingClient("bad-key", http_post=fake_post)
    try:
        client.embed("text")
        assert False, "expected an error"
    except RuntimeError:
        pass
