import aijudge.__main__ as main_module
from aijudge.__main__ import main


def test_main_exits_immediately_on_quit():
    printed = []

    main(input_fn=lambda _: "quit", print_fn=printed.append)

    assert any("AIJudge" in line for line in printed)


def test_main_uses_injected_llm_client_instead_of_constructing_one(monkeypatch):
    constructed = {}

    class SpyOllamaLLMClient:
        def __init__(self):
            constructed["built"] = True

        def complete(self, prompt: str) -> str:
            raise AssertionError("should not be called before user asks a question")

    monkeypatch.setattr(main_module, "OllamaLLMClient", SpyOllamaLLMClient)

    class InjectedLLMClient:
        def complete(self, prompt: str) -> str:
            raise AssertionError("should not be called before user asks a question")

    main(llm_client=InjectedLLMClient(), input_fn=lambda _: "quit", print_fn=lambda _: None)

    assert "built" not in constructed  # the injected client must be used, not OllamaLLMClient()


def test_main_uses_injected_embedding_client_instead_of_constructing_one(monkeypatch):
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


def test_main_defaults_to_a_real_ollama_backed_llm_client(monkeypatch):
    constructed = {}

    class SpyOllamaLLMClient:
        def __init__(self):
            constructed["built"] = True

        def complete(self, prompt: str) -> str:
            raise AssertionError("should not be called before user asks a question")

    monkeypatch.setattr(main_module, "OllamaLLMClient", SpyOllamaLLMClient)

    main(input_fn=lambda _: "quit", print_fn=lambda _: None)

    assert constructed.get("built") is True


def test_main_defaults_to_a_real_ollama_backed_embedding_client(monkeypatch):
    constructed = {}

    class SpyOllamaEmbeddingClient:
        def __init__(self):
            constructed["built"] = True

        def embed(self, text: str) -> list[float]:
            raise AssertionError("should not be called before user asks a question")

    monkeypatch.setattr(main_module, "OllamaEmbeddingClient", SpyOllamaEmbeddingClient)

    main(input_fn=lambda _: "quit", print_fn=lambda _: None)

    assert constructed.get("built") is True
