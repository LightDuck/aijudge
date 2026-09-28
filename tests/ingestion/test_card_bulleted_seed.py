import json
import os

import pytest

pytestmark = pytest.mark.skipif("TEST_DATABASE_URL" not in os.environ, reason="requires TEST_DATABASE_URL (a dedicated test Postgres database)")


def setup_function():
    from aijudge.db.connection import get_connection
    from aijudge.db.migrate import run_migrations

    run_migrations()
    with get_connection() as conn:
        conn.execute("TRUNCATE card_bulleted")
        conn.commit()


def _write_fixture(tmp_path, entries):
    path = tmp_path / "card_bulleted.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


# Real cards with their real passcodes, taken as-is from the Bulleted Effects
# Review: final category as the user placed it, and the reason the fixture
# export keeps (the first-sort reason for a kept card, None for a moved one).
_VARIABLE_FORM = {
    "ygoprodeck_id": "64038662",
    "name": "Variable Form",
    "category_code": "B1",
    "reason": 'activate exactly 1 bullet (activation): "activate 1 of these"',
}
_DARK_MAGIC_EXPANDED = {
    "ygoprodeck_id": "00111280",
    "name": "Dark Magic Expanded",
    "category_code": "C",
    "reason": 'criteria on card decide which bullet(s) apply: "based on"',
}
# Moved from D1 to B1 during review, so its first-sort reason isn't kept.
_X_SABER_SOUZA = {"ygoprodeck_id": "63612442", "name": "X-Saber Souza", "category_code": "B1", "reason": None}

_ENTRIES = [_VARIABLE_FORM, _DARK_MAGIC_EXPANDED, _X_SABER_SOUZA]


def _count():
    from aijudge.db.connection import get_connection

    with get_connection() as conn:
        return conn.execute("SELECT count(*) FROM card_bulleted").fetchone()[0]


def test_seed_loads_every_fixture_entry(tmp_path):
    from aijudge.db.card_bulleted_repo import get_card_bulleted
    from aijudge.ingestion.card_bulleted_seed import seed_card_bulleted

    assert seed_card_bulleted(_write_fixture(tmp_path, _ENTRIES)) == 3

    variable_form = get_card_bulleted("64038662")
    assert (variable_form["code"], variable_form["reason"]) == ("B1", _VARIABLE_FORM["reason"])
    assert get_card_bulleted("00111280")["code"] == "C"
    assert get_card_bulleted("63612442")["reason"] is None


def test_reseeding_does_not_duplicate_rows(tmp_path):
    from aijudge.ingestion.card_bulleted_seed import seed_card_bulleted

    path = _write_fixture(tmp_path, _ENTRIES)
    seed_card_bulleted(path)
    seed_card_bulleted(path)

    assert _count() == 3


def test_reseeding_keeps_a_hand_written_note(tmp_path):
    from aijudge.db.card_bulleted_repo import get_card_bulleted, update_card_bulleted_note
    from aijudge.ingestion.card_bulleted_seed import seed_card_bulleted

    path = _write_fixture(tmp_path, _ENTRIES)
    seed_card_bulleted(path)
    update_card_bulleted_note("63612442", "moved from D1 during review")
    seed_card_bulleted(path)

    assert get_card_bulleted("63612442")["note"] == "moved from D1 during review"


def test_unknown_category_code_raises_and_writes_nothing(tmp_path):
    from aijudge.ingestion.card_bulleted_seed import UnknownBulletCategoryError, seed_card_bulleted

    # A real card, with a category code that isn't in the legend.
    xyz_avenger = {"ygoprodeck_id": "86062400", "name": "Xyz Avenger", "category_code": "Q9", "reason": None}

    with pytest.raises(UnknownBulletCategoryError, match="Q9"):
        seed_card_bulleted(_write_fixture(tmp_path, _ENTRIES + [xyz_avenger]))

    assert _count() == 0


def test_default_fixture_path_points_into_the_package():
    from aijudge.ingestion.card_bulleted_seed import DEFAULT_FIXTURE_PATH

    assert DEFAULT_FIXTURE_PATH.parts[-3:] == ("ingestion", "data", "card_bulleted.json")
