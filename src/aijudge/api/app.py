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
from aijudge.orchestration.tools import build_tool_dispatch

from .schemas import AnswerRequest, QuestionRequest

DEFAULT_CORS_ORIGINS = ["http://localhost:3000", "http://localhost:5173"]

logger = logging.getLogger(__name__)


def _result_response(result: LoopResult) -> dict:
    return {
        "status": result.kind,
        "text": result.text,
        "citations": result.citations if result.kind == "answer" else None,
    }


def create_app(
    llm_client: LLMClient,
    embedding_client: EmbeddingClient,
    *,
    cors_origins: list[str] | None = None,
    tools: dict[str, Callable[[dict], dict]] | None = None,
) -> FastAPI:
    app = FastAPI()
    # Test-only seam: real callers never pass `tools` and get the DB/embedding-
    # backed dispatch below; tests can inject a stub dispatch to exercise the
    # citation-serialization path (lookup_card, etc.) without a live DB.
    tools = tools if tools is not None else build_tool_dispatch(embedding_client)

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

    @app.post("/questions")
    def post_question(body: QuestionRequest) -> dict:
        question = body.question.strip()
        if not question:
            raise HTTPException(status_code=400, detail="question must not be empty")

        clarify_response = llm_client.complete(build_clarification_prompt(question))
        items = parse_clarification_response(clarify_response)
        if items:
            return {
                "status": "needs_clarification",
                "question": question,
                "items": [{"kind": item.kind, "text": item.text} for item in items],
            }

        result = run_loop(question, llm_client=llm_client, tools=tools)
        return _result_response(result)

    @app.post("/questions/answer")
    def post_answer(body: AnswerRequest) -> dict:
        question = body.question.strip()
        if not question:
            raise HTTPException(status_code=400, detail="question must not be empty")
        if len(body.items) != len(body.answers):
            raise HTTPException(status_code=400, detail="items and answers must be the same length")

        items = [ClarificationItem(kind=item.kind, text=item.text) for item in body.items]
        context = format_clarification_context(items, body.answers)
        result = run_loop(question, llm_client=llm_client, tools=tools, clarification_context=context)
        return _result_response(result)

    return app
