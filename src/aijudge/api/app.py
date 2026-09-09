import logging
from typing import Callable

import psycopg
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from aijudge.embeddings.client import EmbeddingClient
from aijudge.llm.client import LLMClient
from aijudge.orchestration.card_effect_pipeline import PipelineResolution, resolve_card_effect_question
from aijudge.orchestration.clarify import (
    ClarificationItem,
    build_clarification_prompt,
    format_clarification_context,
    parse_clarification_response,
)
from aijudge.orchestration.loop import NOT_SUPPORTED_MESSAGE, LoopResult, run_loop
from aijudge.orchestration.preflight import (
    build_grounded_result,
    build_known_facts_context,
    find_matched_cards,
    find_mentioned_card_names,
)
from aijudge.orchestration.protocol import build_answering_system_prompt, build_system_prompt

from .schemas import AnswerRequest, NeedsClarificationResponse, QuestionRequest, ResultResponse

DEFAULT_CORS_ORIGINS = ["http://localhost:3000", "http://localhost:5173"]

logger = logging.getLogger(__name__)


def _result_response(result: LoopResult) -> dict:
    return {
        "status": result.kind,
        "text": result.text,
        "citations": result.citations if result.kind == "answer" else None,
    }


def _resolve_preflight_card(
    matches: list[dict],
    items: list[ClarificationItem],
    answers: list[str],
) -> dict | None:
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        disambiguate_index = next(
            (i for i, item in enumerate(items) if item.kind == "disambiguate_card"), None
        )
        if disambiguate_index is not None and disambiguate_index < len(answers):
            candidate_names = [match["name"] for match in matches]
            matched_names = find_mentioned_card_names(answers[disambiguate_index], candidate_names)
            return next((m for m in matches if m["name"] == matched_names[0]), None) if matched_names else None
    return None


def create_app(
    llm_client: LLMClient,
    embedding_client: EmbeddingClient,
    *,
    cors_origins: list[str] | None = None,
    find_matched_cards_fn: Callable[[str], list[dict]] | None = None,
    build_known_facts_context_fn: Callable[[dict], str] | None = None,
    build_grounded_result_fn: Callable[[dict], dict] | None = None,
    resolve_card_effect_question_fn: Callable[..., PipelineResolution] | None = None,
    online_ingest_enabled: bool = True,
) -> FastAPI:
    app = FastAPI()
    find_matched_cards_fn = find_matched_cards_fn if find_matched_cards_fn is not None else find_matched_cards
    build_known_facts_context_fn = (
        build_known_facts_context_fn if build_known_facts_context_fn is not None else build_known_facts_context
    )
    build_grounded_result_fn = (
        build_grounded_result_fn if build_grounded_result_fn is not None else build_grounded_result
    )
    resolve_card_effect_question_fn = (
        resolve_card_effect_question_fn
        if resolve_card_effect_question_fn is not None
        else resolve_card_effect_question
    )

    def _backend_unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("backend connection error", exc_info=exc)
        return JSONResponse(status_code=503, content={"detail": "backend unavailable"})

    def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error", exc_info=exc)
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

    app.add_exception_handler(requests.exceptions.ConnectionError, _backend_unavailable_handler)
    app.add_exception_handler(psycopg.OperationalError, _backend_unavailable_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins if cors_origins is not None else DEFAULT_CORS_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.post("/questions", response_model=ResultResponse | NeedsClarificationResponse)
    def post_question(body: QuestionRequest) -> dict:
        question = body.question.strip()
        if not question:
            raise HTTPException(status_code=400, detail="question must not be empty")

        matches = find_matched_cards_fn(question)
        disambiguation_items: list[ClarificationItem] = []
        preflight_context = ""
        if len(matches) == 1:
            preflight_context = build_known_facts_context_fn(matches[0])
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
                build_clarification_prompt(question, known_facts_context=preflight_context),
                system=build_system_prompt(),
            )
            items = disambiguation_items + parse_clarification_response(clarify_response)
        else:
            items = disambiguation_items
        if items:
            return {
                "status": "needs_clarification",
                "question": question,
                "items": [{"kind": item.kind, "text": item.text} for item in items],
            }

        grounded_cards = [build_grounded_result_fn(matches[0])] if len(matches) == 1 else []
        if not matches:
            resolution = resolve_card_effect_question_fn(
                question,
                llm_client=llm_client,
                online_ingest_enabled=online_ingest_enabled,
                on_ingest_start=None,
            )
            if not resolution.supported:
                return _result_response(LoopResult(kind="not_supported", text=NOT_SUPPORTED_MESSAGE))
            preflight_context = resolution.context
            grounded_cards = resolution.grounded_cards

        result = run_loop(
            question,
            llm_client=llm_client,
            tools={},
            clarification_context=preflight_context,
            grounded_cards=grounded_cards,
            system_prompt=build_answering_system_prompt(),
        )
        return _result_response(result)

    @app.post("/questions/answer", response_model=ResultResponse)
    def post_answer(body: AnswerRequest) -> dict:
        question = body.question.strip()
        if not question:
            raise HTTPException(status_code=400, detail="question must not be empty")
        if len(body.items) != len(body.answers):
            raise HTTPException(status_code=400, detail="items and answers must be the same length")

        items = [ClarificationItem(kind=item.kind, text=item.text) for item in body.items]
        matches = find_matched_cards_fn(question)
        card = _resolve_preflight_card(matches, items, body.answers)
        preflight_context = build_known_facts_context_fn(card) if card is not None else ""
        grounded_cards = [build_grounded_result_fn(card)] if card is not None else []

        if not matches or not grounded_cards:
            # 0 local matches, or a disambiguation-miss (matches > 1 but the
            # answer didn't fuzzy-resolve, leaving grounded_cards empty): try
            # mandatory extraction + deterministic lookup instead of
            # proceeding ungrounded (the original gap).
            resolution = resolve_card_effect_question_fn(
                question,
                llm_client=llm_client,
                online_ingest_enabled=online_ingest_enabled,
                on_ingest_start=None,
            )
            if not resolution.supported:
                return _result_response(LoopResult(kind="not_supported", text=NOT_SUPPORTED_MESSAGE))
            preflight_context = resolution.context
            grounded_cards = resolution.grounded_cards

        context = format_clarification_context(items, body.answers)
        if preflight_context:
            context = f"{preflight_context}\n\n{context}" if context else preflight_context

        result = run_loop(
            question,
            llm_client=llm_client,
            tools={},
            clarification_context=context,
            grounded_cards=grounded_cards,
            system_prompt=build_answering_system_prompt(),
        )
        return _result_response(result)

    return app
