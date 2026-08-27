from aijudge.cli import run_cli
from aijudge.embeddings.client import MockEmbeddingClient
from aijudge.llm.client import MockLLMClient


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

    run_cli(llm, MockEmbeddingClient(), input_fn=lambda _: next(inputs), print_fn=printed.append)

    assert "It does X." in printed


def test_run_cli_asks_clarification_questions_before_answering():
    printed = []
    inputs = iter(["Can I respond to this?", "Blue-Eyes White Dragon", "quit"])

    llm = MockLLMClient()
    llm.queue_response("CLARIFY: Which monster do you control?")
    llm.queue_response("FINAL: Yes, you can respond. ||CITES: ||")

    run_cli(llm, MockEmbeddingClient(), input_fn=lambda _: next(inputs), print_fn=printed.append)

    assert "Yes, you can respond." in printed
