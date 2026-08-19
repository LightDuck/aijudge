from aijudge.llm.client import MockLLMClient
from aijudge.orchestration.loop import run_loop
from aijudge.rules_engine.resolve import UnsupportedScenarioError


def test_final_answer_with_no_tool_calls_returns_answer():
    llm = MockLLMClient()
    llm.queue_response("FINAL: Ash Blossom negates that effect. ||CITES: ||")

    result = run_loop("What does Ash Blossom do?", llm_client=llm, tools={})

    assert result.kind == "answer"
    assert result.text == "Ash Blossom negates that effect."


def test_tool_call_then_final_answer_cites_the_returned_id():
    llm = MockLLMClient()
    llm.queue_response('TOOL: lookup_card {"name": "Ash Blossom & Joyous Spring"}')
    llm.queue_response("FINAL: It negates the effect. ||CITES: card:abc123||")

    tools = {"lookup_card": lambda args: {"found": True, "id": "abc123", "confirmed_effect": {"effect": "..."}}}

    result = run_loop("What does Ash Blossom do?", llm_client=llm, tools=tools)

    assert result.kind == "answer"
    assert result.text == "It negates the effect."


def test_fabricated_citation_escalates():
    llm = MockLLMClient()
    llm.queue_response("FINAL: It negates the effect. ||CITES: card:never-looked-up||")

    result = run_loop("What does Ash Blossom do?", llm_client=llm, tools={})

    assert result.kind == "escalate"


def test_retrieval_gap_lowers_confidence_below_threshold():
    llm = MockLLMClient()
    llm.queue_response('TOOL: search_rulebook {"query": "obscure ruling"}')
    llm.queue_response("FINAL: I could not find a direct source. ||CITES: ||")

    tools = {"search_rulebook": lambda args: {"chunks": []}}

    result = run_loop("An obscure ruling question", llm_client=llm, tools=tools, threshold=0.95)

    assert result.kind == "escalate"


def test_unsupported_scenario_error_from_resolve_chain_short_circuits():
    llm = MockLLMClient()
    llm.queue_response(
        'TOOL: resolve_chain {"turn_player": "player_a", "steps": [{"kind": "replay"}]}'
    )

    def _raise(args):
        raise UnsupportedScenarioError("replay steps aren't modeled yet")

    result = run_loop("Resolve this weird replay scenario", llm_client=llm, tools={"resolve_chain": _raise})

    assert result.kind == "not_supported"


def test_malformed_responses_exhausted_surfaces_not_supported():
    llm = MockLLMClient()
    for _ in range(4):
        llm.queue_response("I am not following the protocol.")

    result = run_loop("A confusing question", llm_client=llm, tools={})

    assert result.kind == "not_supported"
