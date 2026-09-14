from aijudge.llm.anthropic_client import DEFAULT_MODEL, AnthropicLLMClient


class FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeMessagesResource:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class FakeAnthropicClient:
    def __init__(self, response):
        self.messages = FakeMessagesResource(response)


def test_complete_sends_prompt_and_returns_text_content():
    fake_client = FakeAnthropicClient(FakeMessage([FakeTextBlock("the answer")]))
    client = AnthropicLLMClient("test-key", client=fake_client)

    result = client.complete("what is Ash Blossom's timing?")

    assert result == "the answer"
    call = fake_client.messages.calls[0]
    assert call["model"] == DEFAULT_MODEL
    assert call["messages"] == [{"role": "user", "content": "what is Ash Blossom's timing?"}]
    assert "system" not in call


def test_complete_uses_custom_model_when_given():
    fake_client = FakeAnthropicClient(FakeMessage([FakeTextBlock("ok")]))
    client = AnthropicLLMClient("test-key", model="claude-haiku-4-5", client=fake_client)

    client.complete("question")

    assert fake_client.messages.calls[0]["model"] == "claude-haiku-4-5"


def test_complete_includes_system_message_when_given():
    fake_client = FakeAnthropicClient(FakeMessage([FakeTextBlock("the answer")]))
    client = AnthropicLLMClient("test-key", client=fake_client)

    client.complete("what is Ash Blossom's timing?", system="You are a Yu-Gi-Oh! rules assistant.")

    call = fake_client.messages.calls[0]
    assert call["system"] == "You are a Yu-Gi-Oh! rules assistant."
    assert call["messages"] == [{"role": "user", "content": "what is Ash Blossom's timing?"}]


def test_complete_returns_empty_string_when_no_text_block_present():
    fake_client = FakeAnthropicClient(FakeMessage([]))
    client = AnthropicLLMClient("test-key", client=fake_client)

    result = client.complete("question")

    assert result == ""


def test_complete_returns_first_text_block_when_multiple_blocks_present():
    class FakeThinkingBlock:
        def __init__(self):
            self.type = "thinking"
            self.thinking = "reasoning..."

    fake_client = FakeAnthropicClient(FakeMessage([FakeThinkingBlock(), FakeTextBlock("the answer")]))
    client = AnthropicLLMClient("test-key", client=fake_client)

    result = client.complete("question")

    assert result == "the answer"
