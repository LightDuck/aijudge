import logging
from dataclasses import asdict
from typing import Callable

import psycopg

from aijudge.db.cards_repo import get_card_by_name
from aijudge.db.effects_repo import get_confirmed_effects
from aijudge.db.rulebook_repo import search_chunks
from aijudge.db.rulings_repo import get_rulings_for_card
from aijudge.embeddings.client import EmbeddingClient
from aijudge.ingestion.seed import seed_card
from aijudge.ingestion.ygoprodeck_client import CardNotFoundError, fetch_card
from aijudge.ingestion.ygoresources_client import fetch_rulings
from aijudge.llm.client import LLMClient
from aijudge.rules_engine.resolve import resolve_chain as _resolve_chain_scenario

logger = logging.getLogger(__name__)

DEFAULT_MAX_DISTANCE = 0.15


def _card_result(card: dict) -> dict:
    return {
        "found": True,
        "id": card["id"],
        "name": card["name"],
        "card_text": card["card_text"],
        "card_type": card["card_type"],
        "confirmed_effects": get_confirmed_effects(card["id"]),
    }


def lookup_card(
    args: dict,
    *,
    llm_client: LLMClient | None = None,
    online_ingest_enabled: bool = False,
    fetch_card_fn: Callable[..., dict] = fetch_card,
    fetch_rulings_fn: Callable[..., list[dict]] = fetch_rulings,
    on_ingest_start: Callable[[str], None] | None = None,
) -> dict:
    name = args["name"]
    card = get_card_by_name(name)
    if card is not None:
        return _card_result(card)

    if not online_ingest_enabled:
        return {"found": False}

    if on_ingest_start is not None:
        on_ingest_start(name)

    try:
        seed_card(name, llm_client=llm_client, fetch_card_fn=fetch_card_fn, fetch_rulings_fn=fetch_rulings_fn)
    except CardNotFoundError:
        return {"found": False}
    except psycopg.errors.UniqueViolation:
        pass  # a concurrent request won the insert race -- fall through and re-fetch its row
    except Exception:
        logger.exception("online ingest failed for card name=%r", name)
        return {"found": False}

    card = get_card_by_name(name)
    if card is None:
        return {"found": False}
    return _card_result(card)


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
