import logging
import os
from typing import Callable

import uvicorn
from dotenv import load_dotenv

from aijudge.call_log import CallLogger, LoggingLLMClient
from aijudge.embeddings.client import EmbeddingClient
from aijudge.entrypoint import build_embedding_client, build_llm_client
from aijudge.llm.client import LLMClient

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
    load_dotenv()
    _configure_logging_from_env()
    call_logger = CallLogger()
    app = create_app(
        LoggingLLMClient(llm_client or build_llm_client(), call_logger),
        embedding_client or build_embedding_client(),
        cors_origins=_cors_origins_from_env(),
        online_ingest_enabled=_online_ingest_enabled_from_env(),
        call_logger=call_logger,
    )
    host = os.environ.get("AIJUDGE_API_HOST", DEFAULT_HOST)
    port = int(os.environ.get("AIJUDGE_API_PORT", DEFAULT_PORT))
    run_fn(app, host=host, port=port)


if __name__ == "__main__":
    main()
