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


def test_insert_and_get_card_by_name():
    from aijudge.db.cards_repo import get_card_by_name, insert_card

    insert_card(
        name="Called by the Grave",
        card_text=(
            "During either player's turn, if a monster(s) is banished, or a card "
            "or effect in the Graveyard is activated: You can target 1 banished "
            "monster; banish it. You can only activate 1 \"Called by the Grave\" "
            "per turn."
        ),
        card_type="Quick-Play Spell",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
    )

    card = get_card_by_name("Called by the Grave")

    assert card is not None
    assert card["card_type"] == "Quick-Play Spell"
    assert card["has_errata"] is False


def test_get_card_by_name_returns_none_when_missing():
    from aijudge.db.cards_repo import get_card_by_name

    assert get_card_by_name("Nonexistent Card") is None


def test_insert_errata_version_sets_has_errata_flag():
    from aijudge.db.cards_repo import get_card_by_name, insert_card, insert_errata_version

    card_id = insert_card(
        name="Card With Errata",
        card_text="Original text.",
        card_type="Normal Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
    )

    insert_errata_version(card_id=card_id, errata_date=date(2026, 8, 18), errata_text="Errata'd text.")

    card = get_card_by_name("Card With Errata")
    assert card["has_errata"] is True


def test_get_card_by_name_returns_id_as_str():
    from aijudge.db.cards_repo import get_card_by_name, insert_card

    card_id = insert_card(
        name="Test Card for ID Type",
        card_text="Test text",
        card_type="Normal Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
    )

    card = get_card_by_name("Test Card for ID Type")

    assert card is not None
    assert isinstance(card["id"], str), f"Expected card['id'] to be str, got {type(card['id'])}"
    assert card["id"] == card_id
