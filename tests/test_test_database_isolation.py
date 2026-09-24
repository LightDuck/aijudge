import os
from pathlib import Path

from dotenv import dotenv_values

# DB tests truncate tables, so the suite must never point at the database the
# app itself uses (the .env DATABASE_URL). tests/conftest.py enforces this.
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def test_suite_never_uses_the_app_database_url():
    app_database_url = dotenv_values(_ENV_FILE).get("DATABASE_URL") if _ENV_FILE.exists() else None

    assert os.environ.get("DATABASE_URL") != app_database_url or app_database_url is None
