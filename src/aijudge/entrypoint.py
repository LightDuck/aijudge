import os

from dotenv import load_dotenv

from .call_log import CallLogger, LoggingLLMClient
from .cli import run_cli
from .embeddings.client import EmbeddingClient
from .embeddings.openai_client import OpenAIEmbeddingClient
from .llm.anthropic_client import AnthropicLLMClient
from .llm.client import LLMClient


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set. Add it to your .env file or environment before running AIJudge.")
    return value


def build_llm_client() -> LLMClient:
    return AnthropicLLMClient(_require_env("ANTHROPIC_API_KEY"))


def build_embedding_client() -> EmbeddingClient:
    return OpenAIEmbeddingClient(_require_env("OPENAI_API_KEY"))


def _online_ingest_enabled() -> bool:
    return os.environ.get("AIJUDGE_ENABLE_ONLINE_INGEST", "true").strip().lower() != "false"


def main() -> None:
    load_dotenv()
    call_logger = CallLogger()
    run_cli(
        LoggingLLMClient(build_llm_client(), call_logger),
        build_embedding_client(),
        online_ingest_enabled=_online_ingest_enabled(),
        call_logger=call_logger,
    )


if __name__ == "__main__":
    main()
