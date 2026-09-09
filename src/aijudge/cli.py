from typing import Callable

from aijudge.embeddings.client import EmbeddingClient
from aijudge.llm.client import LLMClient

from .orchestration.card_effect_pipeline import PipelineResolution, resolve_card_effect_question
from .orchestration.clarify import (
    ClarificationItem,
    build_clarification_prompt,
    clarification_prompt_text,
    format_clarification_context,
    parse_clarification_response,
)
from .orchestration.loop import NOT_SUPPORTED_MESSAGE, run_loop
from .orchestration.preflight import (
    build_grounded_result,
    build_known_facts_context,
    find_matched_cards,
    find_mentioned_card_names,
)
from .orchestration.protocol import build_answering_system_prompt, build_system_prompt


def run_cli(
    llm_client: LLMClient,
    embedding_client: EmbeddingClient,
    *,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
    find_matched_cards_fn: Callable[[str], list[dict]] = find_matched_cards,
    build_known_facts_context_fn: Callable[[dict], str] = build_known_facts_context,
    build_grounded_result_fn: Callable[[dict], dict] = build_grounded_result,
    resolve_card_effect_question_fn: Callable[..., PipelineResolution] = resolve_card_effect_question,
    online_ingest_enabled: bool = True,
) -> None:
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
        preflight_context = ""
        grounded_cards: list[dict] = []
        if len(matches) == 1:
            preflight_context = build_known_facts_context_fn(matches[0])
            grounded_cards = [build_grounded_result_fn(matches[0])]
        elif len(matches) > 1:
            names = ", ".join(match["name"] for match in matches)
            disambiguation_items.append(
                ClarificationItem(
                    kind="disambiguate_card",
                    text=f"Multiple cards match your question: {names}. Which one do you mean?",
                )
            )

        if matches:
            clarify_response = llm_client.complete(
                build_clarification_prompt(stripped, known_facts_context=preflight_context),
                system=build_system_prompt(),
            )
            items = disambiguation_items + parse_clarification_response(clarify_response)
        else:
            items = disambiguation_items
        answers = [input_fn(f"{clarification_prompt_text(item)} ") for item in items]

        if len(matches) > 1 and answers:
            candidate_names = [match["name"] for match in matches]
            matched_names = find_mentioned_card_names(answers[0], candidate_names)
            chosen = next((match for match in matches if match["name"] == matched_names[0]), None) if matched_names else None
            if chosen is not None:
                preflight_context = build_known_facts_context_fn(chosen)
                grounded_cards = [build_grounded_result_fn(chosen)]
            else:
                print_fn("Couldn't match your answer to a specific card -- proceeding without that card's confirmed details.")

        if not matches or not grounded_cards:
            # 0 local matches, or a disambiguation-miss (matches > 1 but the
            # user's answer didn't fuzzy-resolve to any candidate, leaving
            # grounded_cards empty): try mandatory extraction + deterministic
            # lookup instead of proceeding ungrounded (the original gap).
            resolution = resolve_card_effect_question_fn(
                stripped,
                llm_client=llm_client,
                online_ingest_enabled=online_ingest_enabled,
                on_ingest_start=lambda name: print_fn(f"Looking up {name}, this may take a moment..."),
            )
            if not resolution.supported:
                print_fn(NOT_SUPPORTED_MESSAGE)
                continue
            preflight_context = resolution.context
            grounded_cards = resolution.grounded_cards

        context = format_clarification_context(items, answers)
        if preflight_context:
            context = f"{preflight_context}\n\n{context}" if context else preflight_context

        result = run_loop(
            stripped,
            llm_client=llm_client,
            tools={},
            clarification_context=context,
            grounded_cards=grounded_cards,
            system_prompt=build_answering_system_prompt(),
        )
        print_fn(result.text)
