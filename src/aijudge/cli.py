from typing import Callable

from aijudge.embeddings.client import EmbeddingClient
from aijudge.llm.client import LLMClient

from .orchestration.clarify import (
    build_clarification_prompt,
    clarification_prompt_text,
    format_clarification_context,
    parse_clarification_response,
)
from .orchestration.loop import run_loop
from .orchestration.tools import build_tool_dispatch


def run_cli(
    llm_client: LLMClient,
    embedding_client: EmbeddingClient,
    *,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
) -> None:
    tools = build_tool_dispatch(embedding_client)
    print_fn("AIJudge -- ask a Yu-Gi-Oh! rules question ('exit' or 'quit' to leave).")

    while True:
        try:
            question = input_fn("> ")
        except EOFError:
            break

        stripped = question.strip()
        if stripped.lower() in ("exit", "quit"):
            break
        if not stripped:
            continue

        clarify_response = llm_client.complete(build_clarification_prompt(stripped))
        items = parse_clarification_response(clarify_response)
        answers = [input_fn(f"{clarification_prompt_text(item)} ") for item in items]
        context = format_clarification_context(items, answers)

        result = run_loop(stripped, llm_client=llm_client, tools=tools, clarification_context=context)
        print_fn(result.text)
