from aijudge.llm.openrouter_client import API_URL, DEFAULT_MODEL, OpenRouterLLMClient


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_complete_posts_prompt_and_returns_message_content():
    captured = {}

    def fake_post(url, *, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse(200, {"choices": [{"message": {"content": "the answer"}}]})

    client = OpenRouterLLMClient("test-key", http_post=fake_post)
    result = client.complete("what is Ash Blossom's timing?")

    assert result == "the answer"
    assert captured["url"] == API_URL
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["json"]["model"] == DEFAULT_MODEL
    assert captured["json"]["messages"] == [
        {"role": "user", "content": "what is Ash Blossom's timing?"}
    ]
    assert captured["timeout"] == 30


def test_complete_uses_custom_model_when_given():
    captured = {}

    def fake_post(url, *, headers, json, timeout):
        captured["json"] = json
        return FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]})

    client = OpenRouterLLMClient("test-key", model="some/other-model:free", http_post=fake_post)
    client.complete("question")

    assert captured["json"]["model"] == "some/other-model:free"


def test_complete_returns_empty_string_when_content_is_null():
    def fake_post(url, *, headers, json, timeout):
        return FakeResponse(200, {"choices": [{"message": {"content": None}}]})

    client = OpenRouterLLMClient("test-key", http_post=fake_post)
    result = client.complete("question")

    assert result == ""


def test_complete_includes_system_message_before_user_message_when_given():
    captured = {}

    def fake_post(url, *, headers, json, timeout):
        captured["json"] = json
        return FakeResponse(200, {"choices": [{"message": {"content": "the answer"}}]})

    client = OpenRouterLLMClient("test-key", http_post=fake_post)
    client.complete("what is Ash Blossom's timing?", system="You are a Yu-Gi-Oh! rules assistant.")

    assert captured["json"]["messages"] == [
        {"role": "system", "content": "You are a Yu-Gi-Oh! rules assistant."},
        {"role": "user", "content": "what is Ash Blossom's timing?"},
    ]


def test_complete_raises_on_http_error():
    def fake_post(url, *, headers, json, timeout):
        return FakeResponse(401, {})

    client = OpenRouterLLMClient("bad-key", http_post=fake_post)
    try:
        client.complete("question")
        assert False, "expected an error"
    except RuntimeError:
        pass


def test_complete_raises_clear_error_on_200_response_with_error_envelope():
    def fake_post(url, *, headers, json, timeout):
        return FakeResponse(
            200,
            {"error": {"message": "Upstream error from Nvidia: Service temporarily overloaded", "code": 502}},
        )

    client = OpenRouterLLMClient("test-key", http_post=fake_post)
    try:
        client.complete("question")
        assert False, "expected an error"
    except RuntimeError as exc:
        assert "Upstream error from Nvidia: Service temporarily overloaded" in str(exc)
