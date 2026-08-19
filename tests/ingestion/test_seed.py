import os
from datetime import date

import pytest

pytestmark = pytest.mark.skipif("DATABASE_URL" not in os.environ, reason="requires a running Postgres instance")


def setup_function():
    from aijudge.db.connection import get_connection
    from aijudge.db.migrate import run_migrations

    run_migrations()
    with get_connection() as conn:
        conn.execute("TRUNCATE cards CASCADE")
        conn.commit()


def test_seed_card_stores_card_ruling_and_confirms_a_high_confidence_effect():
    from aijudge.db.cards_repo import get_card_by_name
    from aijudge.db.effects_repo import get_confirmed_effect
    from aijudge.db.rulings_repo import get_rulings_for_card
    from aijudge.ingestion.seed import seed_card
    from aijudge.llm.client import MockLLMClient

    def fake_fetch_card(name, http_get=None):
        return {
            "name": name,
            "type": "Quick-Play Spell",
            "desc": "You can target 1 banished monster; banish it.",
        }

    def fake_fetch_rulings(name, http_get=None):
        return [{"text": "Can target monsters banished this turn.", "date": "2021-01-01"}]

    llm_client = MockLLMClient()
    llm_client.queue_response("0.97")  # review agent confidence for the parsed effect

    card_id = seed_card(
        "Called by the Grave",
        llm_client=llm_client,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=fake_fetch_rulings,
    )

    card = get_card_by_name("Called by the Grave")
    assert card is not None
    assert card["id"] == card_id

    rulings = get_rulings_for_card(card_id)
    assert len(rulings) == 1

    confirmed_effect = get_confirmed_effect(card_id)
    assert confirmed_effect is not None
    assert confirmed_effect["targeting"] == "target 1 banished monster"


def test_seed_card_leaves_low_confidence_effect_pending():
    from aijudge.db.cards_repo import get_card_by_name
    from aijudge.db.effects_repo import get_confirmed_effect
    from aijudge.ingestion.seed import seed_card
    from aijudge.llm.client import MockLLMClient

    def fake_fetch_card(name, http_get=None):
        return {
            "name": name,
            "type": "Trap Card",
            "desc": "Target 1 face-up monster; negate its effects.",
        }

    def fake_fetch_rulings(name, http_get=None):
        return []

    llm_client = MockLLMClient()
    llm_client.queue_response("0.3")  # deliberately low confidence

    card_id = seed_card(
        "Ambiguous Trap",
        llm_client=llm_client,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=fake_fetch_rulings,
    )

    assert get_card_by_name("Ambiguous Trap")["id"] == card_id
    assert get_confirmed_effect(card_id) is None
