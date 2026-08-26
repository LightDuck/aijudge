import requests
import pytest

from aijudge.llm.client import MockLLMClient, OllamaLLMClient


def test_complete_returns_the_next_queued_response():
    client = MockLLMClient()
    client.queue_response("first")
    client.queue_response("second")

    assert client.complete("any prompt") == "first"
    assert client.complete("any prompt") == "second"


def test_complete_raises_when_queue_is_empty():
    client = MockLLMClient()
    with pytest.raises(AssertionError):
        client.complete("any prompt")


class FakeResponse:
    def __init__(self, json_data: dict, status_code: int = 200):
        self._json_data = json_data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")

    def json(self) -> dict:
        return self._json_data


def test_ollama_client_posts_prompt_to_generate_endpoint_and_returns_response_text():
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse({"response": "0.95"})

    client = OllamaLLMClient(model="qwen3:8b", base_url="http://localhost:11434", http_post=fake_post)

    result = client.complete("Score this from 0.0 to 1.0")

    assert result == "0.95"
    assert captured["url"] == "http://localhost:11434/api/generate"
    assert captured["json"]["model"] == "qwen3:8b"
    assert captured["json"]["prompt"] == "Score this from 0.0 to 1.0"
    assert captured["json"]["stream"] is False


def test_ollama_client_strips_thinking_blocks_from_response():
    def fake_post(url, json, timeout):
        return FakeResponse({"response": "<think>let me reason about this</think>\n0.95"})

    client = OllamaLLMClient(http_post=fake_post)

    assert client.complete("prompt") == "0.95"


def test_ollama_client_disables_thinking_mode_by_default():
    captured = {}

    def fake_post(url, json, timeout):
        captured["json"] = json
        return FakeResponse({"response": "0.95"})

    client = OllamaLLMClient(http_post=fake_post)
    client.complete("prompt")

    assert captured["json"]["think"] is False


def test_ollama_client_raises_on_http_error():
    def fake_post(url, json, timeout):
        return FakeResponse({}, status_code=500)

    client = OllamaLLMClient(http_post=fake_post)

    with pytest.raises(requests.HTTPError):
        client.complete("prompt")


def test_ollama_client_defaults_model_and_base_url_from_env(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b-custom")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://otherhost:11434")
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse({"response": "ok"})

    client = OllamaLLMClient(http_post=fake_post)
    client.complete("prompt")

    assert captured["url"] == "http://otherhost:11434/api/generate"
    assert captured["json"]["model"] == "qwen3:8b-custom"


def test_ollama_client_falls_back_to_defaults_when_env_vars_are_set_but_empty(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "")
    monkeypatch.setenv("OLLAMA_BASE_URL", "")
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse({"response": "ok"})

    client = OllamaLLMClient(http_post=fake_post)
    client.complete("prompt")

    assert captured["url"] == "http://localhost:11434/api/generate"
    assert captured["json"]["model"] == "qwen3:8b"
