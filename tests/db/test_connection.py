import os

import psycopg
import pytest

pytestmark = pytest.mark.skipif("DATABASE_URL" not in os.environ, reason="requires a running Postgres instance")


def test_get_connection_returns_a_working_connection_against_a_real_database():
    from aijudge.db.connection import get_connection

    with get_connection() as conn:
        row = conn.execute("SELECT 1").fetchone()
        assert row[0] == 1


def test_get_connection_tolerates_a_programming_error_from_register_vector(monkeypatch):
    import aijudge.db.connection as connection_module

    def raise_programming_error(conn):
        raise psycopg.ProgrammingError("type \"vector\" does not exist")

    monkeypatch.setattr(connection_module, "register_vector", raise_programming_error)

    with connection_module.get_connection() as conn:
        row = conn.execute("SELECT 1").fetchone()
        assert row[0] == 1


def test_get_connection_raises_key_error_when_database_url_is_unset(monkeypatch):
    from aijudge.db.connection import get_connection

    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(KeyError):
        get_connection()
