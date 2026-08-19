from typing import Callable

import requests

API_URL = "https://db.ygoresources.com/api/rulings"


def fetch_rulings(card_name: str, *, http_get: Callable[..., "requests.Response"] = requests.get) -> list[dict]:
    response = http_get(API_URL, params={"card": card_name}, timeout=10)
    response.raise_for_status()
    body = response.json()
    return [{"text": r["text"], "date": r.get("date")} for r in body.get("rulings", [])]
