from aijudge.llm.client import MockLLMClient
from aijudge.orchestration.loop import MAX_VERIFICATION_RETRIES, run_loop
from aijudge.orchestration.protocol import build_system_prompt
from aijudge.orchestration.verify import VERIFIER_SYSTEM_PROMPT
from aijudge.rules_engine.resolve import UnsupportedScenarioError


class _CapturingLLMClient:
    """A FIFO-response fake that also records every prompt it receives, so
    tests can assert on what actually reached the LLM (MockLLMClient only
    records `system_prompts`, not the `prompt` argument itself)."""

    def __init__(self, responses):
        self._queue = list(responses)
        self.prompts = []

    def complete(self, prompt, *, system=None):
        self.prompts.append(prompt)
        return self._queue.pop(0)


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
    llm.queue_response("YES")

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
    llm.queue_response("YES")

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
    llm.queue_response("YES")

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
    llm.queue_response("YES")

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


def test_grounded_cards_preseed_known_ids_so_direct_final_answer_is_not_fabricated():
    # Reproduces the KNOWN-FACTS-shortcut escalation: preflight already gave
    # the LLM everything it needs, so it answers FINAL on the very first
    # turn without ever calling lookup_card. Without a legitimate id to
    # cite, the LLM fabricates one and compute_confidence correctly flags
    # it -- unless the caller pre-registers the already-grounded card's id
    # via `grounded_cards`, exactly as if lookup_card had returned it.
    llm = MockLLMClient()
    llm.queue_response("FINAL: It negates the effect. ||CITES: card:abc123||")
    llm.queue_response("YES")

    grounded = [
        {
            "found": True,
            "id": "abc123",
            "name": "Ash Blossom & Joyous Spring",
            "card_text": "You can discard this card...",
            "confirmed_effects": [{"effect": "..."}],
        }
    ]

    result = run_loop("What does Ash Blossom do?", llm_client=llm, tools={}, grounded_cards=grounded)

    assert result.kind == "answer"
    assert result.citations == [
        {"label": "Ash Blossom & Joyous Spring", "text": "You can discard this card..."}
    ]


def test_grounded_cards_defaults_to_no_preseeding():
    # Without grounded_cards, behavior is unchanged from before this
    # parameter existed -- a citation with no matching tool call still
    # fabricates and escalates.
    llm = MockLLMClient()
    llm.queue_response("FINAL: It negates the effect. ||CITES: card:abc123||")

    result = run_loop("What does Ash Blossom do?", llm_client=llm, tools={})

    assert result.kind == "escalate"


def test_run_loop_passes_the_system_prompt_on_every_llm_call():
    llm = MockLLMClient()
    llm.queue_response('TOOL: lookup_card {"name": "Ash Blossom & Joyous Spring"}')
    llm.queue_response("FINAL: It negates the effect. ||CITES: card:abc123||")
    llm.queue_response("YES")

    tools = {"lookup_card": lambda args: {"found": True, "id": "abc123", "confirmed_effects": [{"effect": "..."}]}}

    run_loop("What does Ash Blossom do?", llm_client=llm, tools=tools)

    assert llm.system_prompts == [build_system_prompt(), build_system_prompt(), VERIFIER_SYSTEM_PROMPT]


def test_structured_grounding_mismatch_retries_then_succeeds():
    llm = MockLLMClient()
    llm.queue_response('TOOL: lookup_card {"name": "Tearlaments Sulliek"}')
    llm.queue_response("FINAL: It negates the effect of the target spell or trap card. ||CITES: card:abc123||")
    llm.queue_response("NO")
    llm.queue_response("FINAL: It negates the effects of the targeted Effect Monster. ||CITES: card:abc123||")
    llm.queue_response("YES")

    tools = {
        "lookup_card": lambda args: {
            "found": True,
            "id": "abc123",
            "name": "Tearlaments Sulliek",
            "card_text": "...",
            "confirmed_effects": [
                {"effect": "Target 1 Effect Monster your opponent controls; negate its effects."}
            ],
        }
    }

    result = run_loop("What does Tearlaments Sulliek's first effect do?", llm_client=llm, tools=tools)

    assert result.kind == "answer"
    assert result.text == "It negates the effects of the targeted Effect Monster."


def test_structured_grounding_mismatch_exhausts_retries_and_escalates():
    llm = MockLLMClient()
    llm.queue_response('TOOL: lookup_card {"name": "Tearlaments Sulliek"}')
    for _ in range(MAX_VERIFICATION_RETRIES + 1):
        llm.queue_response("FINAL: It negates the effect of the target spell or trap card. ||CITES: card:abc123||")
        llm.queue_response("NO")

    tools = {
        "lookup_card": lambda args: {
            "found": True,
            "id": "abc123",
            "confirmed_effects": [
                {"effect": "Target 1 Effect Monster your opponent controls; negate its effects."}
            ],
        }
    }

    result = run_loop("What does Tearlaments Sulliek's first effect do?", llm_client=llm, tools=tools)

    assert result.kind == "escalate"


def test_verification_failed_feedback_includes_card_name_effect_text_and_prior_draft():
    # Finding 2: the feedback message must show the model its own prior
    # (wrong) draft, not just tell it "you were wrong". Finding 7 (bundled):
    # it should name the card by its human-readable name, not the raw
    # citation id.
    llm = _CapturingLLMClient([
        'TOOL: lookup_card {"name": "Tearlaments Sulliek"}',
        "FINAL: It negates the effect of the target spell or trap card. ||CITES: card:abc123||",
        "NO",
        "FINAL: It negates the effects of the targeted Effect Monster. ||CITES: card:abc123||",
        "YES",
    ])

    tools = {
        "lookup_card": lambda args: {
            "found": True,
            "id": "abc123",
            "name": "Tearlaments Sulliek",
            "card_text": "...",
            "confirmed_effects": [
                {"effect": "Target 1 Effect Monster your opponent controls; negate its effects."}
            ],
        }
    }

    result = run_loop("What does Tearlaments Sulliek's first effect do?", llm_client=llm, tools=tools)

    assert result.kind == "answer"
    feedback_prompt = next(p for p in llm.prompts if "VERIFICATION_FAILED" in p)
    assert "Tearlaments Sulliek" in feedback_prompt
    assert "card:abc123" not in feedback_prompt.split("VERIFICATION_FAILED", 1)[1]
    assert "Target 1 Effect Monster your opponent controls; negate its effects." in feedback_prompt
    assert "It negates the effect of the target spell or trap card." in feedback_prompt


def test_redraft_dropping_flagged_citation_is_treated_as_another_verification_failure_then_recovers():
    # Finding 3: a redraft that responds with no citations at all (or drops
    # the specific card(s) that just failed verification) must not silently
    # bypass the gate. verify_structured_grounding alone would find nothing
    # to check for an empty CITES and return ok=True -- this reproduces that
    # bypass and confirms the fix treats it as another failed verification
    # attempt under the same retry budget, which can still recover.
    llm = MockLLMClient()
    llm.queue_response('TOOL: lookup_card {"name": "Tearlaments Sulliek"}')
    llm.queue_response("FINAL: It negates the effect of the target spell or trap card. ||CITES: card:abc123||")
    llm.queue_response("NO")
    llm.queue_response("FINAL: It negates something, not sure what. ||CITES: ||")
    llm.queue_response("FINAL: It negates the effects of the targeted Effect Monster. ||CITES: card:abc123||")
    llm.queue_response("YES")

    tools = {
        "lookup_card": lambda args: {
            "found": True,
            "id": "abc123",
            "name": "Tearlaments Sulliek",
            "card_text": "...",
            "confirmed_effects": [
                {"effect": "Target 1 Effect Monster your opponent controls; negate its effects."}
            ],
        }
    }

    result = run_loop("What does Tearlaments Sulliek's first effect do?", llm_client=llm, tools=tools)

    assert result.kind == "answer"
    assert result.text == "It negates the effects of the targeted Effect Monster."


def test_redraft_dropping_flagged_citation_repeatedly_exhausts_budget_and_escalates():
    # Companion to the above: if the redraft keeps dropping the flagged
    # citation rather than ever re-citing it, the bypass-detection must
    # still respect MAX_VERIFICATION_RETRIES and escalate rather than loop
    # forever or silently return an ungrounded answer.
    llm = MockLLMClient()
    llm.queue_response('TOOL: lookup_card {"name": "Tearlaments Sulliek"}')
    llm.queue_response("FINAL: It negates the effect of the target spell or trap card. ||CITES: card:abc123||")
    llm.queue_response("NO")
    for _ in range(MAX_VERIFICATION_RETRIES):
        llm.queue_response("FINAL: It negates something, not sure what. ||CITES: ||")

    tools = {
        "lookup_card": lambda args: {
            "found": True,
            "id": "abc123",
            "name": "Tearlaments Sulliek",
            "card_text": "...",
            "confirmed_effects": [
                {"effect": "Target 1 Effect Monster your opponent controls; negate its effects."}
            ],
        }
    }

    result = run_loop("What does Tearlaments Sulliek's first effect do?", llm_client=llm, tools=tools)

    assert result.kind == "escalate"
