import os

import psycopg
import pytest

pytestmark = pytest.mark.skipif("TEST_DATABASE_URL" not in os.environ, reason="requires TEST_DATABASE_URL (a dedicated test Postgres database)")


def setup_function():
    from aijudge.db.connection import get_connection
    from aijudge.db.migrate import run_migrations

    run_migrations()
    with get_connection() as conn:
        conn.execute("TRUNCATE card_bulleted")
        conn.commit()


def _category_id(code):
    from aijudge.db.bullet_categories_repo import get_bullet_category

    return get_bullet_category(code)["id"]


def test_upsert_then_get_joins_the_category():
    from aijudge.db.card_bulleted_repo import get_card_bulleted, upsert_card_bulleted

    upsert_card_bulleted(ygoprodeck_id="32295838", bullet_category_id=_category_id("D1"), reason="gains these effects")

    assert get_card_bulleted("32295838") == {
        "ygoprodeck_id": "32295838",
        "code": "D1",
        "name": "Mandatory grant",
        "description": (
            "1 or more bullets, granted as a single indivisible bundle: one binary condition on the card either "
            "grants all of them or none of them. There is no branch and no scale — the bundle is never split "
            "into a subset."
        ),
        "category_note": (
            "Contrast with C: a card whose criteria select a subset of bullets, or move between them as some "
            "value changes, belongs in C, not here, even if the bullets are grant-phrased."
        ),
        "reason": "gains these effects",
        "note": None,
    }


def test_get_returns_none_for_an_unknown_passcode():
    from aijudge.db.card_bulleted_repo import get_card_bulleted

    assert get_card_bulleted("12345678") is None


def test_upsert_zero_pads_a_short_passcode():
    from aijudge.db.card_bulleted_repo import get_card_bulleted, upsert_card_bulleted

    upsert_card_bulleted(ygoprodeck_id="7403341", bullet_category_id=_category_id("C"))

    assert get_card_bulleted("07403341")["ygoprodeck_id"] == "07403341"


def test_get_matches_with_or_without_the_leading_zero():
    from aijudge.db.card_bulleted_repo import get_card_bulleted, upsert_card_bulleted

    upsert_card_bulleted(ygoprodeck_id="07403341", bullet_category_id=_category_id("C"))

    assert get_card_bulleted("7403341")["code"] == "C"


def test_reason_is_nullable():
    from aijudge.db.card_bulleted_repo import get_card_bulleted, upsert_card_bulleted

    upsert_card_bulleted(ygoprodeck_id="32295838", bullet_category_id=_category_id("B1"))

    assert get_card_bulleted("32295838")["reason"] is None


def test_upsert_updates_category_and_reason_but_keeps_note():
    from aijudge.db.card_bulleted_repo import get_card_bulleted, update_card_bulleted_note, upsert_card_bulleted

    upsert_card_bulleted(ygoprodeck_id="32295838", bullet_category_id=_category_id("B1"), reason="old")
    update_card_bulleted_note("32295838", "kept here as a deliberate exception")
    upsert_card_bulleted(ygoprodeck_id="32295838", bullet_category_id=_category_id("D1"), reason="new")

    row = get_card_bulleted("32295838")
    assert (row["code"], row["reason"], row["note"]) == ("D1", "new", "kept here as a deliberate exception")


def test_one_row_per_passcode():
    from aijudge.db.card_bulleted_repo import upsert_card_bulleted
    from aijudge.db.connection import get_connection

    upsert_card_bulleted(ygoprodeck_id="32295838", bullet_category_id=_category_id("B1"))
    upsert_card_bulleted(ygoprodeck_id="32295838", bullet_category_id=_category_id("B2"))

    with get_connection() as conn:
        assert conn.execute("SELECT count(*) FROM card_bulleted").fetchone()[0] == 1


def test_unknown_bullet_category_id_is_rejected():
    import uuid

    from aijudge.db.card_bulleted_repo import upsert_card_bulleted

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        upsert_card_bulleted(ygoprodeck_id="32295838", bullet_category_id=uuid.uuid4())


def test_update_note_on_a_missing_passcode_raises():
    from aijudge.db.card_bulleted_repo import update_card_bulleted_note

    with pytest.raises(LookupError):
        update_card_bulleted_note("12345678", "note")


def test_bulk_upsert_writes_every_row_in_one_call():
    from aijudge.db.card_bulleted_repo import get_card_bulleted, upsert_card_bulleted_rows

    count = upsert_card_bulleted_rows([
        {"ygoprodeck_id": "32295838", "bullet_category_id": _category_id("B1"), "reason": "a"},
        {"ygoprodeck_id": "7403341", "bullet_category_id": _category_id("C"), "reason": None},
    ])

    assert count == 2
    assert get_card_bulleted("32295838")["code"] == "B1"
    assert get_card_bulleted("07403341")["code"] == "C"


def test_rows_survive_rerunning_migrations():
    from aijudge.db.card_bulleted_repo import get_card_bulleted, upsert_card_bulleted
    from aijudge.db.migrate import run_migrations

    upsert_card_bulleted(ygoprodeck_id="32295838", bullet_category_id=_category_id("B1"))
    run_migrations()

    assert get_card_bulleted("32295838")["code"] == "B1"
