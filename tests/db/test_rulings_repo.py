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


def test_insert_and_get_rulings_for_card():
    from aijudge.db.cards_repo import insert_card
    from aijudge.db.rulings_repo import get_rulings_for_card, insert_ruling

    card_id = insert_card(
        name="Ash Blossom & Joyous Spring",
        card_text="You can only use each of the following effects of \"Ash Blossom & Joyous Spring\" once per turn.",
        card_type="Effect Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
    )

    insert_ruling(
        card_id=card_id,
        ruling_text="Ash Blossom's effect cannot be activated in response to itself.",
        source="db.ygoresources",
        ruling_date=date(2021, 1, 1),
    )

    rulings = get_rulings_for_card(card_id)

    assert len(rulings) == 1
    assert rulings[0]["source"] == "db.ygoresources"


def test_get_rulings_for_card_returns_empty_list_when_none_exist():
    from aijudge.db.cards_repo import insert_card
    from aijudge.db.rulings_repo import get_rulings_for_card

    card_id = insert_card(
        name="No Rulings Card",
        card_text="Text.",
        card_type="Normal Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
    )

    assert get_rulings_for_card(card_id) == []
