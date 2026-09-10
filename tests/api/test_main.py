import aijudge.api.__main__ as main_module
from aijudge.api.__main__ import main
from aijudge.call_log import CallLogger, LoggingLLMClient


class _StubLLMClient:
    def complete(self, prompt: str) -> str:
        raise AssertionError("should not be called during startup")


class _StubEmbeddingClient:
    def embed(self, text: str) -> list[float]:
        raise AssertionError("should not be called during startup")


def test_main_uses_injected_llm_client_instead_of_constructing_one(monkeypatch):
    constructed = {}

    class SpyOllamaLLMClient:
        def __init__(self):
            constructed["built"] = True

        def complete(self, prompt: str) -> str:
            raise AssertionError("should not be called during startup")

    monkeypatch.setattr(main_module, "OllamaLLMClient", SpyOllamaLLMClient)

    main(
        llm_client=_StubLLMClient(),
        embedding_client=_StubEmbeddingClient(),
        run_fn=lambda app, **kwargs: None,
    )

    assert "built" not in constructed


def test_main_defaults_to_a_real_ollama_backed_llm_client(monkeypatch):
    constructed = {}

    class SpyOllamaLLMClient:
        def __init__(self):
            constructed["built"] = True

        def complete(self, prompt: str) -> str:
            raise AssertionError("should not be called during startup")

    monkeypatch.setattr(main_module, "OllamaLLMClient", SpyOllamaLLMClient)
    monkeypatch.setattr(main_module, "OllamaEmbeddingClient", lambda: _StubEmbeddingClient())

    main(run_fn=lambda app, **kwargs: None)

    assert constructed.get("built") is True


def test_main_passes_host_and_port_to_run_fn(monkeypatch):
    monkeypatch.setenv("AIJUDGE_API_HOST", "0.0.0.0")
    monkeypatch.setenv("AIJUDGE_API_PORT", "9001")
    captured = {}

    main(
        llm_client=_StubLLMClient(),
        embedding_client=_StubEmbeddingClient(),
        run_fn=lambda app, **kwargs: captured.update(kwargs),
    )

    assert captured == {"host": "0.0.0.0", "port": 9001}


def test_main_parses_cors_origins_from_env(monkeypatch):
    monkeypatch.setenv("AIJUDGE_API_CORS_ORIGINS", "http://localhost:5173, http://localhost:4000")
    captured = {}

    monkeypatch.setattr(
        main_module,
        "create_app",
        lambda llm, emb, **kwargs: captured.update(kwargs),
    )

    main(
        llm_client=_StubLLMClient(),
        embedding_client=_StubEmbeddingClient(),
        run_fn=lambda app, **kwargs: None,
    )

    assert captured["cors_origins"] == ["http://localhost:5173", "http://localhost:4000"]


def test_main_passes_online_ingest_toggle_from_env(monkeypatch):
    monkeypatch.setenv("AIJUDGE_ENABLE_ONLINE_INGEST", "false")
    captured = {}

    monkeypatch.setattr(
        main_module,
        "create_app",
        lambda llm, emb, **kwargs: captured.update(kwargs),
    )

    main(
        llm_client=_StubLLMClient(),
        embedding_client=_StubEmbeddingClient(),
        run_fn=lambda app, **kwargs: None,
    )

    assert captured["online_ingest_enabled"] is False


def test_main_wraps_the_llm_client_for_logging_and_passes_a_call_logger(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        main_module,
        "create_app",
        lambda llm, emb, **kwargs: captured.update({"llm_client": llm, **kwargs}),
    )

    main(
        llm_client=_StubLLMClient(),
        embedding_client=_StubEmbeddingClient(),
        run_fn=lambda app, **kwargs: None,
    )

    assert isinstance(captured["llm_client"], LoggingLLMClient)
    assert isinstance(captured["call_logger"], CallLogger)


def test_main_defaults_online_ingest_toggle_to_true(monkeypatch):
    monkeypatch.delenv("AIJUDGE_ENABLE_ONLINE_INGEST", raising=False)
    captured = {}

    monkeypatch.setattr(
        main_module,
        "create_app",
        lambda llm, emb, **kwargs: captured.update(kwargs),
    )

    main(
        llm_client=_StubLLMClient(),
        embedding_client=_StubEmbeddingClient(),
        run_fn=lambda app, **kwargs: None,
    )

    assert captured["online_ingest_enabled"] is True
