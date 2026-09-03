from datetime import date
from typing import Callable

import requests

PSCT_CUTOFF_DATE = date(2011, 7, 8)

CARDSETS_API_URL = "https://db.ygoprodeck.com/api/v7/cardsets.php"


def fetch_sets_index(*, http_get: Callable[..., "requests.Response"] = requests.get) -> dict[str, date]:
    """Fetch YGOPRODeck's full set catalog once and index it by set_name ->
    tcg_date. Meant to be called once per ingestion run (not once per card)
    and reused, since this is a large, slowly-changing catalog."""
    response = http_get(CARDSETS_API_URL, timeout=10)
    response.raise_for_status()
    index: dict[str, date] = {}
    for row in response.json():
        set_name = row.get("set_name")
        tcg_date = row.get("tcg_date")
        if set_name and tcg_date:
            index[set_name] = date.fromisoformat(tcg_date)
    return index


def is_deterministic_parse_eligible(card_sets: list[dict], sets_index: dict[str, date]) -> bool:
    """Whether any printing of this card is dated on/after PSCT_CUTOFF_DATE.

    Checks every entry in `card_sets` (as returned by YGOPRODeck's
    cardinfo.php), not just the first -- a card's original printing can
    predate PSCT while a later reprint brings its text current (see
    Elemental HERO Mudballman in the design spec's worked examples).
    """
    for card_set in card_sets:
        set_name = card_set.get("set_name")
        if set_name is None:
            continue
        printed_date = sets_index.get(set_name)
        if printed_date is not None and printed_date >= PSCT_CUTOFF_DATE:
            return True
    return False
