from dataclasses import dataclass
from typing import Callable

from aijudge.db.cards_repo import get_card_by_id
from aijudge.llm.client import LLMClient
from aijudge.orchestration.tools import lookup_card


@dataclass
class CardResolution:
    name: str
    status: str  # "resolved" | "not_found" | "ambiguous"
    card: dict | None = None  # raw card row (get_card_by_id shape), only when status == "resolved"


def resolve_named_cards(
    names: list[str],
    *,
    llm_client: LLMClient,
    online_ingest_enabled: bool = True,
    on_ingest_start: Callable[[str], None] | None = None,
    lookup_card_fn: Callable[..., dict] = lookup_card,
    get_card_by_id_fn: Callable[[str], dict | None] = get_card_by_id,
) -> list[CardResolution]:
    resolutions = []
    for name in names:
        result = lookup_card_fn(
            {"name": name},
            llm_client=llm_client,
            online_ingest_enabled=online_ingest_enabled,
            on_ingest_start=on_ingest_start,
        )
        if result.get("ambiguous"):
            resolutions.append(CardResolution(name=name, status="ambiguous"))
        elif result.get("found"):
            resolutions.append(
                CardResolution(name=name, status="resolved", card=get_card_by_id_fn(result["id"]))
            )
        else:
            resolutions.append(CardResolution(name=name, status="not_found"))
    return resolutions
