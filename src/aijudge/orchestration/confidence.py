from dataclasses import dataclass, field

DEFAULT_CONFIDENCE_THRESHOLD = 0.75
RETRIEVAL_GAP_PENALTY = 0.3
MISSING_STRUCTURED_EFFECT_PENALTY = 0.2


@dataclass
class SignalState:
    known_ids: set[str] = field(default_factory=set)
    citation_index: dict[str, dict] = field(default_factory=dict)
    structured_effects: dict[str, list[dict]] = field(default_factory=dict)
    missing_structured_effect: bool = False
    retrieval_gap: bool = False


def update_signals(state: SignalState, tool_name: str, result: dict) -> None:
    if tool_name == "lookup_card":
        if result.get("found"):
            card_id = f"card:{result['id']}"
            citation = {
                "label": result.get("name", ""),
                "text": result.get("card_text", ""),
            }
            state.known_ids.add(card_id)
            state.citation_index[card_id] = citation
            confirmed_effects = result.get("confirmed_effects")
            if confirmed_effects:
                state.structured_effects[card_id] = confirmed_effects
            else:
                state.missing_structured_effect = True
            ygoprodeck_id = result.get("ygoprodeck_id")
            if ygoprodeck_id:
                # The LLM sometimes cites a card by its real-world passcode
                # instead of (or alongside) the internal id lookup_card
                # returned -- both identify the same already-grounded card,
                # so both must count as known rather than one looking
                # fabricated next to the other.
                passcode_id = f"card:{ygoprodeck_id}"
                state.known_ids.add(passcode_id)
                state.citation_index[passcode_id] = citation
                if confirmed_effects:
                    state.structured_effects[passcode_id] = confirmed_effects
    elif tool_name == "get_rulings":
        rulings = result.get("rulings", [])
        if not rulings:
            state.retrieval_gap = True
        for ruling in rulings:
            ruling_id = f"ruling:{ruling['id']}"
            state.known_ids.add(ruling_id)
            state.citation_index[ruling_id] = {
                "label": ruling.get("source", ""),
                "text": ruling.get("ruling_text", ""),
            }
    elif tool_name == "search_rulebook":
        chunks = result.get("chunks", [])
        if not chunks:
            state.retrieval_gap = True
        for chunk in chunks:
            chunk_id = f"chunk:{chunk['id']}"
            state.known_ids.add(chunk_id)
            state.citation_index[chunk_id] = {
                "label": chunk.get("source", ""),
                "text": chunk.get("chunk_text", ""),
            }


def normalize_cited_ids(cited_ids: set[str], state: SignalState) -> set[str]:
    """A local model sometimes drops the internal id's "card:" prefix in its
    ||CITES: ...|| trailer while still meaning the exact card lookup_card (or
    grounded_cards preseeding) already surfaced -- e.g. citing bare "abc123"
    instead of "card:abc123". Treat that bare id as an alias for its prefixed
    form, the same already-known source rather than a fabricated one,
    mirroring the passcode-alias handling in update_signals above."""
    normalized = set()
    for cited_id in cited_ids:
        prefixed = f"card:{cited_id}"
        if cited_id not in state.known_ids and prefixed in state.known_ids:
            normalized.add(prefixed)
        else:
            normalized.add(cited_id)
    return normalized


def compute_confidence(cited_ids: set[str], state: SignalState) -> float:
    if cited_ids - state.known_ids:
        return 0.0
    if state.known_ids and not cited_ids:
        return 0.0

    score = 1.0
    if state.retrieval_gap:
        score -= RETRIEVAL_GAP_PENALTY
    if state.missing_structured_effect:
        score -= MISSING_STRUCTURED_EFFECT_PENALTY
    return max(0.0, min(1.0, score))
