import pytest

from aijudge import entrypoint
from aijudge.call_log import CallLogger, LoggingLLMClient
from aijudge.embeddings.openai_client import OpenAIEmbeddingClient
from aijudge.llm.anthropic_client import AnthropicLLMClient


def test_build_llm_client_uses_anthropic_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "an-key")

    client = entrypoint.build_llm_client()

    assert isinstance(client, AnthropicLLMClient)


def test_build_llm_client_raises_clear_error_when_key_missing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        entrypoint.build_llm_client()


def test_build_embedding_client_uses_openai_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "oa-key")

    client = entrypoint.build_embedding_client()

    assert isinstance(client, OpenAIEmbeddingClient)
    assert client._api_key == "oa-key"


def test_build_embedding_client_raises_clear_error_when_key_missing(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        entrypoint.build_embedding_client()


def test_main_builds_real_clients_and_runs_cli(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "an-key")
    monkeypatch.setenv("OPENAI_API_KEY", "oa-key")
    captured = {}

    def fake_run_cli(llm_client, embedding_client, **kwargs):
        captured["llm_client"] = llm_client
        captured["embedding_client"] = embedding_client

    monkeypatch.setattr(entrypoint, "run_cli", fake_run_cli)

    entrypoint.main()

    assert isinstance(captured["llm_client"], LoggingLLMClient)
    assert isinstance(captured["llm_client"].inner, AnthropicLLMClient)
    assert isinstance(captured["embedding_client"], OpenAIEmbeddingClient)


def test_main_passes_a_call_logger_to_run_cli(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "an-key")
    monkeypatch.setenv("OPENAI_API_KEY", "oa-key")
    captured = {}

    def fake_run_cli(llm_client, embedding_client, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(entrypoint, "run_cli", fake_run_cli)

    entrypoint.main()

    assert isinstance(captured["call_logger"], CallLogger)


def test_online_ingest_enabled_defaults_to_true(monkeypatch):
    monkeypatch.delenv("AIJUDGE_ENABLE_ONLINE_INGEST", raising=False)
    assert entrypoint._online_ingest_enabled() is True


def test_online_ingest_enabled_reads_false_from_env(monkeypatch):
    monkeypatch.setenv("AIJUDGE_ENABLE_ONLINE_INGEST", "false")
    assert entrypoint._online_ingest_enabled() is False


def test_online_ingest_enabled_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("AIJUDGE_ENABLE_ONLINE_INGEST", "FALSE")
    assert entrypoint._online_ingest_enabled() is False


def test_main_passes_online_ingest_toggle_to_run_cli(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "an-key")
    monkeypatch.setenv("OPENAI_API_KEY", "oa-key")
    monkeypatch.setenv("AIJUDGE_ENABLE_ONLINE_INGEST", "false")
    captured = {}

    def fake_run_cli(llm_client, embedding_client, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(entrypoint, "run_cli", fake_run_cli)

    entrypoint.main()

    assert captured["online_ingest_enabled"] is False
