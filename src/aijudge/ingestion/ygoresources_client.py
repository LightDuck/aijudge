import re
from typing import Callable

import requests

BASE_URL = "https://db.ygoresources.com"

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def fetch_rulings(
    konami_id: int | None, *, http_get: Callable[..., "requests.Response"] = requests.get
) -> list[dict]:
    if konami_id is None:
        return []

    card_response = http_get(f"{BASE_URL}/data/card/{konami_id}", timeout=10)
    card_response.raise_for_status()
    qa_index = card_response.json().get("qaIndex", [])

    rulings = []
    for qa_id in qa_index:
        qa_response = http_get(f"{BASE_URL}/data/qa/{qa_id}", timeout=10)
        qa_response.raise_for_status()
        en = qa_response.json().get("qaData", {}).get("en")
        if en is None:
            continue

        raw_date = (en.get("thisSrc") or {}).get("date")
        rulings.append(
            {
                "text": f"Q: {en['question']}\nA: {en['answer']}",
                "date": raw_date if raw_date and _ISO_DATE_RE.match(raw_date) else None,
            }
        )
    return rulings
