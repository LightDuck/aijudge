import os
import uuid

import pytest

pytestmark = pytest.mark.skipif("TEST_DATABASE_URL" not in os.environ, reason="requires TEST_DATABASE_URL (a dedicated test Postgres database)")


# No TRUNCATE here, unlike the other tests/db modules: bullet_category rows
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

    assert isinstance(d1.pop("id"), uuid.UUID)
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


def test_ids_are_stable_across_reruns_of_migrations():
    from aijudge.db.bullet_categories_repo import get_all_bullet_categories
    from aijudge.db.migrate import run_migrations

    before = {c["code"]: c["id"] for c in get_all_bullet_categories()}
    run_migrations()
    after = {c["code"]: c["id"] for c in get_all_bullet_categories()}

    assert before == after


def test_id_is_primary_key_and_code_is_unique():
    from aijudge.db.connection import get_connection

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT c.contype, a.attname
            FROM pg_constraint c
            JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
            WHERE c.conrelid = 'public.bullet_category'::regclass AND c.contype IN ('p', 'u')
            """
        ).fetchall()

    assert sorted(rows) == [("p", "id"), ("u", "code")]


def test_legacy_bullet_categories_table_is_migrated_in_place():
    from aijudge.db.bullet_categories_repo import get_bullet_category
    from aijudge.db.connection import get_connection
    from aijudge.db.migrate import run_migrations

    # Recreate the pre-rename shape: plural name, code as primary key.
    with get_connection() as conn:
        conn.execute("DROP TABLE bullet_category")
        conn.execute(
            "CREATE TABLE bullet_categories ("
            "code TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL, note TEXT)"
        )
        conn.execute("INSERT INTO bullet_categories (code, name, description) VALUES ('Q9', 'Legacy', 'kept')")

    run_migrations()

    with get_connection() as conn:
        assert conn.execute("SELECT to_regclass('public.bullet_categories')").fetchone()[0] is None
    legacy = get_bullet_category("Q9")
    assert legacy["name"] == "Legacy"
    assert isinstance(legacy["id"], uuid.UUID)

    with get_connection() as conn:
        conn.execute("DELETE FROM bullet_category WHERE code = 'Q9'")
