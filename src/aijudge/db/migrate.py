from pathlib import Path

from .connection import get_connection

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def run_migrations() -> None:
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with get_connection() as conn:
        conn.execute(schema_sql)
        conn.commit()
