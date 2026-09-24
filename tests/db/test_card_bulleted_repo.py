import os

import psycopg
import pytest

pytestmark = pytest.mark.skipif("TEST_DATABASE_URL" not in os.environ, reason="requires TEST_DATABASE_URL (a dedicated test Postgres database)")

# Real cards with their real passcodes, categories and reasons from the
# Bulleted Effects Review. X-Saber Souza's first sort put it in D1; the user
# moved it to B1, so its final reason is None.
_ORICHALCOS_SWORD_OF_SEALING = "00847217"
_ORICHALCOS_REASON = 'one binary gate grants this bullet once its trigger fires: "gains this effect"'
_VARIABLE_FORM = "64038662"
_VARIABLE_FORM_REASON = 'activate exactly 1 bullet (activation): "activate 1 of these"'
_DARK_MAGIC_EXPANDED = "00111280"
_X_SABER_SOUZA = "63612442"
_X_SABER_SOUZA_FIRST_SORT_REASON = (
    "picks 1 effect then grants it (mechanism is a player choice, not a criteria gate -- kept here as a "
    "deliberate exception)"
)
# A real card that is never written to card_bulleted in these tests.
_XYZ_AVENGER = "86062400"


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

    upsert_card_bulleted(
        ygoprodeck_id=_ORICHALCOS_SWORD_OF_SEALING, bullet_category_id=_category_id("D1"), reason=_ORICHALCOS_REASON
    )

    assert get_card_bulleted(_ORICHALCOS_SWORD_OF_SEALING) == {
        "ygoprodeck_id": _ORICHALCOS_SWORD_OF_SEALING,
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
        "reason": _ORICHALCOS_REASON,
        "note": None,
    }


def test_get_returns_none_for_a_card_with_no_row():
    from aijudge.db.card_bulleted_repo import get_card_bulleted

    assert get_card_bulleted(_XYZ_AVENGER) is None


def test_upsert_zero_pads_a_short_passcode():
    from aijudge.db.card_bulleted_repo import get_card_bulleted, upsert_card_bulleted

    # YGOPRODeck returns Dark Magic Expanded's passcode 00111280 as the int 111280.
    upsert_card_bulleted(ygoprodeck_id="111280", bullet_category_id=_category_id("C"))

    assert get_card_bulleted(_DARK_MAGIC_EXPANDED)["ygoprodeck_id"] == _DARK_MAGIC_EXPANDED


def test_get_matches_with_or_without_the_leading_zeros():
    from aijudge.db.card_bulleted_repo import get_card_bulleted, upsert_card_bulleted

    upsert_card_bulleted(ygoprodeck_id=_DARK_MAGIC_EXPANDED, bullet_category_id=_category_id("C"))

    assert get_card_bulleted("111280")["code"] == "C"


def test_reason_is_nullable():
    from aijudge.db.card_bulleted_repo import get_card_bulleted, upsert_card_bulleted

    upsert_card_bulleted(ygoprodeck_id=_X_SABER_SOUZA, bullet_category_id=_category_id("B1"))

    assert get_card_bulleted(_X_SABER_SOUZA)["reason"] is None


def test_upsert_updates_category_and_reason_but_keeps_note():
    from aijudge.db.card_bulleted_repo import get_card_bulleted, update_card_bulleted_note, upsert_card_bulleted

    # Replays X-Saber Souza's review: first sorted into D1, then moved to B1.
    upsert_card_bulleted(
        ygoprodeck_id=_X_SABER_SOUZA, bullet_category_id=_category_id("D1"), reason=_X_SABER_SOUZA_FIRST_SORT_REASON
    )
    update_card_bulleted_note(_X_SABER_SOUZA, "moved from D1 during review")
    upsert_card_bulleted(ygoprodeck_id=_X_SABER_SOUZA, bullet_category_id=_category_id("B1"), reason=None)

    row = get_card_bulleted(_X_SABER_SOUZA)
    assert (row["code"], row["reason"], row["note"]) == ("B1", None, "moved from D1 during review")


def test_one_row_per_passcode():
    from aijudge.db.card_bulleted_repo import upsert_card_bulleted
    from aijudge.db.connection import get_connection

    upsert_card_bulleted(ygoprodeck_id=_X_SABER_SOUZA, bullet_category_id=_category_id("D1"))
    upsert_card_bulleted(ygoprodeck_id=_X_SABER_SOUZA, bullet_category_id=_category_id("B1"))

    with get_connection() as conn:
        assert conn.execute("SELECT count(*) FROM card_bulleted").fetchone()[0] == 1


def test_unknown_bullet_category_id_is_rejected():
    import uuid

    from aijudge.db.card_bulleted_repo import upsert_card_bulleted

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        upsert_card_bulleted(ygoprodeck_id=_VARIABLE_FORM, bullet_category_id=uuid.uuid4())


def test_update_note_on_a_card_with_no_row_raises():
    from aijudge.db.card_bulleted_repo import update_card_bulleted_note

    with pytest.raises(LookupError):
        update_card_bulleted_note(_XYZ_AVENGER, "note")


def test_bulk_upsert_writes_every_row_in_one_call():
    from aijudge.db.card_bulleted_repo import get_card_bulleted, upsert_card_bulleted_rows

    count = upsert_card_bulleted_rows([
        {"ygoprodeck_id": _VARIABLE_FORM, "bullet_category_id": _category_id("B1"), "reason": _VARIABLE_FORM_REASON},
        {"ygoprodeck_id": "111280", "bullet_category_id": _category_id("C"), "reason": None},
    ])

    assert count == 2
    assert get_card_bulleted(_VARIABLE_FORM)["code"] == "B1"
    assert get_card_bulleted(_DARK_MAGIC_EXPANDED)["code"] == "C"


def test_rows_survive_rerunning_migrations():
    from aijudge.db.card_bulleted_repo import get_card_bulleted, upsert_card_bulleted
    from aijudge.db.migrate import run_migrations

    upsert_card_bulleted(ygoprodeck_id=_VARIABLE_FORM, bullet_category_id=_category_id("B1"))
    run_migrations()

    assert get_card_bulleted(_VARIABLE_FORM)["code"] == "B1"
