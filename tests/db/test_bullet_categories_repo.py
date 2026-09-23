import os

import pytest

pytestmark = pytest.mark.skipif("DATABASE_URL" not in os.environ, reason="requires a running Postgres instance")


# No TRUNCATE here, unlike the other tests/db modules: bullet_categories rows
# are seeded by schema.sql itself, so they're part of the schema, not test data.
def setup_function():
    from aijudge.db.migrate import run_migrations

    run_migrations()


def test_all_thirteen_categories_are_seeded_in_code_order():
    from aijudge.db.bullet_categories_repo import get_all_bullet_categories

    codes = [c["code"] for c in get_all_bullet_categories()]

    assert codes == ["A1", "A2", "B1", "B2", "C", "D1", "D2", "E1", "E2", "F", "G", "H", "Z"]


def test_category_row_matches_legend_verbatim_including_note():
    from aijudge.db.bullet_categories_repo import get_bullet_category

    d1 = get_bullet_category("D1")

    assert d1 == {
        "code": "D1",
        "name": "Mandatory grant",
        "description": (
            "1 or more bullets, granted as a single indivisible bundle: one binary condition on the card either "
            "grants all of them or none of them. There is no branch and no scale — the bundle is never split "
            "into a subset."
        ),
        "note": (
            "Contrast with C: a card whose criteria select a subset of bullets, or move between them as some "
            "value changes, belongs in C, not here, even if the bullets are grant-phrased."
        ),
    }


def test_category_without_note_has_none_note():
    from aijudge.db.bullet_categories_repo import get_bullet_category

    assert get_bullet_category("A1")["note"] is None


def test_unknown_code_returns_none():
    from aijudge.db.bullet_categories_repo import get_bullet_category

    assert get_bullet_category("Q9") is None


def test_rerunning_migrations_does_not_duplicate_rows():
    from aijudge.db.bullet_categories_repo import get_all_bullet_categories
    from aijudge.db.migrate import run_migrations

    run_migrations()
    run_migrations()

    assert len(get_all_bullet_categories()) == 13
