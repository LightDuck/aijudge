from typing import Callable

from aijudge.embeddings.client import EmbeddingClient
from aijudge.llm.client import LLMClient

from .orchestration.clarify import (
    ClarificationItem,
    build_clarification_prompt,
    clarification_prompt_text,
    format_clarification_context,
    parse_clarification_response,
)
from .orchestration.loop import run_loop
from .orchestration.preflight import build_known_facts_context, find_matched_cards, find_mentioned_card_names
from .orchestration.tools import build_tool_dispatch


def run_cli(
    llm_client: LLMClient,
    embedding_client: EmbeddingClient,
    *,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
    find_matched_cards_fn: Callable[[str], list[dict]] = find_matched_cards,
    build_known_facts_context_fn: Callable[[dict], str] = build_known_facts_context,
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

        matches = find_matched_cards_fn(stripped)
        disambiguation_items: list[ClarificationItem] = []
        if len(matches) > 1:
            names = ", ".join(match["name"] for match in matches)
            disambiguation_items.append(
                ClarificationItem(
                    kind="disambiguate_card",
                    text=f"Multiple cards match your question: {names}. Which one do you mean?",
                )
            )

        clarify_response = llm_client.complete(build_clarification_prompt(stripped))
        items = disambiguation_items + parse_clarification_response(clarify_response)
        answers = [input_fn(f"{clarification_prompt_text(item)} ") for item in items]

        preflight_context = ""
        if len(matches) == 1:
            preflight_context = build_known_facts_context_fn(matches[0])
        elif len(matches) > 1 and answers:
            candidate_names = [match["name"] for match in matches]
            matched_names = find_mentioned_card_names(answers[0], candidate_names)
            chosen = next((match for match in matches if match["name"] == matched_names[0]), None) if matched_names else None
            if chosen is not None:
                preflight_context = build_known_facts_context_fn(chosen)
            else:
                print_fn("Couldn't match your answer to a specific card -- proceeding without that card's confirmed details.")

        context = format_clarification_context(items, answers)
        if preflight_context:
            context = f"{preflight_context}\n\n{context}" if context else preflight_context

        result = run_loop(stripped, llm_client=llm_client, tools=tools, clarification_context=context)
        print_fn(result.text)
