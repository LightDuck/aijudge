import pytest

from aijudge.effect_parser.clause_splitter import resolve_effect_clauses, score_split_confidence, split_effect_clauses
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


def test_score_split_confidence_returns_the_llm_score():
    llm = MockLLMClient()
    llm.queue_response("0.95")

    confidence = score_split_confidence(
        llm, card_text="Effect one. Effect two.", effect_texts=["Effect one.", "Effect two."]
    )

    assert confidence == pytest.approx(0.95)


def test_score_split_confidence_rejects_out_of_range_values():
    llm = MockLLMClient()
    llm.queue_response("1.5")

    with pytest.raises(ValueError):
        score_split_confidence(llm, card_text="x", effect_texts=["x"])


def test_resolve_effect_clauses_returns_single_chunk_without_scoring_when_llm_finds_one_effect():
    llm = MockLLMClient()
    llm.queue_response("Just one effect.")  # only one queued response -- scoring must not be called

    result = resolve_effect_clauses(llm, "Just one effect.")

    assert result == ["Just one effect."]


def test_resolve_effect_clauses_keeps_a_high_confidence_multi_effect_split():
    llm = MockLLMClient()
    llm.queue_response("Effect one.\n---\nEffect two.")
    llm.queue_response("0.95")

    result = resolve_effect_clauses(llm, "Effect one. Effect two.")

    assert result == ["Effect one.", "Effect two."]


def test_resolve_effect_clauses_falls_back_to_single_chunk_on_low_split_confidence():
    llm = MockLLMClient()
    llm.queue_response("Effect one.\n---\nEffect two.")
    llm.queue_response("0.4")

    result = resolve_effect_clauses(llm, "Effect one. Effect two.")

    assert result == ["Effect one. Effect two."]
