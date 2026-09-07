import logging
import os
from typing import Callable

import uvicorn

from aijudge.embeddings.client import EmbeddingClient
from aijudge.embeddings.ollama_client import OllamaEmbeddingClient
from aijudge.llm.client import LLMClient, OllamaLLMClient

from .app import create_app

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def _configure_logging_from_env() -> None:
    level_name = os.environ.get("AIJUDGE_LOG_LEVEL")
    if level_name is None:
        return
    logging.basicConfig(level=level_name.upper())
    logging.getLogger("aijudge").setLevel(level_name.upper())


def _cors_origins_from_env() -> list[str] | None:
    raw = os.environ.get("AIJUDGE_API_CORS_ORIGINS")
    if raw is None:
        return None
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def _online_ingest_enabled_from_env() -> bool:
    return os.environ.get("AIJUDGE_ENABLE_ONLINE_INGEST", "true").strip().lower() != "false"


def main(
    *,
    llm_client: LLMClient | None = None,
    embedding_client: EmbeddingClient | None = None,
    run_fn: Callable = uvicorn.run,
) -> None:
    _configure_logging_from_env()
    app = create_app(
        llm_client or OllamaLLMClient(),
        embedding_client or OllamaEmbeddingClient(),
        cors_origins=_cors_origins_from_env(),
        online_ingest_enabled=_online_ingest_enabled_from_env(),
    )
    host = os.environ.get("AIJUDGE_API_HOST", DEFAULT_HOST)
    port = int(os.environ.get("AIJUDGE_API_PORT", DEFAULT_PORT))
    run_fn(app, host=host, port=port)


if __name__ == "__main__":
    main()
