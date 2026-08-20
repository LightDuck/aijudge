import os

from dotenv import load_dotenv

from .cli import run_cli
from .embeddings.client import EmbeddingClient
from .embeddings.openai_client import OpenAIEmbeddingClient
from .llm.client import LLMClient
from .llm.openrouter_client import OpenRouterLLMClient


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set. Add it to your .env file or environment before running AIJudge.")
    return value


def build_llm_client() -> LLMClient:
    return OpenRouterLLMClient(_require_env("OPENROUTER_API_KEY"))


def build_embedding_client() -> EmbeddingClient:
    return OpenAIEmbeddingClient(_require_env("OPENAI_API_KEY"))


def main() -> None:
    load_dotenv()
    run_cli(build_llm_client(), build_embedding_client())


if __name__ == "__main__":
    main()
