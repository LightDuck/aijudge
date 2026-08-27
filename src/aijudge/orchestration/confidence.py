from dataclasses import dataclass, field

DEFAULT_CONFIDENCE_THRESHOLD = 0.9
RETRIEVAL_GAP_PENALTY = 0.3
MISSING_STRUCTURED_EFFECT_PENALTY = 0.2


@dataclass
class SignalState:
    known_ids: set[str] = field(default_factory=set)
    citation_index: dict[str, dict] = field(default_factory=dict)
    missing_structured_effect: bool = False
    retrieval_gap: bool = False


def update_signals(state: SignalState, tool_name: str, result: dict) -> None:
    if tool_name == "lookup_card":
        if result.get("found"):
            card_id = f"card:{result['id']}"
            state.known_ids.add(card_id)
            state.citation_index[card_id] = {
                "label": result.get("name", ""),
                "text": result.get("card_text", ""),
            }
            if result.get("confirmed_effect") is None:
                state.missing_structured_effect = True
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


def compute_confidence(cited_ids: set[str], state: SignalState) -> float:
    if cited_ids - state.known_ids:
        return 0.0

    score = 1.0
    if state.retrieval_gap:
        score -= RETRIEVAL_GAP_PENALTY
    if state.missing_structured_effect:
        score -= MISSING_STRUCTURED_EFFECT_PENALTY
    return max(0.0, min(1.0, score))
