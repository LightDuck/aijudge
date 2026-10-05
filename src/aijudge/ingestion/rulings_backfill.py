"""One-off, re-runnable backfill for cards ingested before rulings grounding.

Stores each card's Konami id, re-fetches rulings for cards whose stored "zero
rulings" may have been a silently swallowed fetch failure, and resolves every
ruling's <<konami_id>> placeholders. Never deletes a ruling or rewrites its
raw text. Run after run_migrations():

    python -c "from aijudge.ingestion.rulings_backfill import backfill_rulings; print(backfill_rulings())"
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from aijudge.db.cards_repo import list_cards, set_card_rulings_source
from aijudge.db.rulings_repo import (
    get_rulings_for_card,
    insert_ruling,
    list_unresolved_rulings,
    update_ruling_resolution,
)
from aijudge.ingestion import ygoresources_client
from aijudge.ingestion.ygoprodeck_client import fetch_card
from aijudge.ingestion.ygoresources_client import fetch_rulings, parse_referenced_ids, resolve_ruling_text

logger = logging.getLogger(__name__)


@dataclass
class BackfillReport:
    konami_ids_stored: int = 0
    rulings_refetched: int = 0
    rulings_resolved: int = 0
    failures: list[str] = field(default_factory=list)


def _store_konami_id(card: dict, fetch_card_fn: Callable[..., dict], report: BackfillReport) -> int | None:
    try:
        # YGOPRODeck takes the passcode as a number; int() drops the printed leading zero.
        card_data = fetch_card_fn(str(int(card["ygoprodeck_id"])), field="id")
    except Exception:
        logger.exception("could not fetch %s from YGOPRODeck", card["name"])
        report.failures.append(card["name"])
        return None
    konami_id = (card_data.get("misc_info") or [{}])[0].get("konami_id")
    if konami_id is None:
        set_card_rulings_source(card["id"], rulings_status="no_konami_id")
        return None
    set_card_rulings_source(card["id"], rulings_status=card["rulings_status"], ygoresources_id=str(konami_id))
    report.konami_ids_stored += 1
    return konami_id


def _refetch_if_empty(
    card: dict, konami_id: int, fetch_rulings_fn: Callable[..., list[dict]], report: BackfillReport
) -> None:
    if get_rulings_for_card(card["id"]):
        set_card_rulings_source(card["id"], rulings_status="fetched")
        return
    try:
        rulings = fetch_rulings_fn(konami_id)
    except Exception:
        logger.exception("rulings refetch failed for %s", card["name"])
        set_card_rulings_source(card["id"], rulings_status="failed")
        report.failures.append(card["name"])
        return
    for ruling in rulings:
        raw_date = ruling.get("date")
        insert_ruling(
            card_id=card["id"],
            ruling_text=ruling["text"],
            source="db.ygoresources",
            ruling_date=date.fromisoformat(raw_date) if raw_date else None,
            referenced_konami_ids=parse_referenced_ids(ruling["text"]),
        )
    report.rulings_refetched += len(rulings)
    set_card_rulings_source(card["id"], rulings_status="fetched")


def backfill_rulings(
    *,
    fetch_card_fn: Callable[..., dict] = fetch_card,
    fetch_rulings_fn: Callable[..., list[dict]] = fetch_rulings,
    fetch_card_name_index_fn: Callable[[], dict[int, list[str]]] | None = None,
) -> BackfillReport:
    report = BackfillReport()

    for card in list_cards():
        if card["rulings_status"] == "no_konami_id":
            continue
        konami_id = int(card["ygoresources_id"]) if card["ygoresources_id"] else None
        if konami_id is None:
            konami_id = _store_konami_id(card, fetch_card_fn, report)
            if konami_id is None:
                continue
        if card["rulings_status"] in (None, "failed"):
            _refetch_if_empty(card, konami_id, fetch_rulings_fn, report)

    unresolved = list_unresolved_rulings()
    if not unresolved:
        return report
    fetch_index = fetch_card_name_index_fn or ygoresources_client.cached_card_name_index
    try:
        name_index = fetch_index()
    except Exception:
        logger.exception("card name index unavailable; rulings left unresolved")
        report.failures.append("card name index")
        return report
    for ruling in unresolved:
        resolved, referenced_ids = resolve_ruling_text(ruling["ruling_text"], name_index)
        update_ruling_resolution(ruling["id"], ruling_text_resolved=resolved, referenced_konami_ids=referenced_ids)
        report.rulings_resolved += 1
    return report
