from typing import Callable

import requests

API_URL = "https://db.ygoprodeck.com/api/v7/cardinfo.php"


class CardNotFoundError(Exception):
    pass


def fetch_card(name: str, *, http_get: Callable[..., "requests.Response"] = requests.get) -> dict:
    response = http_get(API_URL, params={"name": name}, timeout=10)
    if response.status_code == 400:
        raise CardNotFoundError(f"no card found for name={name!r}")
    response.raise_for_status()
    data = response.json()["data"]
    return data[0]
