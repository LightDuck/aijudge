import os
from pathlib import Path

import pytest
from dotenv import dotenv_values, load_dotenv

load_dotenv()

# DB tests truncate tables, so they must never run against the database the
# app itself uses. They run only against TEST_DATABASE_URL (a dedicated
# database, e.g. aijudge_test) and skip when it's unset. DATABASE_URL is
# always overridden here: with no test database it points at an unreachable
# placeholder, so nothing can fall back to the .env value (load_dotenv, also
# called by aijudge.db.connection, never overrides an already-set variable).
_app_database_url = dotenv_values(Path(__file__).resolve().parent.parent / ".env").get("DATABASE_URL")
_test_database_url = os.environ.get("TEST_DATABASE_URL")

if _test_database_url and _test_database_url == _app_database_url:
    raise RuntimeError("TEST_DATABASE_URL must not be the app's DATABASE_URL: DB tests truncate its tables")

os.environ["DATABASE_URL"] = _test_database_url or "postgresql://test-database-not-configured.invalid/aijudge_test"


@pytest.fixture(autouse=True)
def no_real_card_name_index(monkeypatch):
    """seed_card/backfill fall back to ygoresources_client.cached_card_name_index
    when no index function is injected; never let that reach the network in tests."""
    from aijudge.ingestion import ygoresources_client

    monkeypatch.setattr(ygoresources_client, "cached_card_name_index", lambda: {})
