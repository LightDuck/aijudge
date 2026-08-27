import logging
import traceback

import psycopg
import requests
from fastapi.testclient import TestClient

from aijudge.api.app import create_app
from aijudge.embeddings.client import MockEmbeddingClient
from aijudge.llm.client import MockLLMClient


def _client(llm: MockLLMClient, **kwargs) -> TestClient:
    app = create_app(llm, MockEmbeddingClient(), **kwargs)
    return TestClient(app)


def test_post_questions_returns_answer_when_no_clarification_needed():
    llm = MockLLMClient()
    llm.queue_response("PROCEED")
    llm.queue_response("FINAL: Ash Blossom negates that effect. ||CITES: ||")

    response = _client(llm).post("/questions", json={"question": "What does Ash Blossom do?"})

    assert response.status_code == 200
    assert response.json() == {"status": "answer", "text": "Ash Blossom negates that effect.", "citations": []}


def test_post_questions_returns_needs_clarification_when_llm_asks():
    llm = MockLLMClient()
    llm.queue_response("CLARIFY: Which card's effect are you asking about?")

    response = _client(llm).post("/questions", json={"question": "What does it do?"})

    assert response.status_code == 200
    assert response.json() == {
        "status": "needs_clarification",
        "question": "What does it do?",
        "items": [{"kind": "clarify", "text": "Which card's effect are you asking about?"}],
    }


def test_post_questions_rejects_empty_question():
    llm = MockLLMClient()

    response = _client(llm).post("/questions", json={"question": "   "})

    assert response.status_code == 400
    assert response.json() == {"detail": "question must not be empty"}


def test_post_questions_serializes_citation_content_without_leaking_raw_ids():
    # Mirrors tests/orchestration/test_loop.py's
    # test_tool_call_then_final_answer_includes_citation_text, but driven
    # through the actual HTTP/JSON response body -- proving citation
    # {label, text} pairs serialize correctly over the wire and that no
    # raw internal id (card:<uuid>, etc.) ever appears in the response.
    llm = MockLLMClient()
    llm.queue_response("PROCEED")
    llm.queue_response('TOOL: lookup_card {"name": "Ash Blossom & Joyous Spring"}')
    llm.queue_response("FINAL: It negates the effect. ||CITES: card:abc123||")

    stub_tools = {
        "lookup_card": lambda args: {
            "found": True,
            "id": "abc123",
            "name": "Ash Blossom & Joyous Spring",
            "card_text": "You can discard this card...",
            "confirmed_effect": {"effect": "..."},
        }
    }

    response = _client(llm, tools=stub_tools).post(
        "/questions", json={"question": "What does Ash Blossom do?"}
    )

    assert response.status_code == 200
    assert response.json()["citations"] == [
        {"label": "Ash Blossom & Joyous Spring", "text": "You can discard this card..."}
    ]
    assert "card:" not in response.text
    assert "abc123" not in response.text


def test_post_questions_cors_allows_configured_origin():
    llm = MockLLMClient()
    llm.queue_response("PROCEED")
    llm.queue_response("FINAL: ok. ||CITES: ||")

    client = _client(llm, cors_origins=["http://localhost:5173"])
    response = client.post(
        "/questions",
        json={"question": "x"},
        headers={"Origin": "http://localhost:5173"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_post_questions_answer_returns_final_result():
    llm = MockLLMClient()
    llm.queue_response("FINAL: Yes, it does that. ||CITES: ||")

    response = _client(llm).post(
        "/questions/answer",
        json={
            "question": "Is X active?",
            "items": [{"kind": "continuous_check", "text": "Some Card"}],
            "answers": ["Yes, it's on the field."],
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "answer", "text": "Yes, it does that.", "citations": []}


def test_post_questions_answer_rejects_mismatched_items_and_answers_length():
    llm = MockLLMClient()

    response = _client(llm).post(
        "/questions/answer",
        json={"question": "Is X active?", "items": [{"kind": "clarify", "text": "Which card?"}], "answers": []},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "items and answers must be the same length"}


def test_post_questions_answer_rejects_empty_question():
    llm = MockLLMClient()

    response = _client(llm).post("/questions/answer", json={"question": " ", "items": [], "answers": []})

    assert response.status_code == 400
    assert response.json() == {"detail": "question must not be empty"}


class _ConnectionErrorLLMClient:
    def complete(self, prompt: str) -> str:
        raise requests.exceptions.ConnectionError("no route to host")


class _BrokenLLMClient:
    def complete(self, prompt: str) -> str:
        raise RuntimeError("something internal broke")


def test_post_questions_returns_503_when_llm_backend_unreachable():
    app = create_app(_ConnectionErrorLLMClient(), MockEmbeddingClient())
    client = TestClient(app)

    response = client.post("/questions", json={"question": "What does Ash Blossom do?"})

    assert response.status_code == 503
    assert response.json() == {"detail": "backend unavailable"}


def test_post_questions_returns_generic_500_without_leaking_exception_details():
    app = create_app(_BrokenLLMClient(), MockEmbeddingClient())
    # ServerErrorMiddleware re-raises after building the response, specifically so
    # unhandled errors stay visible to the ASGI server/logs -- TestClient must be
    # told not to propagate that re-raised exception into the test itself.
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/questions", json={"question": "What does Ash Blossom do?"})

    assert response.status_code == 500
    assert response.json() == {"detail": "internal server error"}
    assert "something internal broke" not in response.text


class _OperationalErrorLLMClient:
    def complete(self, prompt: str) -> str:
        raise psycopg.OperationalError("could not connect to server")


def test_post_questions_returns_503_when_db_backend_unreachable():
    app = create_app(_OperationalErrorLLMClient(), MockEmbeddingClient())
    client = TestClient(app)

    response = client.post("/questions", json={"question": "What does Ash Blossom do?"})

    assert response.status_code == 503
    assert response.json() == {"detail": "backend unavailable"}


def _exc_log_records(caplog, logger_name: str = "aijudge.api.app") -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == logger_name]


def test_post_questions_503_logs_the_actual_exception_traceback(caplog):
    app = create_app(_ConnectionErrorLLMClient(), MockEmbeddingClient())
    client = TestClient(app)

    with caplog.at_level(logging.ERROR):
        client.post("/questions", json={"question": "What does Ash Blossom do?"})

    records = _exc_log_records(caplog)
    assert len(records) == 1
    exc_info = records[0].exc_info
    # Starlette dispatches sync exception handlers via run_in_threadpool, so
    # sys.exc_info() is empty on that worker thread -- logger.exception() must
    # be given the handler's own `exc` explicitly via exc_info=exc, or the
    # exception type/traceback is silently lost.
    assert exc_info is not None
    assert exc_info[0] is requests.exceptions.ConnectionError
    formatted = "".join(traceback.format_exception(*exc_info))
    assert "no route to host" in formatted


def test_post_questions_500_logs_the_actual_exception_traceback(caplog):
    app = create_app(_BrokenLLMClient(), MockEmbeddingClient())
    client = TestClient(app, raise_server_exceptions=False)

    with caplog.at_level(logging.ERROR):
        client.post("/questions", json={"question": "What does Ash Blossom do?"})

    records = _exc_log_records(caplog)
    assert len(records) == 1
    exc_info = records[0].exc_info
    assert exc_info is not None
    assert exc_info[0] is RuntimeError
    formatted = "".join(traceback.format_exception(*exc_info))
    assert "something internal broke" in formatted
