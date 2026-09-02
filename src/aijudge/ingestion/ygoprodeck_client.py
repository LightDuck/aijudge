from typing import Callable

import requests

API_URL = "https://db.ygoprodeck.com/api/v7/cardinfo.php"

PRIORITY_FIELDS = ["name", "fname", "archetype", "id"]


class CardNotFoundError(Exception):
    pass


class AmbiguousCardError(Exception):
    pass


def fetch_card(
    query: str,
    *,
    field: str | None = None,
    http_get: Callable[..., "requests.Response"] = requests.get,
) -> dict:
    fields = [field] if field is not None else PRIORITY_FIELDS
    for candidate_field in fields:
        response = http_get(API_URL, params={candidate_field: query, "misc": "yes"}, timeout=10)
        if response.status_code == 400:
            continue
        response.raise_for_status()
        data = response.json()["data"]
        if len(data) == 1:
            return data[0]
        if len(data) > 1:
            raise AmbiguousCardError(f"multiple cards matched field={candidate_field!r} query={query!r}")
    raise CardNotFoundError(f"no card found for query={query!r}")
