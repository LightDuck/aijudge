import os

import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector

load_dotenv()


def get_connection() -> psycopg.Connection:
    database_url = os.environ["DATABASE_URL"]
    conn = psycopg.connect(database_url)
    try:
        register_vector(conn)
    except psycopg.ProgrammingError:
        # The `vector` extension may not exist yet on a brand-new
        # database (migrate.py creates it) — fall back to an
        # unregistered connection rather than failing to connect.
        # (pgvector's register_vector raises a plain ProgrammingError,
        # not psycopg.errors.UndefinedObject, when the type is missing.)
        conn.rollback()
    return conn
