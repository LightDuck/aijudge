from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from aijudge.embeddings.client import EmbeddingClient
from aijudge.llm.client import LLMClient
from aijudge.orchestration.clarify import build_clarification_prompt, parse_clarification_response
from aijudge.orchestration.loop import LoopResult, run_loop
from aijudge.orchestration.tools import build_tool_dispatch

from .schemas import QuestionRequest

DEFAULT_CORS_ORIGINS = ["http://localhost:3000", "http://localhost:5173"]


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
) -> FastAPI:
    app = FastAPI()
    tools = build_tool_dispatch(embedding_client)

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

    return app
