from aijudge.effect_parser.clause_splitter import split_effect_clauses
from aijudge.llm.client import MockLLMClient


def test_split_effect_clauses_returns_single_chunk_when_llm_echoes_text_unchanged():
    llm = MockLLMClient()
    llm.queue_response("You can target 1 banished monster; banish it.")

    result = split_effect_clauses(llm, "You can target 1 banished monster; banish it.")

    assert result == ["You can target 1 banished monster; banish it."]


def test_split_effect_clauses_parses_multiple_dash_delimited_segments():
    llm = MockLLMClient()
    llm.queue_response("Effect one.\n---\nEffect two.")

    result = split_effect_clauses(llm, "Effect one. Effect two.")

    assert result == ["Effect one.", "Effect two."]


def test_split_effect_clauses_tolerates_whitespace_differences_when_reconstructing():
    llm = MockLLMClient()
    llm.queue_response("Effect one.\n---\n  Effect two.  ")

    result = split_effect_clauses(llm, "Effect one. Effect two.")

    assert result == ["Effect one.", "Effect two."]


def test_split_effect_clauses_falls_back_to_original_text_when_reconstruction_fails():
    llm = MockLLMClient()
    llm.queue_response("Effect one.\n---\nSomething completely different that lost text.")

    result = split_effect_clauses(llm, "Effect one. Effect two.")

    assert result == ["Effect one. Effect two."]
