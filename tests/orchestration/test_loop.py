import json

from aijudge.call_log import CallLogger
from aijudge.llm.client import MockLLMClient
from aijudge.orchestration.loop import MAX_VERIFICATION_RETRIES, run_loop
from aijudge.orchestration.protocol import build_system_prompt
from aijudge.orchestration.verify import VERIFIER_SYSTEM_PROMPT
from aijudge.rules_engine.resolve import UnsupportedScenarioError


def _read_loop_events(path):
    with open(path, encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    return [r for r in records if r["type"] == "loop_event"]


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
    # search_rulebook is temporarily disabled (pipeline instability); get_rulings
    # exercises the same retrieval-gap-penalty mechanism in confidence.py.
    llm = MockLLMClient()
    llm.queue_response('TOOL: get_rulings {"card_id": "abc123"}')
    llm.queue_response("FINAL: I could not find a direct source. ||CITES: ||")

    tools = {"get_rulings": lambda args: {"rulings": []}}

    result = run_loop("An obscure ruling question", llm_client=llm, tools=tools, threshold=0.95)

    assert result.kind == "escalate"


def test_refusal_returns_off_topic_result():
    llm = MockLLMClient()
    llm.queue_response("REFUSE: This assistant only answers Yu-Gi-Oh! TCG rules questions.")

    result = run_loop("What's the capital of France?", llm_client=llm, tools={})

    assert result.kind == "off_topic"
    assert result.text == "This assistant only answers Yu-Gi-Oh! TCG rules questions."


def test_unsupported_scenario_error_from_a_tool_call_short_circuits():
    # resolve_chain is temporarily disabled (pipeline instability); lookup_card
    # is a stand-in here to exercise run_loop's generic short-circuit on
    # UnsupportedScenarioError from any tool call.
    llm = MockLLMClient()
    llm.queue_response(
        'TOOL: lookup_card {"name": "some weird replay scenario"}'
    )

    def _raise(args):
        raise UnsupportedScenarioError("replay steps aren't modeled yet")

    result = run_loop("Resolve this weird replay scenario", llm_client=llm, tools={"lookup_card": _raise})

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


def test_tool_call_against_empty_tool_dispatch_degrades_to_not_supported_not_a_crash():
    # tools={} is the restricted answering pathway used by cli.py/api/app.py
    # now. parse_response validates a TOOL: line's name against the static
    # TOOL_NAMES set, not against whatever `tools` dict was actually passed
    # to run_loop -- so an LLM emitting a TOOL: line here must not raise an
    # uncaught KeyError out of run_loop; it should be treated like any other
    # malformed/tool-arg-error retry and eventually degrade to not_supported.
    llm = MockLLMClient()
    for _ in range(5):
        llm.queue_response('TOOL: lookup_card {"name": "Ash Blossom & Joyous Spring"}')

    result = run_loop("What does Ash Blossom do?", llm_client=llm, tools={})

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


def test_grounded_card_cited_without_card_prefix_still_answers():
    # Reproduces a real false-positive escalation seen with Qwen3-8B via
    # Ollama: the KNOWN FACTS prompt tells the model to cite card:abc123, but
    # its ||CITES: ...|| trailer drops the "card:" prefix and cites the bare
    # internal id instead. compute_confidence used to treat that as an
    # unrecognized (fabricated-looking) citation and escalate a correct,
    # grounded answer.
    llm = MockLLMClient()
    llm.queue_response("FINAL: It negates the effect. ||CITES: abc123||")
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


def test_redraft_dropping_citation_entirely_after_verification_failure_escalates_immediately():
    # Behavior change from the hardened compute_confidence rule (Task 5):
    # previously a redraft that dropped the flagged citation entirely
    # (||CITES: ||) got one more chance via the verify_structured_grounding
    # bypass-detection path below (it trivially "passes" verification when
    # there's nothing cited to check, and the loop used to treat that as
    # another correctable verification failure). Now that compute_confidence
    # hard-fails any answer citing nothing while known_ids is populated
    # (closing the "cite nothing to dodge grounding checks" gap for good),
    # that citation-drop is caught earlier, at the confidence gate itself --
    # before verification, and its bypass-detection recovery, ever runs
    # again.
    llm = MockLLMClient()
    llm.queue_response('TOOL: lookup_card {"name": "Tearlaments Sulliek"}')
    llm.queue_response("FINAL: It negates the effect of the target spell or trap card. ||CITES: card:abc123||")
    llm.queue_response("NO")
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


def test_redraft_dropping_flagged_citation_repeatedly_exhausts_budget_and_escalates():
    # Companion to the above: repeatedly dropping the citation still ends
    # in escalate -- now via the hardened compute_confidence rule firing on
    # the very first empty-citation redraft (Task 5), rather than via
    # MAX_VERIFICATION_RETRIES exhaustion as before. The assertion is
    # unchanged; only *why* it escalates changed.
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


def test_run_loop_uses_default_system_prompt_when_none_given():
    llm = MockLLMClient()
    llm.queue_response("FINAL: ok. ||CITES: ||")

    run_loop("A question", llm_client=llm, tools={})

    assert llm.system_prompts == [build_system_prompt()]


def test_run_loop_uses_provided_system_prompt_override():
    llm = MockLLMClient()
    llm.queue_response("FINAL: ok. ||CITES: ||")

    run_loop("A question", llm_client=llm, tools={}, system_prompt="CUSTOM PROMPT")

    assert llm.system_prompts == ["CUSTOM PROMPT"]


def test_run_loop_without_call_logger_does_not_crash():
    # call_logger defaults to None -- every existing caller (and test above)
    # relies on this staying a no-op rather than requiring the parameter.
    llm = MockLLMClient()
    llm.queue_response("FINAL: ok. ||CITES: ||")

    result = run_loop("A question", llm_client=llm, tools={})

    assert result.kind == "answer"


def test_run_loop_logs_answered_event(tmp_path):
    log_path = tmp_path / "aijudge.jsonl"
    call_logger = CallLogger(str(log_path))
    llm = MockLLMClient()
    llm.queue_response("FINAL: ok. ||CITES: ||")

    run_loop("A question", llm_client=llm, tools={}, call_logger=call_logger)

    events = _read_loop_events(log_path)
    assert events[-1]["event"] == "answered"
    assert events[-1]["site"] == "loop"


def test_run_loop_logs_malformed_response_event(tmp_path):
    log_path = tmp_path / "aijudge.jsonl"
    call_logger = CallLogger(str(log_path))
    llm = MockLLMClient()
    llm.queue_response("I am not following the protocol.")
    llm.queue_response("FINAL: ok. ||CITES: ||")

    run_loop("A question", llm_client=llm, tools={}, call_logger=call_logger)

    events = _read_loop_events(log_path)
    assert any(e["event"] == "malformed_response" for e in events)


def test_run_loop_logs_not_supported_event_on_malformed_retry_budget_exceeded(tmp_path):
    log_path = tmp_path / "aijudge.jsonl"
    call_logger = CallLogger(str(log_path))
    llm = MockLLMClient()
    for _ in range(4):
        llm.queue_response("I am not following the protocol.")

    run_loop("A confusing question", llm_client=llm, tools={}, call_logger=call_logger)

    events = _read_loop_events(log_path)
    assert events[-1]["event"] == "not_supported"
    assert events[-1]["reason"]


def test_run_loop_logs_tool_error_event(tmp_path):
    log_path = tmp_path / "aijudge.jsonl"
    call_logger = CallLogger(str(log_path))
    llm = MockLLMClient()
    llm.queue_response("TOOL: lookup_card {}")
    llm.queue_response('TOOL: lookup_card {"name": "Ash Blossom & Joyous Spring"}')
    llm.queue_response("FINAL: It negates the effect. ||CITES: card:abc123||")
    llm.queue_response("YES")

    def _lookup(args):
        return {"found": True, "id": "abc123", "confirmed_effects": [{"effect": "..."}], "name": args["name"]}

    run_loop("What does Ash Blossom do?", llm_client=llm, tools={"lookup_card": _lookup}, call_logger=call_logger)

    events = _read_loop_events(log_path)
    assert any(e["event"] == "tool_error" for e in events)


def test_run_loop_logs_off_topic_event(tmp_path):
    log_path = tmp_path / "aijudge.jsonl"
    call_logger = CallLogger(str(log_path))
    llm = MockLLMClient()
    llm.queue_response("REFUSE: This assistant only answers Yu-Gi-Oh! TCG rules questions.")

    run_loop("What's the capital of France?", llm_client=llm, tools={}, call_logger=call_logger)

    events = _read_loop_events(log_path)
    assert events[-1]["event"] == "off_topic"


def test_run_loop_logs_escalate_event_with_score_and_threshold(tmp_path):
    log_path = tmp_path / "aijudge.jsonl"
    call_logger = CallLogger(str(log_path))
    # search_rulebook is temporarily disabled (pipeline instability); get_rulings
    # exercises the same retrieval-gap-penalty mechanism in confidence.py.
    llm = MockLLMClient()
    llm.queue_response('TOOL: get_rulings {"card_id": "abc123"}')
    llm.queue_response("FINAL: I could not find a direct source. ||CITES: ||")

    tools = {"get_rulings": lambda args: {"rulings": []}}

    run_loop("An obscure ruling question", llm_client=llm, tools=tools, threshold=0.95, call_logger=call_logger)

    events = _read_loop_events(log_path)
    escalate_events = [e for e in events if e["event"] == "escalate"]
    assert len(escalate_events) == 1
    assert "score" in escalate_events[0]
    assert "threshold" in escalate_events[0]


def test_run_loop_logs_verification_failed_event(tmp_path):
    log_path = tmp_path / "aijudge.jsonl"
    call_logger = CallLogger(str(log_path))
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

    run_loop(
        "What does Tearlaments Sulliek's first effect do?",
        llm_client=llm,
        tools=tools,
        call_logger=call_logger,
    )

    events = _read_loop_events(log_path)
    assert any(e["event"] == "verification_failed" for e in events)


def test_run_loop_wraps_its_own_llm_calls_in_the_loop_call_site(tmp_path):
    log_path = tmp_path / "aijudge.jsonl"
    call_logger = CallLogger(str(log_path))
    from aijudge.call_log import LoggingLLMClient

    inner = MockLLMClient()
    inner.queue_response("FINAL: ok. ||CITES: ||")
    wrapped = LoggingLLMClient(inner, call_logger)

    run_loop("A question", llm_client=wrapped, tools={}, call_logger=call_logger)

    with open(log_path, encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    llm_calls = [r for r in records if r["type"] == "llm_call"]
    assert llm_calls and all(r["site"] == "loop" for r in llm_calls)
