import pytest

from aijudge import entrypoint
from aijudge.embeddings.openai_client import OpenAIEmbeddingClient
from aijudge.llm.openrouter_client import OpenRouterLLMClient


def test_build_llm_client_uses_openrouter_api_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")

    client = entrypoint.build_llm_client()

    assert isinstance(client, OpenRouterLLMClient)
    assert client._api_key == "or-key"


def test_build_llm_client_raises_clear_error_when_key_missing(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
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
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("OPENAI_API_KEY", "oa-key")
    captured = {}

    def fake_run_cli(llm_client, embedding_client):
        captured["llm_client"] = llm_client
        captured["embedding_client"] = embedding_client

    monkeypatch.setattr(entrypoint, "run_cli", fake_run_cli)

    entrypoint.main()

    assert isinstance(captured["llm_client"], OpenRouterLLMClient)
    assert isinstance(captured["embedding_client"], OpenAIEmbeddingClient)
