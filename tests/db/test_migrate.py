import os

import pytest

pytestmark = pytest.mark.skipif("DATABASE_URL" not in os.environ, reason="requires a running Postgres instance")


def test_run_migrations_creates_all_tables():
    from aijudge.db.connection import get_connection
    from aijudge.db.migrate import run_migrations

    run_migrations()
    with get_connection() as conn:
        for table in ("cards", "card_errata_versions", "rulings", "card_effects_structured", "rulebook_chunks", "qa_test_cases"):
            row = conn.execute("SELECT to_regclass(%s)", (f"public.{table}",)).fetchone()
            assert row[0] == table, f"expected table {table!r} to exist"
