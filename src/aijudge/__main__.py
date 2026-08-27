from typing import Callable

from aijudge.cli import run_cli
from aijudge.embeddings.client import EmbeddingClient
from aijudge.embeddings.ollama_client import OllamaEmbeddingClient
from aijudge.llm.client import LLMClient, OllamaLLMClient


def main(
    *,
    llm_client: LLMClient | None = None,
    embedding_client: EmbeddingClient | None = None,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
) -> None:
    run_cli(
        llm_client or OllamaLLMClient(),
        embedding_client or OllamaEmbeddingClient(),
        input_fn=input_fn,
        print_fn=print_fn,
    )


if __name__ == "__main__":
    main()
