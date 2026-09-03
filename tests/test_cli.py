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

    card = {"id": "1", "name": "Card X", "card_type": "Effect Monster"}

    run_cli(
        llm,
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: [card],
        build_known_facts_context_fn=lambda c: "",
    )

    assert "It does X." in printed


def test_run_cli_passes_the_system_prompt_to_the_clarification_call():
    printed = []
    inputs = iter(["What does Card X do?", "quit"])

    llm = MockLLMClient()
    llm.queue_response("PROCEED")
    llm.queue_response("FINAL: It does X. ||CITES: ||")

    card = {"id": "1", "name": "Card X", "card_type": "Effect Monster"}

    run_cli(
        llm,
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: [card],
        build_known_facts_context_fn=lambda c: "",
    )

    assert llm.system_prompts[0] == build_system_prompt()


def test_run_cli_asks_clarification_questions_before_answering():
    printed = []
    inputs = iter(["Can I respond to this?", "Blue-Eyes White Dragon", "quit"])

    llm = MockLLMClient()
    llm.queue_response("CLARIFY: Which monster do you control?")
    llm.queue_response("FINAL: Yes, you can respond. ||CITES: ||")

    card = {"id": "1", "name": "Effect Veiler", "card_type": "Effect Monster"}

    run_cli(
        llm,
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: [card],
        build_known_facts_context_fn=lambda c: "",
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
    )

    assert "It negates a Spell/Trap Card." in printed


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


def test_run_cli_passes_known_facts_to_the_clarification_call_for_a_single_match():
    printed = []
    inputs = iter(["Is Baronne de Fleur's effect usable in the Damage Step?", "quit"])

    llm = _CapturingLLMClient(["PROCEED", "FINAL: Yes. ||CITES: ||"])

    card = {"id": "1", "name": "Baronne de Fleur", "card_type": "Synchro Monster"}

    run_cli(
        llm,
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: [card],
        build_known_facts_context_fn=lambda c: f"KNOWN FACTS: {c['name']}",
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


def test_run_cli_wires_on_ingest_start_callback_to_print_fn(monkeypatch):
    import aijudge.cli as cli_module

    captured = {}

    def fake_build_tool_dispatch(
        llm_client, embedding_client, *, online_ingest_enabled=True, on_ingest_start=None, card_mode=True
    ):
        captured["on_ingest_start"] = on_ingest_start
        captured["online_ingest_enabled"] = online_ingest_enabled
        return {}

    monkeypatch.setattr(cli_module, "build_tool_dispatch", fake_build_tool_dispatch)

    printed = []
    inputs = iter(["quit"])
    run_cli(MockLLMClient(), MockEmbeddingClient(), input_fn=lambda _: next(inputs), print_fn=printed.append)

    assert captured["online_ingest_enabled"] is True
    captured["on_ingest_start"]("Some New Card")
    assert any("Some New Card" in line for line in printed)


def test_run_cli_passes_online_ingest_enabled_through_to_tool_dispatch(monkeypatch):
    import aijudge.cli as cli_module

    captured = {}

    def fake_build_tool_dispatch(
        llm_client, embedding_client, *, online_ingest_enabled=True, on_ingest_start=None, card_mode=True
    ):
        captured["online_ingest_enabled"] = online_ingest_enabled
        return {}

    monkeypatch.setattr(cli_module, "build_tool_dispatch", fake_build_tool_dispatch)

    inputs = iter(["quit"])
    run_cli(
        MockLLMClient(),
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=lambda _: None,
        online_ingest_enabled=False,
    )

    assert captured["online_ingest_enabled"] is False


def test_run_cli_defaults_to_card_mode(monkeypatch):
    import aijudge.cli as cli_module

    card_modes = []

    def fake_build_tool_dispatch(
        llm_client, embedding_client, *, online_ingest_enabled=True, on_ingest_start=None, card_mode=True
    ):
        card_modes.append(card_mode)
        return {}

    monkeypatch.setattr(cli_module, "build_tool_dispatch", fake_build_tool_dispatch)

    printed = []
    inputs = iter(["What does Ash Blossom do?", "quit"])
    llm = MockLLMClient()
    llm.queue_response("FINAL: It negates. ||CITES: ||")

    run_cli(
        llm,
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: [],
    )

    assert True in card_modes
    assert False not in card_modes


def test_run_cli_ruling_marker_switches_mode_and_strips_marker_from_the_question(monkeypatch):
    import aijudge.cli as cli_module

    card_modes = []
    seen_questions = []

    def fake_build_tool_dispatch(
        llm_client, embedding_client, *, online_ingest_enabled=True, on_ingest_start=None, card_mode=True
    ):
        card_modes.append(card_mode)
        return {}

    def fake_run_loop(question, *, llm_client, tools, clarification_context=""):
        seen_questions.append(question)
        from aijudge.orchestration.loop import LoopResult

        return LoopResult(kind="answer", text="ok")

    monkeypatch.setattr(cli_module, "build_tool_dispatch", fake_build_tool_dispatch)
    monkeypatch.setattr(cli_module, "run_loop", fake_run_loop)

    printed = []
    inputs = iter(["{ruling} what does Ash Blossom do?", "quit"])

    run_cli(
        MockLLMClient(),
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: [],
    )

    assert seen_questions == ["what does Ash Blossom do?"]
    assert card_modes[-1] is False


def test_run_cli_mode_persists_across_turns_after_marker_switch(monkeypatch):
    import aijudge.cli as cli_module

    card_modes = []

    def fake_build_tool_dispatch(
        llm_client, embedding_client, *, online_ingest_enabled=True, on_ingest_start=None, card_mode=True
    ):
        card_modes.append(card_mode)
        return {}

    def fake_run_loop(question, *, llm_client, tools, clarification_context=""):
        from aijudge.orchestration.loop import LoopResult

        return LoopResult(kind="answer", text="ok")

    monkeypatch.setattr(cli_module, "build_tool_dispatch", fake_build_tool_dispatch)
    monkeypatch.setattr(cli_module, "run_loop", fake_run_loop)

    printed = []
    inputs = iter(["{ruling} what does Ash Blossom do?", "what about Effect Veiler?", "quit"])

    run_cli(
        MockLLMClient(),
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: [],
    )

    # Both the switching turn and the following unmarked turn stay in
    # ruling mode -- the marker sets a session-level mode, not a one-shot.
    assert card_modes[1:] == [False, False]
