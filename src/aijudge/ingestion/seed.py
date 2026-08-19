from datetime import date, datetime
from typing import Callable

from aijudge.db.cards_repo import insert_card
from aijudge.db.effects_repo import confirm_effect, insert_pending_effect
from aijudge.db.rulings_repo import insert_ruling
from aijudge.effect_parser.parser import classify_effect_type, parse_psct
from aijudge.effect_parser.review_agent import review_parsed_effect
from aijudge.ingestion.ygoprodeck_client import fetch_card
from aijudge.ingestion.ygoresources_client import fetch_rulings
from aijudge.llm.client import LLMClient

HAND_PICKED_CARDS: list[str] = [
    "Ash Blossom & Joyous Spring",
    "Called by the Grave",
    "Infinite Impermanence",
    "Effect Veiler",
    "Solemn Strike",
]


def seed_card(
    name: str,
    *,
    llm_client: LLMClient,
    fetch_card_fn: Callable[..., dict] = fetch_card,
    fetch_rulings_fn: Callable[..., list[dict]] = fetch_rulings,
) -> str:
    card_data = fetch_card_fn(name)
    card_type = card_data["type"]
    card_text = card_data["desc"]

    card_id = insert_card(
        name=card_data["name"],
        card_text=card_text,
        card_type=card_type,
        source="ygoprodeck",
        fetched_at=datetime.utcnow().date(),
        ygoprodeck_id=str(card_data["id"]),
    )

    for ruling in fetch_rulings_fn(name):
        raw_date = ruling.get("date")
        insert_ruling(
            card_id=card_id,
            ruling_text=ruling["text"],
            source="db.ygoresources",
            ruling_date=date.fromisoformat(raw_date) if raw_date else None,
        )

    effect_type = classify_effect_type(card_text, card_type=card_type)
    parsed = parse_psct(card_text)

    review = review_parsed_effect(
        llm_client,
        raw_text=card_text,
        activation_condition=parsed.activation_condition,
        cost=parsed.cost,
        targeting=parsed.targeting,
        effect=parsed.effect,
    )

    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type=effect_type.value,
        effect=parsed.effect,
        activation_condition=parsed.activation_condition,
        cost=parsed.cost,
        targeting=parsed.targeting,
        has_target=(parsed.targeting is not None),
        confidence_score=review.confidence,
    )

    if review.auto_confirmed:
        confirm_effect(effect_id)

    return card_id


def run_seed(llm_client: LLMClient) -> list[str]:
    return [seed_card(name, llm_client=llm_client) for name in HAND_PICKED_CARDS]
