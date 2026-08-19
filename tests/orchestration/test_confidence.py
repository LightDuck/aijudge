import pytest

from aijudge.orchestration.confidence import (
    MISSING_STRUCTURED_EFFECT_PENALTY,
    RETRIEVAL_GAP_PENALTY,
    SignalState,
    compute_confidence,
    update_signals,
)


def test_update_signals_tracks_found_card_id():
    state = SignalState()
    update_signals(state, "lookup_card", {"found": True, "id": "abc", "confirmed_effect": {"effect": "..."}})
    assert state.known_ids == {"card:abc"}
    assert state.missing_structured_effect is False


def test_update_signals_flags_missing_structured_effect():
    state = SignalState()
    update_signals(state, "lookup_card", {"found": True, "id": "abc", "confirmed_effect": None})
    assert state.missing_structured_effect is True


def test_update_signals_ignores_card_not_found():
    state = SignalState()
    update_signals(state, "lookup_card", {"found": False})
    assert state.known_ids == set()
    assert state.missing_structured_effect is False


def test_update_signals_tracks_ruling_ids_and_gap():
    state = SignalState()
    update_signals(state, "get_rulings", {"rulings": [{"id": "r1", "ruling_text": "..."}]})
    assert state.known_ids == {"ruling:r1"}
    assert state.retrieval_gap is False

    empty_state = SignalState()
    update_signals(empty_state, "get_rulings", {"rulings": []})
    assert empty_state.retrieval_gap is True


def test_update_signals_tracks_chunk_ids_and_gap():
    state = SignalState()
    update_signals(state, "search_rulebook", {"chunks": [{"id": "c1", "chunk_text": "..."}]})
    assert state.known_ids == {"chunk:c1"}

    empty_state = SignalState()
    update_signals(empty_state, "search_rulebook", {"chunks": []})
    assert empty_state.retrieval_gap is True


def test_compute_confidence_is_perfect_with_no_negative_signals():
    state = SignalState(known_ids={"card:abc"})
    assert compute_confidence({"card:abc"}, state) == 1.0


def test_compute_confidence_zero_on_fabricated_citation():
    state = SignalState(known_ids={"card:abc"})
    assert compute_confidence({"card:abc", "ruling:never-looked-up"}, state) == 0.0


def test_compute_confidence_applies_retrieval_gap_penalty():
    state = SignalState(retrieval_gap=True)
    assert compute_confidence(set(), state) == pytest.approx(1.0 - RETRIEVAL_GAP_PENALTY)


def test_compute_confidence_applies_missing_structured_effect_penalty():
    state = SignalState(missing_structured_effect=True)
    assert compute_confidence(set(), state) == pytest.approx(1.0 - MISSING_STRUCTURED_EFFECT_PENALTY)


def test_compute_confidence_applies_both_penalties_together():
    state = SignalState(retrieval_gap=True, missing_structured_effect=True)
    assert compute_confidence(set(), state) == pytest.approx(1.0 - RETRIEVAL_GAP_PENALTY - MISSING_STRUCTURED_EFFECT_PENALTY)
