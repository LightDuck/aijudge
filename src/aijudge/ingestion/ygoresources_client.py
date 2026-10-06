import functools
import logging
import re
from datetime import date
from typing import Callable

import requests

BASE_URL = "https://db.ygoresources.com"

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

logger = logging.getLogger(__name__)

NAME_INDEX_URL = f"{BASE_URL}/data/idx/card/name/en"

_PLACEHOLDER_RE = re.compile(r"<<(\d+)>>")


def parse_referenced_ids(text: str) -> list[int]:
    """Every distinct Konami id ygoresources wrote as a <<id>> placeholder, in
    first-appearance order. Pure: needs no network, so it works even when the
    name index can't be fetched."""
    ids: list[int] = []
    for match in _PLACEHOLDER_RE.finditer(text):
        konami_id = int(match.group(1))
        if konami_id not in ids:
            ids.append(konami_id)
    return ids


def invert_name_index(index: dict[str, list[int]]) -> dict[int, list[str]]:
    inverted: dict[int, list[str]] = {}
    for name, konami_ids in index.items():
        for konami_id in konami_ids:
            inverted.setdefault(konami_id, []).append(name)
    return inverted


def fetch_card_name_index(*, http_get: Callable[..., "requests.Response"] = requests.get) -> dict[int, list[str]]:
    response = http_get(NAME_INDEX_URL, timeout=30)
    response.raise_for_status()
    return invert_name_index(response.json())


@functools.lru_cache(maxsize=1)
def cached_card_name_index() -> dict[int, list[str]]:
    """One download per process: the on-demand lookup_card path ingests cards
    one at a time, and the index is large and slow-changing. Exceptions aren't
    cached by lru_cache, so a failed download is retried next time."""
    return fetch_card_name_index()


def fetch_current_card_name(
    konami_id: int, *, http_get: Callable[..., "requests.Response"] = requests.get
) -> str | None:
    response = http_get(f"{BASE_URL}/data/card/{konami_id}", timeout=10)
    response.raise_for_status()
    return ((response.json().get("cardData") or {}).get("en") or {}).get("name")


def _unknown_card(konami_id: int | str) -> str:
    return f"[card #{konami_id}]"


def resolve_ruling_text(
    text: str,
    name_index: dict[int, list[str]],
    *,
    http_get: Callable[..., "requests.Response"] = requests.get,
) -> tuple[str, list[int]]:
    """Replace each <<id>> with that card's English name. A renamed card (more
    than one name in the index) is looked up for its single current name. An
    id that can't be named becomes "[card #id]" -- never a guess."""
    ids = parse_referenced_ids(text)
    names: dict[int, str | None] = {}
    for konami_id in ids:
        candidates = name_index.get(konami_id, [])
        if len(candidates) == 1:
            names[konami_id] = candidates[0]
        elif len(candidates) > 1:
            try:
                names[konami_id] = fetch_current_card_name(konami_id, http_get=http_get)
            except requests.RequestException:
                logger.exception("could not fetch the current name of konami_id=%s", konami_id)
                names[konami_id] = None

    def replace(match: re.Match) -> str:
        konami_id = int(match.group(1))
        return names.get(konami_id) or _unknown_card(konami_id)

    return _PLACEHOLDER_RE.sub(replace, text), ids


def unresolved_display_text(text: str) -> str:
    """Display form of a ruling whose names were never resolved."""
    return _PLACEHOLDER_RE.sub(lambda match: _unknown_card(match.group(1)), text)


def parse_ruling_date(raw_date: str | None) -> date | None:
    """A fetched ruling's date, or None when it's missing or not a real date
    (e.g. "2025-13-45"): an undated ruling is honest, a guessed date is not."""
    if not raw_date:
        return None
    try:
        return date.fromisoformat(raw_date)
    except ValueError:
        logger.warning("ruling date %r is not a valid date; storing the ruling undated", raw_date)
        return None


def ruling_row(
    ruling: dict, *, ruling_text_resolved: str | None, referenced_konami_ids: list[int]
) -> dict:
    """A fetched ruling ({"text", "date"}) as a rulings_repo.insert_rulings row."""
    return {
        "ruling_text": ruling["text"],
        "source": "db.ygoresources",
        "ruling_date": parse_ruling_date(ruling.get("date")),
        "ruling_text_resolved": ruling_text_resolved,
        "referenced_konami_ids": referenced_konami_ids,
    }


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
