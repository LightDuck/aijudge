import json
import logging
import traceback

import psycopg
import requests
from fastapi.testclient import TestClient

from aijudge.api.app import create_app
from aijudge.call_log import CallLogger, LoggingLLMClient
from aijudge.embeddings.client import MockEmbeddingClient
from aijudge.llm.client import MockLLMClient
from aijudge.orchestration.card_effect_pipeline import PipelineResolution
from aijudge.orchestration.protocol import build_system_prompt


def _client(llm: MockLLMClient, **kwargs) -> TestClient:
    # Default to no preflight card matches so existing tests -- which don't
    # care about preflight -- don't accidentally hit a real (unconfigured)
    # DB via the real find_matched_cards. Tests that want to exercise
    # preflight override find_matched_cards_fn explicitly.
    kwargs.setdefault("find_matched_cards_fn", lambda question: [])
    kwargs.setdefault(
        "resolve_card_effect_question_fn",
        lambda question, **kw: PipelineResolution(supported=True),
    )
    app = create_app(llm, MockEmbeddingClient(), **kwargs)
    return TestClient(app)


class _CapturingLLMClient:
    """A FIFO-response fake that also records every prompt it receives, so
    tests can assert on what actually reached the LLM (mirrors test_cli.py's
    helper of the same name)."""

    def __init__(self, responses):
        self._queue = list(responses)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        self.prompts.append(prompt)
        return self._queue.pop(0)


def test_post_questions_tags_clarification_call_with_clarify_site_and_logs_loop_events(tmp_path):
    log_path = tmp_path / "aijudge.jsonl"
    call_logger = CallLogger(str(log_path))
    inner = MockLLMClient()
    inner.queue_response("PROCEED")
    inner.queue_response("FINAL: Ash Blossom negates that effect. ||CITES: card:1||")
    llm = LoggingLLMClient(inner, call_logger)

    card = {"id": "1", "name": "Ash Blossom & Joyous Spring", "card_type": "Effect Monster"}
    response = _client(
        llm,
        find_matched_cards_fn=lambda question: [card],
        build_known_facts_context_fn=lambda c: "",
        build_grounded_result_fn=lambda c: {"found": True, "id": c["id"], "name": c["name"], "confirmed_effects": []},
        call_logger=call_logger,
    ).post("/questions", json={"question": "What does Ash Blossom do?"})

    assert response.status_code == 200
    with open(log_path, encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    llm_calls = [r for r in records if r["type"] == "llm_call"]
    assert llm_calls[0]["site"] == "clarify"
    assert llm_calls[1]["site"] == "loop"
    assert any(r["type"] == "loop_event" and r["event"] == "answered" for r in records)


def test_post_questions_returns_answer_when_no_clarification_needed():
    llm = MockLLMClient()
    llm.queue_response("PROCEED")
    llm.queue_response("FINAL: Ash Blossom negates that effect. ||CITES: card:1||")

    card = {"id": "1", "name": "Ash Blossom & Joyous Spring", "card_type": "Effect Monster"}
    response = _client(
        llm,
        find_matched_cards_fn=lambda question: [card],
        build_known_facts_context_fn=lambda c: "",
        build_grounded_result_fn=lambda c: {"found": True, "id": c["id"], "name": c["name"], "confirmed_effects": []},
    ).post("/questions", json={"question": "What does Ash Blossom do?"})

    assert response.status_code == 200
    assert response.json() == {
        "status": "answer",
        "text": "Ash Blossom negates that effect.",
        "citations": [{"label": "Ash Blossom & Joyous Spring", "text": ""}],
    }


def test_post_questions_returns_needs_clarification_when_llm_asks():
    llm = MockLLMClient()
    llm.queue_response("CLARIFY: Which card's effect are you asking about?")

    card = {"id": "1", "name": "Some Card", "card_type": "Effect Monster"}
    response = _client(
        llm,
        find_matched_cards_fn=lambda question: [card],
        build_known_facts_context_fn=lambda c: "",
    ).post("/questions", json={"question": "What does it do?"})

    assert response.status_code == 200
    assert response.json() == {
        "status": "needs_clarification",
        "question": "What does it do?",
        "items": [{"kind": "clarify", "text": "Which card's effect are you asking about?"}],
    }


def test_post_questions_skips_the_clarification_call_when_no_card_matches():
    llm = MockLLMClient()
    # Only one response queued -- if the clarify pass ran anyway, it would
    # consume this response itself (leaving run_loop's own call to raise
    # AssertionError on the now-empty queue), so this asserts the skip.
    llm.queue_response("FINAL: It negates a Spell/Trap Card. ||CITES: ||")

    response = _client(llm).post("/questions", json={"question": "what is tearlaments havnis effect?"})

    assert response.status_code == 200
    assert response.json() == {"status": "answer", "text": "It negates a Spell/Trap Card.", "citations": []}


def test_post_questions_passes_the_system_prompt_to_the_clarification_call():
    llm = MockLLMClient()
    llm.queue_response("PROCEED")
    llm.queue_response("FINAL: ok. ||CITES: card:1||")

    card = {"id": "1", "name": "Some Card", "card_type": "Effect Monster"}
    _client(
        llm,
        find_matched_cards_fn=lambda question: [card],
        build_known_facts_context_fn=lambda c: "",
        build_grounded_result_fn=lambda c: {"found": True, "id": c["id"], "name": c["name"], "confirmed_effects": []},
    ).post("/questions", json={"question": "x"})

    assert llm.system_prompts[0] == build_system_prompt()


def test_post_questions_rejects_empty_question():
    llm = MockLLMClient()

    response = _client(llm).post("/questions", json={"question": "   "})

    assert response.status_code == 400
    assert response.json() == {"detail": "question must not be empty"}


def test_post_questions_serializes_citation_content_without_leaking_raw_ids():
    # Grounding now comes from the mandatory card-effect pipeline (no local
    # match -- resolve_card_effect_question_fn stands in for extraction +
    # lookup), not a TOOL: lookup_card call: tools are no longer available
    # to the LLM's answering turn at all.
    llm = MockLLMClient()
    llm.queue_response("FINAL: It negates the effect. ||CITES: card:abc123||")
    llm.queue_response("YES")

    def fake_resolve(question, **kwargs):
        return PipelineResolution(
            supported=True,
            context="KNOWN FACTS: Ash Blossom & Joyous Spring (cite as card:abc123)",
            grounded_cards=[
                {
                    "found": True,
                    "id": "abc123",
                    "name": "Ash Blossom & Joyous Spring",
                    "card_text": "You can discard this card...",
                    "confirmed_effects": [{"effect": "..."}],
                }
            ],
        )

    response = _client(llm, resolve_card_effect_question_fn=fake_resolve).post(
        "/questions", json={"question": "What does Ash Blossom do?"}
    )

    assert response.status_code == 200
    assert response.json()["citations"] == [
        {"label": "Ash Blossom & Joyous Spring", "text": "You can discard this card..."}
    ]
    assert "card:" not in response.text
    assert "abc123" not in response.text


def test_post_questions_route_declares_a_pydantic_response_model():
    # Structural enforcement, not convention: the spec states "the API's
    # Pydantic response models simply don't include an id field, so they
    # can never leak into a JSON response by accident" -- that guarantee
    # requires an actual response_model on the route, not just correct
    # hand-built dicts in _result_response.
    app = create_app(MockLLMClient(), MockEmbeddingClient())
    route = next(r for r in app.routes if getattr(r, "path", None) == "/questions")

    assert route.response_model is not None
    assert route.response_model is not dict


def test_post_questions_answer_route_declares_result_response_model():
    import aijudge.api.schemas as schemas

    app = create_app(MockLLMClient(), MockEmbeddingClient())
    route = next(r for r in app.routes if getattr(r, "path", None) == "/questions/answer")

    assert route.response_model is schemas.ResultResponse


def test_post_questions_response_model_strips_fields_not_declared_on_the_model(monkeypatch):
    # Behavioral proof, not just a structural check: even if _result_response
    # has a bug and includes a stray internal field, the declared
    # response_model must strip it before serialization -- that's the actual
    # leak-prevention guarantee, not merely "some response_model exists."
    import aijudge.api.app as app_module

    llm = MockLLMClient()
    llm.queue_response("FINAL: ok. ||CITES: ||")

    def _leaky_result_response(result):
        return {
            "status": result.kind,
            "text": result.text,
            "citations": result.citations if result.kind == "answer" else None,
            "id": "card:leaked-internal-id",
        }

    monkeypatch.setattr(app_module, "_result_response", _leaky_result_response)

    response = _client(llm).post("/questions", json={"question": "x"})

    assert response.status_code == 200
    assert "id" not in response.json()
    assert "leaked-internal-id" not in response.text


def test_post_questions_cors_allows_configured_origin():
    llm = MockLLMClient()
    llm.queue_response("FINAL: ok. ||CITES: ||")

    client = _client(llm, cors_origins=["http://localhost:5173"])
    response = client.post(
        "/questions",
        json={"question": "x"},
        headers={"Origin": "http://localhost:5173"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_post_questions_folds_known_facts_for_a_single_matched_card_into_the_llm_prompt():
    llm = _CapturingLLMClient(["PROCEED", "FINAL: Yes. ||CITES: card:1||"])

    app = create_app(
        llm,
        MockEmbeddingClient(),
        find_matched_cards_fn=lambda question: [
            {"id": "1", "name": "Baronne de Fleur", "card_type": "Synchro Monster"}
        ],
        build_known_facts_context_fn=lambda card: f"KNOWN FACTS: {card['name']}",
        build_grounded_result_fn=lambda card: {
            "found": True,
            "id": card["id"],
            "name": card["name"],
            "confirmed_effects": [],
        },
    )

    response = TestClient(app).post(
        "/questions", json={"question": "Is Baronne de Fleur usable in the Damage Step?"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "answer"
    assert any("KNOWN FACTS: Baronne de Fleur" in p for p in llm.prompts)


def test_post_questions_passes_known_facts_to_the_clarification_call_for_a_single_match():
    llm = _CapturingLLMClient(["PROCEED", "FINAL: Yes. ||CITES: card:1||"])

    app = create_app(
        llm,
        MockEmbeddingClient(),
        find_matched_cards_fn=lambda question: [
            {"id": "1", "name": "Baronne de Fleur", "card_type": "Synchro Monster"}
        ],
        build_known_facts_context_fn=lambda card: f"KNOWN FACTS: {card['name']}",
        build_grounded_result_fn=lambda card: {
            "found": True,
            "id": card["id"],
            "name": card["name"],
            "confirmed_effects": [],
        },
    )

    response = TestClient(app).post(
        "/questions", json={"question": "Is Baronne de Fleur's effect usable in the Damage Step?"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "answer"
    # The clarification-decision call (prompts[0]) must see the grounding
    # data too, not just the run_loop call -- otherwise the LLM can ask for
    # clarification the deterministic layer already resolved.
    assert "KNOWN FACTS: Baronne de Fleur" in llm.prompts[0]


def test_post_questions_direct_final_answer_citing_the_grounded_id_does_not_escalate():
    # Reproduces the real-world escalation: the LLM answers straight from
    # KNOWN FACTS on the first turn (no lookup_card call), citing the
    # matched card's id. Without grounded_cards pre-registering that id,
    # compute_confidence would treat it as fabricated and escalate.
    llm = _CapturingLLMClient(["PROCEED", "FINAL: It negates that activation. ||CITES: card:1||", "YES"])

    app = create_app(
        llm,
        MockEmbeddingClient(),
        find_matched_cards_fn=lambda question: [
            {"id": "1", "name": "Ghost Belle & Haunted Mansion", "card_type": "Tuner Monster"}
        ],
        build_known_facts_context_fn=lambda card: f"KNOWN FACTS: {card['name']} (cite as card:{card['id']})",
        build_grounded_result_fn=lambda card: {
            "found": True,
            "id": card["id"],
            "name": card["name"],
            "card_text": "Ghost Belle card text.",
            "confirmed_effects": [{"effect": "..."}],
        },
    )

    response = TestClient(app).post(
        "/questions", json={"question": "What does Ghost Belle & Haunted Mansion do?"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "answer"
    assert response.json()["citations"] == [
        {"label": "Ghost Belle & Haunted Mansion", "text": "Ghost Belle card text."}
    ]


def test_post_questions_answer_direct_final_answer_citing_the_grounded_id_does_not_escalate():
    llm = _CapturingLLMClient(["FINAL: It negates that activation. ||CITES: card:1||", "YES"])

    app = create_app(
        llm,
        MockEmbeddingClient(),
        find_matched_cards_fn=lambda question: [
            {"id": "1", "name": "Effect Veiler", "card_type": "Effect Monster"},
            {"id": "2", "name": "Effector", "card_type": "Effect Monster"},
        ],
        build_known_facts_context_fn=lambda card: f"KNOWN FACTS: {card['name']} (cite as card:{card['id']})",
        build_grounded_result_fn=lambda card: {
            "found": True,
            "id": card["id"],
            "name": card["name"],
            "card_text": "Effect Veiler card text.",
            "confirmed_effects": [{"effect": "..."}],
        },
    )

    response = TestClient(app).post(
        "/questions/answer",
        json={
            "question": "Can I chain Effect Veiler or Effector here?",
            "items": [
                {
                    "kind": "disambiguate_card",
                    "text": "Multiple cards match your question: Effect Veiler, Effector. Which one do you mean?",
                }
            ],
            "answers": ["Effect Veiler"],
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "answer"
    assert response.json()["citations"] == [
        {"label": "Effect Veiler", "text": "Effect Veiler card text."}
    ]


def test_post_questions_returns_disambiguate_card_item_when_multiple_cards_match():
    llm = _CapturingLLMClient(["PROCEED"])

    app = create_app(
        llm,
        MockEmbeddingClient(),
        find_matched_cards_fn=lambda question: [
            {"id": "1", "name": "Effect Veiler", "card_type": "Effect Monster"},
            {"id": "2", "name": "Effector", "card_type": "Effect Monster"},
        ],
    )

    response = TestClient(app).post(
        "/questions", json={"question": "Can I chain Effect Veiler or Effector here?"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "needs_clarification",
        "question": "Can I chain Effect Veiler or Effector here?",
        "items": [
            {
                "kind": "disambiguate_card",
                "text": "Multiple cards match your question: Effect Veiler, Effector. Which one do you mean?",
            }
        ],
    }


def test_post_questions_answer_resolves_disambiguation_answer_to_known_facts():
    llm = _CapturingLLMClient(["FINAL: Yes. ||CITES: card:1||"])

    app = create_app(
        llm,
        MockEmbeddingClient(),
        find_matched_cards_fn=lambda question: [
            {"id": "1", "name": "Effect Veiler", "card_type": "Effect Monster"},
            {"id": "2", "name": "Effector", "card_type": "Effect Monster"},
        ],
        build_known_facts_context_fn=lambda card: f"KNOWN FACTS: {card['name']}",
        build_grounded_result_fn=lambda card: {
            "found": True,
            "id": card["id"],
            "name": card["name"],
            "confirmed_effects": [],
        },
    )

    response = TestClient(app).post(
        "/questions/answer",
        json={
            "question": "Can I chain Effect Veiler or Effector here?",
            "items": [
                {
                    "kind": "disambiguate_card",
                    "text": "Multiple cards match your question: Effect Veiler, Effector. Which one do you mean?",
                }
            ],
            "answers": ["Effect Veiler"],
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "answer"
    assert any("KNOWN FACTS: Effect Veiler" in p for p in llm.prompts)


def test_post_questions_answer_resolves_disambiguation_answer_case_insensitive_fuzzy():
    llm = _CapturingLLMClient(["FINAL: Yes. ||CITES: card:1||"])

    app = create_app(
        llm,
        MockEmbeddingClient(),
        find_matched_cards_fn=lambda question: [
            {"id": "1", "name": "Effect Veiler", "card_type": "Effect Monster"},
            {"id": "2", "name": "Effector", "card_type": "Effect Monster"},
        ],
        build_known_facts_context_fn=lambda card: f"KNOWN FACTS: {card['name']}",
        build_grounded_result_fn=lambda card: {
            "found": True,
            "id": card["id"],
            "name": card["name"],
            "confirmed_effects": [],
        },
    )

    response = TestClient(app).post(
        "/questions/answer",
        json={
            "question": "Can I chain Effect Veiler or Effector here?",
            "items": [
                {
                    "kind": "disambiguate_card",
                    "text": "Multiple cards match your question: Effect Veiler, Effector. Which one do you mean?",
                }
            ],
            "answers": ["effect veiler"],
        },
    )

    assert response.status_code == 200
    assert any("KNOWN FACTS: Effect Veiler" in p for p in llm.prompts)


def test_post_questions_answer_falls_back_to_pipeline_when_disambiguation_answer_matches_nothing_and_pipeline_unsupported():
    # A disambiguation-miss (matches > 1 but the answer didn't fuzzy-resolve)
    # must NOT fall through to run_loop ungrounded -- that reproduces the
    # exact bug shape this branch exists to close (an uncited answer scoring
    # confidence 1.0). It must fall back to the same mandatory pipeline as a
    # 0-local-matches question. Here the pipeline reports unsupported, so
    # not_supported is returned and run_loop is never reached.
    llm = _CapturingLLMClient([])

    app = create_app(
        llm,
        MockEmbeddingClient(),
        find_matched_cards_fn=lambda question: [
            {"id": "1", "name": "Effect Veiler", "card_type": "Effect Monster"},
            {"id": "2", "name": "Effector", "card_type": "Effect Monster"},
        ],
        build_known_facts_context_fn=lambda card: f"KNOWN FACTS: {card['name']}",
        resolve_card_effect_question_fn=lambda question, **kw: PipelineResolution(supported=False),
    )

    response = TestClient(app).post(
        "/questions/answer",
        json={
            "question": "Can I chain Effect Veiler or Effector here?",
            "items": [
                {
                    "kind": "disambiguate_card",
                    "text": "Multiple cards match your question: Effect Veiler, Effector. Which one do you mean?",
                }
            ],
            "answers": ["I have no idea what you mean"],
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "not_supported"
    assert not any("KNOWN FACTS" in p for p in llm.prompts)


def test_post_questions_answer_falls_back_to_pipeline_when_disambiguation_answer_matches_nothing_and_pipeline_supported():
    # Same disambiguation-miss, but the fallback pipeline DOES resolve a
    # card -- its context/grounded_cards must reach run_loop so the final
    # answer is grounded, instead of the LLM answering ungrounded.
    llm = _CapturingLLMClient(["FINAL: It does the thing. ||CITES: card:99||", "YES"])

    app = create_app(
        llm,
        MockEmbeddingClient(),
        find_matched_cards_fn=lambda question: [
            {"id": "1", "name": "Effect Veiler", "card_type": "Effect Monster"},
            {"id": "2", "name": "Effector", "card_type": "Effect Monster"},
        ],
        build_known_facts_context_fn=lambda card: f"KNOWN FACTS: {card['name']}",
        resolve_card_effect_question_fn=lambda question, **kw: PipelineResolution(
            supported=True,
            context="KNOWN FACTS: Some New Card (cite as card:99)",
            grounded_cards=[
                {
                    "found": True,
                    "id": "99",
                    "name": "Some New Card",
                    "card_text": "...",
                    "confirmed_effects": [{"effect": "..."}],
                }
            ],
        ),
    )

    response = TestClient(app).post(
        "/questions/answer",
        json={
            "question": "Can I chain Effect Veiler or Effector here?",
            "items": [
                {
                    "kind": "disambiguate_card",
                    "text": "Multiple cards match your question: Effect Veiler, Effector. Which one do you mean?",
                }
            ],
            "answers": ["I have no idea what you mean"],
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "answer"
    assert response.json()["text"] == "It does the thing."
    assert any("KNOWN FACTS: Some New Card" in p for p in llm.prompts)


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


class _RecordingLLMClient:
    """Records every prompt it's called with, unlike MockLLMClient which
    ignores `prompt` entirely -- needed to prove post_answer actually
    threads clarification_context into the prompt sent to the LLM, not
    just that some hardcoded response comes back regardless.
    """

    def __init__(self, response: str):
        self._response = response
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        self.prompts.append(prompt)
        return self._response


def test_post_questions_answer_threads_clarification_context_into_llm_prompt():
    llm = _RecordingLLMClient("FINAL: Yes, it does that. ||CITES: ||")

    response = TestClient(
        create_app(
            llm,
            MockEmbeddingClient(),
            find_matched_cards_fn=lambda question: [],
            resolve_card_effect_question_fn=lambda question, **kw: PipelineResolution(supported=True),
        )
    ).post(
        "/questions/answer",
        json={
            "question": "Is X active?",
            "items": [{"kind": "continuous_check", "text": "Some Card"}],
            "answers": ["Yes, Ash Blossom is on the field."],
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "answer", "text": "Yes, it does that.", "citations": []}
    assert len(llm.prompts) == 1
    assert "Yes, Ash Blossom is on the field." in llm.prompts[-1]


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
    def complete(self, prompt: str, *, system: str | None = None) -> str:
        raise requests.exceptions.ConnectionError("no route to host")


class _BrokenLLMClient:
    def complete(self, prompt: str, *, system: str | None = None) -> str:
        raise RuntimeError("something internal broke")


def test_post_questions_returns_503_when_llm_backend_unreachable():
    app = create_app(_ConnectionErrorLLMClient(), MockEmbeddingClient(), find_matched_cards_fn=lambda question: [])
    client = TestClient(app)

    response = client.post("/questions", json={"question": "What does Ash Blossom do?"})

    assert response.status_code == 503
    assert response.json() == {"detail": "backend unavailable"}


def test_post_questions_returns_generic_500_without_leaking_exception_details():
    app = create_app(_BrokenLLMClient(), MockEmbeddingClient(), find_matched_cards_fn=lambda question: [])
    # ServerErrorMiddleware re-raises after building the response, specifically so
    # unhandled errors stay visible to the ASGI server/logs -- TestClient must be
    # told not to propagate that re-raised exception into the test itself.
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/questions", json={"question": "What does Ash Blossom do?"})

    assert response.status_code == 500
    assert response.json() == {"detail": "internal server error"}
    assert "something internal broke" not in response.text


def test_post_questions_generic_500_response_still_carries_cors_headers():
    # Regression test: a handler registered for the bare `Exception` type is
    # special-cased by Starlette to run in ServerErrorMiddleware, which wraps
    # *outside* all user middleware including CORSMiddleware -- so its
    # response used to reach the browser with no Access-Control-Allow-Origin
    # header at all. The browser then reports a generic network/CORS failure
    # instead of surfacing the real 500, which is exactly what a real 400
    # from the Anthropic API (e.g. an exhausted credit balance) looked like
    # from the frontend: "network error: could not reach the backend".
    app = create_app(
        _BrokenLLMClient(),
        MockEmbeddingClient(),
        find_matched_cards_fn=lambda question: [],
        cors_origins=["http://localhost:5173"],
    )
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/questions",
        json={"question": "What does Ash Blossom do?"},
        headers={"Origin": "http://localhost:5173"},
    )

    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


class _OperationalErrorLLMClient:
    def complete(self, prompt: str, *, system: str | None = None) -> str:
        raise psycopg.OperationalError("could not connect to server")


def test_post_questions_returns_503_when_db_backend_unreachable():
    app = create_app(_OperationalErrorLLMClient(), MockEmbeddingClient(), find_matched_cards_fn=lambda question: [])
    client = TestClient(app)

    response = client.post("/questions", json={"question": "What does Ash Blossom do?"})

    assert response.status_code == 503
    assert response.json() == {"detail": "backend unavailable"}


def _exc_log_records(caplog, logger_name: str = "aijudge.api.app") -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == logger_name]


def test_post_questions_503_logs_the_actual_exception_traceback(caplog):
    app = create_app(_ConnectionErrorLLMClient(), MockEmbeddingClient(), find_matched_cards_fn=lambda question: [])
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
    app = create_app(_BrokenLLMClient(), MockEmbeddingClient(), find_matched_cards_fn=lambda question: [])
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


def test_create_app_defaults_online_ingest_enabled_to_true():
    captured = {}

    def fake_resolve(question, *, llm_client, online_ingest_enabled, on_ingest_start):
        captured["online_ingest_enabled"] = online_ingest_enabled
        return PipelineResolution(supported=False)

    app = create_app(
        MockLLMClient(),
        MockEmbeddingClient(),
        find_matched_cards_fn=lambda question: [],
        resolve_card_effect_question_fn=fake_resolve,
    )
    TestClient(app).post("/questions", json={"question": "What does Some New Card do?"})

    assert captured["online_ingest_enabled"] is True


def test_create_app_passes_online_ingest_enabled_false_through():
    captured = {}

    def fake_resolve(question, *, llm_client, online_ingest_enabled, on_ingest_start):
        captured["online_ingest_enabled"] = online_ingest_enabled
        return PipelineResolution(supported=False)

    app = create_app(
        MockLLMClient(),
        MockEmbeddingClient(),
        online_ingest_enabled=False,
        find_matched_cards_fn=lambda question: [],
        resolve_card_effect_question_fn=fake_resolve,
    )
    TestClient(app).post("/questions", json={"question": "What does Some New Card do?"})

    assert captured["online_ingest_enabled"] is False
