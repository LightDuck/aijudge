from aijudge.cli import run_cli
from aijudge.embeddings.client import MockEmbeddingClient
from aijudge.llm.client import MockLLMClient
from aijudge.orchestration.card_effect_pipeline import PipelineResolution
from aijudge.orchestration.loop import NOT_SUPPORTED_MESSAGE
from aijudge.orchestration.protocol import build_answering_system_prompt, build_system_prompt


class _CapturingLLMClient:
    """A FIFO-response fake that also records every prompt (and system prompt)
    it receives, so tests can assert on what actually reached the LLM."""

    def __init__(self, responses):
        self._queue = list(responses)
        self.prompts = []
        self.system_prompts = []

    def complete(self, prompt, *, system=None):
        self.prompts.append(prompt)
        self.system_prompts.append(system)
        return self._queue.pop(0)


def test_run_cli_exits_immediately_on_quit():
    printed = []
    inputs = iter(["quit"])

    run_cli(MockLLMClient(), MockEmbeddingClient(), input_fn=lambda _: next(inputs), print_fn=printed.append)

    assert any("AIJudge" in line for line in printed)


def test_run_cli_exits_on_eof():
    printed = []

    def _input(_prompt):
        raise EOFError

    run_cli(MockLLMClient(), MockEmbeddingClient(), input_fn=_input, print_fn=printed.append)

    assert any("AIJudge" in line for line in printed)


def test_run_cli_skips_blank_input_without_calling_the_llm():
    printed = []
    inputs = iter(["   ", "quit"])

    # No responses queued: if blank input reached the LLM, MockLLMClient
    # would raise AssertionError on the empty queue and fail this test.
    run_cli(MockLLMClient(), MockEmbeddingClient(), input_fn=lambda _: next(inputs), print_fn=printed.append)

    assert any("AIJudge" in line for line in printed)


def test_run_cli_answers_a_question_with_no_clarification_needed():
    printed = []
    inputs = iter(["What does Card X do?", "quit"])

    llm = MockLLMClient()
    llm.queue_response("PROCEED")
    llm.queue_response("FINAL: It does X. ||CITES: card:1||")

    card = {"id": "1", "name": "Card X", "card_type": "Effect Monster"}

    run_cli(
        llm,
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: [card],
        build_known_facts_context_fn=lambda c: "",
        build_grounded_result_fn=lambda c: {"found": True, "id": c["id"], "name": c["name"], "confirmed_effects": []},
    )

    assert "It does X." in printed


def test_run_cli_passes_the_system_prompt_to_the_clarification_call():
    printed = []
    inputs = iter(["What does Card X do?", "quit"])

    llm = MockLLMClient()
    llm.queue_response("PROCEED")
    llm.queue_response("FINAL: It does X. ||CITES: card:1||")

    card = {"id": "1", "name": "Card X", "card_type": "Effect Monster"}

    run_cli(
        llm,
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: [card],
        build_known_facts_context_fn=lambda c: "",
        build_grounded_result_fn=lambda c: {"found": True, "id": c["id"], "name": c["name"], "confirmed_effects": []},
    )

    assert llm.system_prompts[0] == build_system_prompt()


def test_run_cli_asks_clarification_questions_before_answering():
    printed = []
    inputs = iter(["Can I respond to this?", "Blue-Eyes White Dragon", "quit"])

    llm = MockLLMClient()
    llm.queue_response("CLARIFY: Which monster do you control?")
    llm.queue_response("FINAL: Yes, you can respond. ||CITES: card:1||")

    card = {"id": "1", "name": "Effect Veiler", "card_type": "Effect Monster"}

    run_cli(
        llm,
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: [card],
        build_known_facts_context_fn=lambda c: "",
        build_grounded_result_fn=lambda c: {"found": True, "id": c["id"], "name": c["name"], "confirmed_effects": []},
    )

    assert "Yes, you can respond." in printed


def test_run_cli_skips_the_clarification_call_when_no_card_matches():
    printed = []
    inputs = iter(["what is tearlaments havnis effect?", "quit"])

    llm = MockLLMClient()
    # Only one response queued -- if the clarify pass ran anyway, it would
    # consume this response itself (leaving run_loop's own call to raise
    # AssertionError on the now-empty queue), so this asserts the skip.
    llm.queue_response("FINAL: It negates a Spell/Trap Card. ||CITES: ||")

    run_cli(
        llm,
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: [],
        resolve_card_effect_question_fn=lambda question, **kwargs: PipelineResolution(supported=True),
    )

    assert "It negates a Spell/Trap Card." in printed


def test_run_cli_prints_not_supported_when_pipeline_finds_no_cards():
    printed = []
    inputs = iter(["what is the SEGOC rule?", "quit"])

    run_cli(
        MockLLMClient(),
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: [],
        resolve_card_effect_question_fn=lambda question, **kwargs: PipelineResolution(supported=False),
    )

    assert NOT_SUPPORTED_MESSAGE in printed


def test_run_cli_uses_pipeline_context_and_grounded_cards_when_no_local_match():
    printed = []
    inputs = iter(["What does Some New Card do?", "quit"])

    llm = _CapturingLLMClient(["FINAL: It does the thing. ||CITES: card:99||", "YES"])

    def fake_resolve(question, **kwargs):
        return PipelineResolution(
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
        )

    run_cli(
        llm,
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: [],
        resolve_card_effect_question_fn=fake_resolve,
    )

    assert "It does the thing." in printed
    assert "KNOWN FACTS: Some New Card" in llm.prompts[0]


def test_run_cli_uses_answering_system_prompt_for_the_final_turn():
    inputs = iter(["What does Card X do?", "quit"])
    llm = _CapturingLLMClient(["PROCEED", "FINAL: It does X. ||CITES: card:1||"])
    card = {"id": "1", "name": "Card X", "card_type": "Effect Monster"}

    run_cli(
        llm,
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=lambda _: None,
        find_matched_cards_fn=lambda question: [card],
        build_known_facts_context_fn=lambda c: "",
        build_grounded_result_fn=lambda c: {"found": True, "id": c["id"], "name": c["name"], "confirmed_effects": []},
    )

    assert llm.system_prompts[0] == build_system_prompt()
    assert llm.system_prompts[1] == build_answering_system_prompt()


def test_run_cli_disambiguates_when_multiple_cards_match():
    printed = []
    inputs = iter(["Can I chain Effect Veiler or Effector here?", "Effect Veiler", "quit"])

    llm = _CapturingLLMClient(["PROCEED", "FINAL: Yes. ||CITES: card:1||"])

    matches = [
        {"id": "1", "name": "Effect Veiler", "card_type": "Effect Monster"},
        {"id": "2", "name": "Effector", "card_type": "Effect Monster"},
    ]

    run_cli(
        llm,
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: matches,
        build_known_facts_context_fn=lambda card: f"KNOWN FACTS: {card['name']}",
        build_grounded_result_fn=lambda card: {
            "found": True,
            "id": card["id"],
            "name": card["name"],
            "confirmed_effects": [],
        },
    )

    assert "Yes." in printed
    assert any("KNOWN FACTS: Effect Veiler" in p for p in llm.prompts)


def test_run_cli_disambiguates_with_case_insensitive_fuzzy_match():
    printed = []
    inputs = iter(["Can I chain Effect Veiler or Effector here?", "effect veiler", "quit"])

    llm = _CapturingLLMClient(["PROCEED", "FINAL: Yes. ||CITES: card:1||"])

    matches = [
        {"id": "1", "name": "Effect Veiler", "card_type": "Effect Monster"},
        {"id": "2", "name": "Effector", "card_type": "Effect Monster"},
    ]

    run_cli(
        llm,
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: matches,
        build_known_facts_context_fn=lambda card: f"KNOWN FACTS: {card['name']}",
        build_grounded_result_fn=lambda card: {
            "found": True,
            "id": card["id"],
            "name": card["name"],
            "confirmed_effects": [],
        },
    )

    assert "Yes." in printed
    assert any("KNOWN FACTS: Effect Veiler" in p for p in llm.prompts)


def test_run_cli_passes_known_facts_to_the_clarification_call_for_a_single_match():
    printed = []
    inputs = iter(["Is Baronne de Fleur's effect usable in the Damage Step?", "quit"])

    llm = _CapturingLLMClient(["PROCEED", "FINAL: Yes. ||CITES: card:1||"])

    card = {"id": "1", "name": "Baronne de Fleur", "card_type": "Synchro Monster"}

    run_cli(
        llm,
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: [card],
        build_known_facts_context_fn=lambda c: f"KNOWN FACTS: {c['name']}",
        build_grounded_result_fn=lambda c: {"found": True, "id": c["id"], "name": c["name"], "confirmed_effects": []},
    )

    assert "Yes." in printed
    # The clarification-decision call (prompts[0]) must see the grounding
    # data too, not just the run_loop call -- otherwise the LLM can ask for
    # clarification the deterministic layer already resolved.
    assert "KNOWN FACTS: Baronne de Fleur" in llm.prompts[0]


def test_run_cli_prints_a_notice_when_disambiguation_answer_matches_nothing():
    printed = []
    inputs = iter(["Can I chain Effect Veiler or Effector here?", "I have no idea what you mean", "quit"])

    llm = _CapturingLLMClient(["PROCEED", "FINAL: Yes. ||CITES: ||"])

    matches = [
        {"id": "1", "name": "Effect Veiler", "card_type": "Effect Monster"},
        {"id": "2", "name": "Effector", "card_type": "Effect Monster"},
    ]

    run_cli(
        llm,
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: matches,
        build_known_facts_context_fn=lambda card: f"KNOWN FACTS: {card['name']}",
    )

    assert "Yes." in printed
    assert any("Couldn't match your answer" in p for p in printed)
    assert not any("KNOWN FACTS" in p for p in llm.prompts)


def test_run_cli_folds_preflight_facts_in_for_a_single_match():
    printed = []
    inputs = iter(["Can I activate Effect Veiler here?", "quit"])

    llm = _CapturingLLMClient(["PROCEED", "FINAL: Yes. ||CITES: card:1||"])

    card = {"id": "1", "name": "Effect Veiler", "card_type": "Effect Monster"}

    run_cli(
        llm,
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: [card],
        build_known_facts_context_fn=lambda c: f"KNOWN FACTS: {c['name']}",
        build_grounded_result_fn=lambda c: {"found": True, "id": c["id"], "name": c["name"], "confirmed_effects": []},
    )

    assert "Yes." in printed
    assert any("KNOWN FACTS: Effect Veiler" in p for p in llm.prompts)


def test_run_cli_direct_final_answer_citing_the_grounded_id_does_not_escalate():
    # Reproduces the real-world escalation: the LLM answers straight from
    # KNOWN FACTS on the first turn (no lookup_card call), citing the
    # matched card's id. Without grounded_cards pre-registering that id,
    # compute_confidence would treat it as fabricated and escalate.
    printed = []
    inputs = iter(["What does Ghost Belle & Haunted Mansion do?", "quit"])

    llm = _CapturingLLMClient(["PROCEED", "FINAL: It negates that activation. ||CITES: card:1||", "YES"])

    card = {"id": "1", "name": "Ghost Belle & Haunted Mansion", "card_type": "Tuner Monster"}

    run_cli(
        llm,
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: [card],
        build_known_facts_context_fn=lambda c: f"KNOWN FACTS: {c['name']} (cite as card:{c['id']})",
        build_grounded_result_fn=lambda c: {
            "found": True,
            "id": c["id"],
            "name": c["name"],
            "card_text": "Ghost Belle card text.",
            "confirmed_effects": [{"effect": "..."}],
        },
    )

    assert "It negates that activation." in printed


def test_run_cli_wires_on_ingest_start_callback_and_online_ingest_enabled_to_the_pipeline():
    printed = []
    inputs = iter(["What does Some New Card do?", "quit"])
    captured = {}

    def fake_resolve(question, *, llm_client, online_ingest_enabled, on_ingest_start):
        captured["online_ingest_enabled"] = online_ingest_enabled
        on_ingest_start("Some New Card")
        return PipelineResolution(supported=False)

    run_cli(
        MockLLMClient(),
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: [],
        resolve_card_effect_question_fn=fake_resolve,
    )

    assert captured["online_ingest_enabled"] is True
    assert any("Some New Card" in line for line in printed)


def test_run_cli_passes_online_ingest_enabled_false_through_to_the_pipeline():
    inputs = iter(["What does Some New Card do?", "quit"])
    captured = {}

    def fake_resolve(question, *, llm_client, online_ingest_enabled, on_ingest_start):
        captured["online_ingest_enabled"] = online_ingest_enabled
        return PipelineResolution(supported=False)

    run_cli(
        MockLLMClient(),
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=lambda _: None,
        find_matched_cards_fn=lambda question: [],
        resolve_card_effect_question_fn=fake_resolve,
        online_ingest_enabled=False,
    )

    assert captured["online_ingest_enabled"] is False
