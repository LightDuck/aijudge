import aijudge.__main__ as main_module
from aijudge.__main__ import main


def test_main_exits_immediately_on_quit():
    printed = []

    main(input_fn=lambda _: "quit", print_fn=printed.append)

    assert any("AIJudge" in line for line in printed)


def test_main_uses_injected_llm_client_instead_of_constructing_one():
    used = {}

    class SpyLLMClient:
        def complete(self, prompt: str) -> str:
            used["called"] = True
            return "0.5"

    main(llm_client=SpyLLMClient(), input_fn=lambda _: "quit", print_fn=lambda _: None)

    assert "called" not in used  # "quit" exits before any LLM call is made


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
