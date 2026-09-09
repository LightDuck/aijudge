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
    update_signals(state, "lookup_card", {"found": True, "id": "abc", "confirmed_effects": [{"effect": "..."}]})
    assert state.known_ids == {"card:abc"}
    assert state.missing_structured_effect is False


def test_update_signals_flags_missing_structured_effect():
    state = SignalState()
    update_signals(state, "lookup_card", {"found": True, "id": "abc", "confirmed_effects": []})
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


def test_update_signals_indexes_card_citation_label_and_text():
    state = SignalState()
    update_signals(
        state,
        "lookup_card",
        {
            "found": True,
            "id": "abc",
            "name": "Ash Blossom & Joyous Spring",
            "card_text": "You can discard this card...",
            "confirmed_effects": [{"effect": "..."}],
        },
    )
    assert state.citation_index["card:abc"] == {
        "label": "Ash Blossom & Joyous Spring",
        "text": "You can discard this card...",
    }


def test_update_signals_indexes_card_citation_with_missing_optional_fields():
    state = SignalState()
    update_signals(state, "lookup_card", {"found": True, "id": "abc", "confirmed_effects": []})
    assert state.citation_index["card:abc"] == {"label": "", "text": ""}


def test_update_signals_indexes_ruling_citation_label_and_text():
    state = SignalState()
    update_signals(
        state,
        "get_rulings",
        {"rulings": [{"id": "r1", "ruling_text": "This does X.", "source": "ygoresources"}]},
    )
    assert state.citation_index["ruling:r1"] == {"label": "ygoresources", "text": "This does X."}


def test_update_signals_indexes_chunk_citation_label_and_text():
    state = SignalState()
    update_signals(
        state,
        "search_rulebook",
        {"chunks": [{"id": "c1", "chunk_text": "Rule text.", "source": "rulebook"}]},
    )
    assert state.citation_index["chunk:c1"] == {"label": "rulebook", "text": "Rule text."}


def test_update_signals_registers_ygoprodeck_id_as_citable_alias_for_card():
    state = SignalState()
    update_signals(
        state,
        "lookup_card",
        {
            "found": True,
            "id": "abc",
            "ygoprodeck_id": "32896829",
            "name": "Ghost Belle & Haunted Mansion",
            "card_text": "...",
            "confirmed_effects": [{"effect": "..."}],
        },
    )
    assert state.known_ids == {"card:abc", "card:32896829"}
    assert state.citation_index["card:32896829"] == state.citation_index["card:abc"]


def test_update_signals_tracks_structured_effects_for_card():
    state = SignalState()
    effects = [{"effect": "Target 1 Effect Monster your opponent controls; negate its effects."}]
    update_signals(state, "lookup_card", {"found": True, "id": "abc", "confirmed_effects": effects})
    assert state.structured_effects["card:abc"] == effects


def test_update_signals_tracks_structured_effects_under_passcode_alias_too():
    state = SignalState()
    effects = [{"effect": "..."}]
    update_signals(
        state,
        "lookup_card",
        {"found": True, "id": "abc", "ygoprodeck_id": "32896829", "confirmed_effects": effects},
    )
    assert state.structured_effects["card:abc"] == effects
    assert state.structured_effects["card:32896829"] == effects


def test_update_signals_does_not_add_structured_effects_entry_when_missing():
    state = SignalState()
    update_signals(state, "lookup_card", {"found": True, "id": "abc", "confirmed_effects": []})
    assert "card:abc" not in state.structured_effects


def test_update_signals_without_ygoprodeck_id_registers_only_internal_id():
    state = SignalState()
    update_signals(state, "lookup_card", {"found": True, "id": "abc", "confirmed_effects": [{"effect": "..."}]})
    assert state.known_ids == {"card:abc"}


def test_compute_confidence_accepts_passcode_citation_alongside_internal_id():
    # Reproduces the false-positive escalation: the LLM correctly grounded its
    # answer via lookup_card, but cited the card by its real-world passcode
    # (which it knows from training data, not from any tool result) in
    # addition to the internal id lookup_card actually returned. That passcode
    # refers to the exact same already-looked-up card, so it must not be
    # treated as a fabricated source the way an unrelated unknown id would be.
    state = SignalState()
    update_signals(
        state,
        "lookup_card",
        {"found": True, "id": "abc", "ygoprodeck_id": "32896829", "confirmed_effects": [{"effect": "..."}]},
    )
    assert compute_confidence({"card:abc", "card:32896829"}, state) == 1.0


def test_compute_confidence_zero_when_known_ids_populated_but_nothing_cited():
    state = SignalState(known_ids={"card:abc"})
    assert compute_confidence(set(), state) == 0.0


def test_compute_confidence_unaffected_when_known_ids_empty_and_nothing_cited():
    state = SignalState()
    assert compute_confidence(set(), state) == 1.0
