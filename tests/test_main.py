import pytest

import aijudge.__main__ as main_module
from aijudge.__main__ import main
from aijudge.call_log import CallLogger, LoggingLLMClient


def test_main_exits_immediately_on_quit(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "an-key")
    printed = []

    main(input_fn=lambda _: "quit", print_fn=printed.append)

    assert any("AIJudge" in line for line in printed)


def test_main_uses_injected_llm_client_instead_of_constructing_one(monkeypatch):
    constructed = {}

    class SpyAnthropicLLMClient:
        def __init__(self, api_key):
            constructed["built"] = True

        def complete(self, prompt: str) -> str:
            raise AssertionError("should not be called before user asks a question")

    monkeypatch.setattr(main_module, "AnthropicLLMClient", SpyAnthropicLLMClient)

    class InjectedLLMClient:
        def complete(self, prompt: str) -> str:
            raise AssertionError("should not be called before user asks a question")

    main(llm_client=InjectedLLMClient(), input_fn=lambda _: "quit", print_fn=lambda _: None)

    assert "built" not in constructed  # the injected client must be used, not AnthropicLLMClient()


def test_main_uses_injected_embedding_client_instead_of_constructing_one(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "an-key")
    constructed = {}

    class SpyOllamaEmbeddingClient:
        def __init__(self):
            constructed["built"] = True

        def embed(self, text: str) -> list[float]:
            raise AssertionError("should not be called before user asks a question")

    monkeypatch.setattr(main_module, "OllamaEmbeddingClient", SpyOllamaEmbeddingClient)

    class InjectedEmbeddingClient:
        def embed(self, text: str) -> list[float]:
            raise AssertionError("should not be called before user asks a question")

    main(embedding_client=InjectedEmbeddingClient(), input_fn=lambda _: "quit", print_fn=lambda _: None)

    assert "built" not in constructed  # the injected client must be used, not OllamaEmbeddingClient()


def test_main_defaults_to_a_real_anthropic_backed_llm_client(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "an-key")
    constructed = {}

    class SpyAnthropicLLMClient:
        def __init__(self, api_key):
            constructed["built"] = True
            constructed["api_key"] = api_key

        def complete(self, prompt: str) -> str:
            raise AssertionError("should not be called before user asks a question")

    monkeypatch.setattr(main_module, "AnthropicLLMClient", SpyAnthropicLLMClient)

    main(input_fn=lambda _: "quit", print_fn=lambda _: None)

    assert constructed.get("built") is True
    assert constructed.get("api_key") == "an-key"


def test_main_raises_clear_error_when_anthropic_api_key_missing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        main_module.build_llm_client()


def test_main_defaults_to_a_real_ollama_backed_embedding_client(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "an-key")
    constructed = {}

    class SpyOllamaEmbeddingClient:
        def __init__(self):
            constructed["built"] = True

        def embed(self, text: str) -> list[float]:
            raise AssertionError("should not be called before user asks a question")

    monkeypatch.setattr(main_module, "OllamaEmbeddingClient", SpyOllamaEmbeddingClient)

    main(input_fn=lambda _: "quit", print_fn=lambda _: None)

    assert constructed.get("built") is True


def test_main_wraps_the_llm_client_for_logging_and_passes_a_call_logger(monkeypatch):
    captured = {}

    def fake_run_cli(llm_client, embedding_client, **kwargs):
        captured["llm_client"] = llm_client
        captured.update(kwargs)

    monkeypatch.setattr(main_module, "run_cli", fake_run_cli)

    class InjectedLLMClient:
        def complete(self, prompt: str, *, system: str | None = None) -> str:
            raise AssertionError("should not be called")

    injected = InjectedLLMClient()
    main(llm_client=injected)

    assert isinstance(captured["llm_client"], LoggingLLMClient)
    assert captured["llm_client"].inner is injected
    assert isinstance(captured["call_logger"], CallLogger)
