import functools
import logging
from dataclasses import asdict
from typing import Callable

import psycopg

from aijudge.db.cards_repo import find_card_by_priority, get_card_by_id, get_card_by_name
from aijudge.db.effects_repo import get_confirmed_effects
from aijudge.db.rulebook_repo import search_chunks
from aijudge.db.rulings_repo import get_rulings_for_card
from aijudge.embeddings.client import EmbeddingClient
from aijudge.ingestion.printing_eligibility import fetch_sets_index
from aijudge.ingestion.seed import seed_card
from aijudge.ingestion.ygoprodeck_client import AmbiguousCardError, CardNotFoundError, fetch_card
from aijudge.ingestion.ygoresources_client import fetch_rulings
from aijudge.llm.client import LLMClient
from aijudge.rules_engine.resolve import resolve_chain as _resolve_chain_scenario

logger = logging.getLogger(__name__)

DEFAULT_MAX_DISTANCE = 0.15


@functools.lru_cache(maxsize=1)
def _cached_fetch_sets_index() -> dict:
    """Thin cached wrapper around the real fetch_sets_index, local to this
    module (not caching the imported function itself, which would affect
    other callers/tests unexpectedly). Each `lookup_card` online-ingest call
    is its own independent invocation, not part of a natural batch the way
    `ingestion.seed.run_seed` has one -- caching here is the pragmatic fix
    so repeated online-ingest calls within a process don't re-fetch this
    large, slowly-changing catalog."""
    return fetch_sets_index()


def _card_result(card: dict) -> dict:
    return {
        "found": True,
        "id": card["id"],
        "ygoprodeck_id": card["ygoprodeck_id"],
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
    fetch_sets_index_fn: Callable[..., dict] = _cached_fetch_sets_index,
    on_ingest_start: Callable[[str], None] | None = None,
) -> dict:
    name = args["name"]
    field = args.get("field")

    status, cards = find_card_by_priority(name, field=field)
    logger.debug("lookup_card name=%r field=%r db status=%r matches=%d", name, field, status, len(cards))
    if status == "single":
        return _card_result(cards[0])
    if status == "ambiguous":
        return {"found": False, "ambiguous": True}

    if not online_ingest_enabled:
        logger.debug("lookup_card name=%r: not found in db and online ingest disabled", name)
        return {"found": False}

    if on_ingest_start is not None:
        on_ingest_start(name)

    logger.debug("lookup_card name=%r: not found in db, attempting online ingest", name)
    card_id = None
    try:
        card_id = seed_card(
            name,
            llm_client=llm_client,
            fetch_card_fn=fetch_card_fn,
            fetch_rulings_fn=fetch_rulings_fn,
            fetch_sets_index_fn=fetch_sets_index_fn,
            field=field,
        )
        logger.debug("online ingest succeeded for name=%r -> card_id=%r", name, card_id)
    except AmbiguousCardError:
        logger.debug("online ingest name=%r: AmbiguousCardError", name)
        return {"found": False, "ambiguous": True}
    except CardNotFoundError:
        logger.debug("online ingest name=%r: CardNotFoundError", name)
        return {"found": False}
    except psycopg.errors.UniqueViolation:
        logger.debug("online ingest name=%r: UniqueViolation, re-fetching concurrently-inserted row", name)
        pass  # a concurrent request won the insert race -- fall through and re-fetch its row
    except Exception:
        logger.exception("online ingest failed for card name=%r", name)
        return {"found": False}

    if card_id is not None:
        card = get_card_by_id(card_id)
    else:
        card = get_card_by_name(name)
    if card is None:
        logger.debug("lookup_card name=%r: post-ingest lookup found no row", name)
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


def build_tool_dispatch(
    llm_client: LLMClient,
    embedding_client: EmbeddingClient,
    *,
    online_ingest_enabled: bool = True,
    on_ingest_start: Callable[[str], None] | None = None,
) -> dict[str, Callable[[dict], dict]]:
    # search_rulebook and resolve_chain are temporarily disabled (pipeline instability) --
    # left out of the dispatch dict so the loop can never invoke them even if a caller
    # passes them; the underlying implementations stay intact for re-enabling later.
    return {
        "lookup_card": lambda args: lookup_card(
            args,
            llm_client=llm_client,
            online_ingest_enabled=online_ingest_enabled,
            on_ingest_start=on_ingest_start,
        ),
        "get_rulings": get_rulings,
    }
