from aijudge.cli import run_cli
from aijudge.embeddings.client import MockEmbeddingClient
from aijudge.llm.client import MockLLMClient
from aijudge.orchestration.protocol import build_system_prompt


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
    llm.queue_response("FINAL: It does X. ||CITES: ||")

    run_cli(
        llm,
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: [],
    )

    assert "It does X." in printed


def test_run_cli_passes_the_system_prompt_to_the_clarification_call():
    printed = []
    inputs = iter(["What does Card X do?", "quit"])

    llm = MockLLMClient()
    llm.queue_response("PROCEED")
    llm.queue_response("FINAL: It does X. ||CITES: ||")

    run_cli(
        llm,
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: [],
    )

    assert llm.system_prompts[0] == build_system_prompt()


def test_run_cli_asks_clarification_questions_before_answering():
    printed = []
    inputs = iter(["Can I respond to this?", "Blue-Eyes White Dragon", "quit"])

    llm = MockLLMClient()
    llm.queue_response("CLARIFY: Which monster do you control?")
    llm.queue_response("FINAL: Yes, you can respond. ||CITES: ||")

    run_cli(
        llm,
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: [],
    )

    assert "Yes, you can respond." in printed


def test_run_cli_disambiguates_when_multiple_cards_match():
    printed = []
    inputs = iter(["Can I chain Effect Veiler or Effector here?", "Effect Veiler", "quit"])

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
    assert any("KNOWN FACTS: Effect Veiler" in p for p in llm.prompts)


def test_run_cli_disambiguates_with_case_insensitive_fuzzy_match():
    printed = []
    inputs = iter(["Can I chain Effect Veiler or Effector here?", "effect veiler", "quit"])

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
    assert any("KNOWN FACTS: Effect Veiler" in p for p in llm.prompts)


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

    llm = _CapturingLLMClient(["PROCEED", "FINAL: Yes. ||CITES: ||"])

    card = {"id": "1", "name": "Effect Veiler", "card_type": "Effect Monster"}

    run_cli(
        llm,
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: [card],
        build_known_facts_context_fn=lambda c: f"KNOWN FACTS: {c['name']}",
    )

    assert "Yes." in printed
    assert any("KNOWN FACTS: Effect Veiler" in p for p in llm.prompts)
