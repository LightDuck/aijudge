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
