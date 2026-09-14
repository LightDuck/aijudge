import os
from typing import Callable

from dotenv import load_dotenv

from aijudge.call_log import CallLogger, LoggingLLMClient
from aijudge.cli import run_cli
from aijudge.embeddings.client import EmbeddingClient
from aijudge.embeddings.ollama_client import OllamaEmbeddingClient
from aijudge.llm.anthropic_client import AnthropicLLMClient
from aijudge.llm.client import LLMClient


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set. Add it to your .env file or environment before running AIJudge.")
    return value


def build_llm_client() -> LLMClient:
    return AnthropicLLMClient(_require_env("ANTHROPIC_API_KEY"))


def main(
    *,
    llm_client: LLMClient | None = None,
    embedding_client: EmbeddingClient | None = None,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
) -> None:
    load_dotenv()
    call_logger = CallLogger()
    run_cli(
        LoggingLLMClient(llm_client or build_llm_client(), call_logger),
        embedding_client or OllamaEmbeddingClient(),
        input_fn=input_fn,
        print_fn=print_fn,
        call_logger=call_logger,
    )


if __name__ == "__main__":
    main()
