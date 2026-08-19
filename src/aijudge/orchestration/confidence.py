from dataclasses import dataclass, field

DEFAULT_CONFIDENCE_THRESHOLD = 0.9
RETRIEVAL_GAP_PENALTY = 0.3
MISSING_STRUCTURED_EFFECT_PENALTY = 0.2


@dataclass
class SignalState:
    known_ids: set[str] = field(default_factory=set)
    missing_structured_effect: bool = False
    retrieval_gap: bool = False


def update_signals(state: SignalState, tool_name: str, result: dict) -> None:
    if tool_name == "lookup_card":
        if result.get("found"):
            state.known_ids.add(f"card:{result['id']}")
            if result.get("confirmed_effect") is None:
                state.missing_structured_effect = True
    elif tool_name == "get_rulings":
        rulings = result.get("rulings", [])
        if not rulings:
            state.retrieval_gap = True
        for ruling in rulings:
            state.known_ids.add(f"ruling:{ruling['id']}")
    elif tool_name == "search_rulebook":
        chunks = result.get("chunks", [])
        if not chunks:
            state.retrieval_gap = True
        for chunk in chunks:
            state.known_ids.add(f"chunk:{chunk['id']}")


def compute_confidence(cited_ids: set[str], state: SignalState) -> float:
    if cited_ids - state.known_ids:
        return 0.0

    score = 1.0
    if state.retrieval_gap:
        score -= RETRIEVAL_GAP_PENALTY
    if state.missing_structured_effect:
        score -= MISSING_STRUCTURED_EFFECT_PENALTY
    return max(0.0, min(1.0, score))
