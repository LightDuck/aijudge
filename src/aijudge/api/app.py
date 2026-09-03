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
from aijudge.orchestration.clarify import (
    ClarificationItem,
    build_clarification_prompt,
    format_clarification_context,
    parse_clarification_response,
)
from aijudge.orchestration.loop import LoopResult, run_loop
from aijudge.orchestration.preflight import build_known_facts_context, find_matched_cards, find_mentioned_card_names
from aijudge.orchestration.protocol import build_system_prompt
from aijudge.orchestration.tools import build_tool_dispatch

from .schemas import AnswerRequest, NeedsClarificationResponse, QuestionRequest, ResultResponse

DEFAULT_CORS_ORIGINS = ["http://localhost:3000", "http://localhost:5173"]

logger = logging.getLogger(__name__)


def _result_response(result: LoopResult) -> dict:
    return {
        "status": result.kind,
        "text": result.text,
        "citations": result.citations if result.kind == "answer" else None,
    }


def _resolve_preflight_context(
    matches: list[dict],
    items: list[ClarificationItem],
    answers: list[str],
    build_known_facts_context_fn: Callable[[dict], str],
) -> str:
    # Mirrors cli.py's preflight resolution, but re-derived from scratch on
    # every call since the API is stateless -- there's no in-process session
    # to carry `matches` between /questions and /questions/answer.
    if len(matches) == 1:
        return build_known_facts_context_fn(matches[0])
    if len(matches) > 1:
        disambiguate_index = next(
            (i for i, item in enumerate(items) if item.kind == "disambiguate_card"), None
        )
        if disambiguate_index is not None and disambiguate_index < len(answers):
            candidate_names = [match["name"] for match in matches]
            matched_names = find_mentioned_card_names(answers[disambiguate_index], candidate_names)
            chosen = next((m for m in matches if m["name"] == matched_names[0]), None) if matched_names else None
            if chosen is not None:
                return build_known_facts_context_fn(chosen)
    return ""


def create_app(
    llm_client: LLMClient,
    embedding_client: EmbeddingClient,
    *,
    cors_origins: list[str] | None = None,
    tools: dict[str, Callable[[dict], dict]] | None = None,
    find_matched_cards_fn: Callable[[str], list[dict]] | None = None,
    build_known_facts_context_fn: Callable[[dict], str] | None = None,
    online_ingest_enabled: bool = True,
) -> FastAPI:
    app = FastAPI()
    # Test-only seam: real callers never pass `tools` and get the DB/embedding-
    # backed dispatch below; tests can inject a stub dispatch to exercise the
    # citation-serialization path (lookup_card, etc.) without a live DB.
    tools = (
        tools
        if tools is not None
        else build_tool_dispatch(llm_client, embedding_client, online_ingest_enabled=online_ingest_enabled)
    )
    find_matched_cards_fn = find_matched_cards_fn if find_matched_cards_fn is not None else find_matched_cards
    build_known_facts_context_fn = (
        build_known_facts_context_fn if build_known_facts_context_fn is not None else build_known_facts_context
    )

    def _backend_unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
        # Starlette dispatches sync exception handlers via run_in_threadpool, so
        # sys.exc_info() is empty on that worker thread -- exc_info=True (the
        # logger.exception() default) would log nothing. Pass exc explicitly.
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
            # Ground the clarification-decision call itself, not just the
            # eventual run_loop call -- otherwise the LLM can ask for
            # clarification the deterministic KNOWN FACTS already resolve.
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
            # No known card at all means the clarify pass has nothing to
            # ground a decision in -- it tends to second-guess the card
            # name itself (asking the user to confirm/spell it) even
            # though lookup_card auto-imports on demand, so skip the call
            # entirely rather than rely on the LLM following that
            # instruction every time.
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

        result = run_loop(question, llm_client=llm_client, tools=tools, clarification_context=preflight_context)
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
        preflight_context = _resolve_preflight_context(matches, items, body.answers, build_known_facts_context_fn)

        context = format_clarification_context(items, body.answers)
        if preflight_context:
            context = f"{preflight_context}\n\n{context}" if context else preflight_context

        result = run_loop(question, llm_client=llm_client, tools=tools, clarification_context=context)
        return _result_response(result)

    return app
