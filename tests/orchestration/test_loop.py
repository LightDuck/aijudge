from aijudge.llm.client import MockLLMClient
from aijudge.orchestration.loop import run_loop
from aijudge.orchestration.protocol import build_system_prompt
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

    tools = {"lookup_card": lambda args: {"found": True, "id": "abc123", "confirmed_effects": [{"effect": "..."}]}}

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


def test_refusal_returns_off_topic_result():
    llm = MockLLMClient()
    llm.queue_response("REFUSE: This assistant only answers Yu-Gi-Oh! TCG rules questions.")

    result = run_loop("What's the capital of France?", llm_client=llm, tools={})

    assert result.kind == "off_topic"
    assert result.text == "This assistant only answers Yu-Gi-Oh! TCG rules questions."


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


def test_tool_call_loop_gives_up_after_max_tool_calls():
    llm = MockLLMClient()
    for _ in range(20):
        llm.queue_response('TOOL: lookup_card {"name": "Ash Blossom & Joyous Spring"}')

    tools = {"lookup_card": lambda args: {"found": True, "id": "abc123", "confirmed_effects": []}}

    result = run_loop("What does this do?", llm_client=llm, tools=tools)

    assert result.kind == "not_supported"


def test_malformed_tool_arguments_are_recoverable():
    llm = MockLLMClient()
    llm.queue_response("TOOL: lookup_card {}")
    llm.queue_response('TOOL: lookup_card {"name": "Ash Blossom & Joyous Spring"}')
    llm.queue_response("FINAL: It negates the effect. ||CITES: card:abc123||")

    def _lookup(args):
        return {"found": True, "id": "abc123", "confirmed_effects": [{"effect": "..."}], "name": args["name"]}

    result = run_loop("What does Ash Blossom do?", llm_client=llm, tools={"lookup_card": _lookup})

    assert result.kind == "answer"


def test_malformed_tool_arguments_exhausted_surfaces_not_supported():
    llm = MockLLMClient()
    for _ in range(5):
        llm.queue_response("TOOL: lookup_card {}")

    def _lookup(args):
        return {"found": True, "id": "abc123", "confirmed_effects": [], "name": args["name"]}

    result = run_loop("What does Ash Blossom do?", llm_client=llm, tools={"lookup_card": _lookup})

    assert result.kind == "not_supported"


def test_tool_call_then_final_answer_includes_citation_text():
    llm = MockLLMClient()
    llm.queue_response('TOOL: lookup_card {"name": "Ash Blossom & Joyous Spring"}')
    llm.queue_response("FINAL: It negates the effect. ||CITES: card:abc123||")

    tools = {
        "lookup_card": lambda args: {
            "found": True,
            "id": "abc123",
            "name": "Ash Blossom & Joyous Spring",
            "card_text": "You can discard this card...",
            "confirmed_effects": [{"effect": "..."}],
        }
    }

    result = run_loop("What does Ash Blossom do?", llm_client=llm, tools=tools)

    assert result.kind == "answer"
    assert result.citations == [
        {"label": "Ash Blossom & Joyous Spring", "text": "You can discard this card..."}
    ]


def test_final_answer_with_no_citations_has_empty_citations_list():
    llm = MockLLMClient()
    llm.queue_response("FINAL: Ash Blossom negates that effect. ||CITES: ||")

    result = run_loop("What does Ash Blossom do?", llm_client=llm, tools={})

    assert result.citations == []


def test_escalated_answer_has_empty_citations_list():
    llm = MockLLMClient()
    llm.queue_response("FINAL: It negates the effect. ||CITES: card:never-looked-up||")

    result = run_loop("What does Ash Blossom do?", llm_client=llm, tools={})

    assert result.kind == "escalate"
    assert result.citations == []


def test_multiple_citations_are_sorted_by_id():
    llm = MockLLMClient()
    llm.queue_response('TOOL: lookup_card {"name": "Card Z"}')
    llm.queue_response('TOOL: lookup_card {"name": "Card A"}')
    llm.queue_response("FINAL: Both cards matter. ||CITES: card:z9, card:a1||")

    def lookup_tool(args):
        name = args.get("name", "")
        if "Z" in name:
            return {
                "found": True,
                "id": "z9",
                "name": "Card Z",
                "card_text": "Card Z text",
                "confirmed_effects": [{"effect": "..."}],
            }
        else:
            return {
                "found": True,
                "id": "a1",
                "name": "Card A",
                "card_text": "Card A text",
                "confirmed_effects": [{"effect": "..."}],
            }

    result = run_loop("Compare Card Z and Card A", llm_client=llm, tools={"lookup_card": lookup_tool})

    assert result.kind == "answer"
    # Citations should be sorted by ID, so card:a1 before card:z9 (not in lookup order)
    assert result.citations == [
        {"label": "Card A", "text": "Card A text"},
        {"label": "Card Z", "text": "Card Z text"},
    ]


def test_run_loop_passes_the_system_prompt_on_every_llm_call():
    llm = MockLLMClient()
    llm.queue_response('TOOL: lookup_card {"name": "Ash Blossom & Joyous Spring"}')
    llm.queue_response("FINAL: It negates the effect. ||CITES: card:abc123||")

    tools = {
        "lookup_card": lambda args: {"found": True, "id": "abc123", "confirmed_effects": [{"effect": "..."}]},
        "get_rulings": lambda args: {"rulings": []},
        "search_rulebook": lambda args: {"chunks": []},
        "resolve_chain": lambda args: {},
    }

    run_loop("What does Ash Blossom do?", llm_client=llm, tools=tools)

    expected = build_system_prompt(available_tools=set(tools))
    assert llm.system_prompts == [expected, expected]


def test_run_loop_only_advertises_the_tools_actually_in_the_dispatch():
    llm = MockLLMClient()
    llm.queue_response("FINAL: It does not deal with rulings. ||CITES: ||")

    tools = {"lookup_card": lambda args: {"found": False}}

    run_loop("What does Ash Blossom do?", llm_client=llm, tools=tools)

    assert "lookup_card" in llm.system_prompts[0]
    assert "get_rulings" not in llm.system_prompts[0]
