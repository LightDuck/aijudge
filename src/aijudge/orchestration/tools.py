from dataclasses import asdict
from typing import Callable

from aijudge.db.cards_repo import get_card_by_name
from aijudge.db.effects_repo import get_confirmed_effect
from aijudge.db.rulebook_repo import search_chunks
from aijudge.db.rulings_repo import get_rulings_for_card
from aijudge.embeddings.client import EmbeddingClient
from aijudge.rules_engine.resolve import resolve_chain as _resolve_chain_scenario

DEFAULT_MAX_DISTANCE = 0.15


def lookup_card(args: dict) -> dict:
    card = get_card_by_name(args["name"])
    if card is None:
        return {"found": False}
    confirmed_effect = get_confirmed_effect(card["id"])
    return {
        "found": True,
        "id": card["id"],
        "name": card["name"],
        "card_text": card["card_text"],
        "card_type": card["card_type"],
        "confirmed_effect": confirmed_effect,
    }


def get_rulings(args: dict) -> dict:
    rulings = get_rulings_for_card(args["card_id"])
    return {
        "rulings": [
            {
                "id": ruling["id"],
                "ruling_text": ruling["ruling_text"],
                "source": ruling["source"],
                "ruling_date": ruling["ruling_date"].isoformat() if ruling["ruling_date"] else None,
            }
            for ruling in rulings
        ]
    }


def _search_rulebook(args: dict, *, embedding_client: EmbeddingClient) -> dict:
    query_embedding = embedding_client.embed(args["query"])
    chunks = search_chunks(query_embedding, max_distance=DEFAULT_MAX_DISTANCE)
    return {
        "chunks": [
            {
                "id": chunk["id"],
                "chunk_text": chunk["chunk_text"],
                "source": chunk["source"],
                "section_reference": chunk["section_reference"],
            }
            for chunk in chunks
        ]
    }


def resolve_chain(args: dict) -> dict:
    result = _resolve_chain_scenario(args)
    return asdict(result)


def build_tool_dispatch(embedding_client: EmbeddingClient) -> dict[str, Callable[[dict], dict]]:
    return {
        "lookup_card": lookup_card,
        "get_rulings": get_rulings,
        "search_rulebook": lambda args: _search_rulebook(args, embedding_client=embedding_client),
        "resolve_chain": resolve_chain,
    }
