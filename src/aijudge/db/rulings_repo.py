from collections.abc import Sequence
from datetime import date

from .connection import get_connection

_RULING_SELECT = "SELECT id, ruling_text, source, ruling_date, ruling_text_resolved, referenced_konami_ids"


def _row_to_ruling(row) -> dict:
    return {
        "id": str(row[0]),
        "ruling_text": row[1],
        "source": row[2],
        "ruling_date": row[3],
        "ruling_text_resolved": row[4],
        "referenced_konami_ids": list(row[5] or []),
    }


def insert_ruling(
    *,
    card_id: str,
    ruling_text: str,
    source: str,
    ruling_date: date | None = None,
    ruling_text_resolved: str | None = None,
    referenced_konami_ids: Sequence[int] = (),
) -> str:
    with get_connection() as conn:
        row = conn.execute(
            """
            INSERT INTO rulings (card_id, ruling_text, source, ruling_date, ruling_text_resolved, referenced_konami_ids)
            VALUES (%s, %s, %s, %s, %s, %s::integer[])
            RETURNING id
            """,
            (card_id, ruling_text, source, ruling_date, ruling_text_resolved, list(referenced_konami_ids)),
        ).fetchone()
        conn.commit()
        return str(row[0])


def get_rulings_for_card(card_id: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(f"{_RULING_SELECT} FROM rulings WHERE card_id = %s", (card_id,)).fetchall()
    return [_row_to_ruling(r) for r in rows]


def list_unresolved_rulings() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            f"{_RULING_SELECT}, card_id FROM rulings WHERE ruling_text_resolved IS NULL ORDER BY id"
        ).fetchall()
    return [{**_row_to_ruling(r), "card_id": str(r[6])} for r in rows]


def update_ruling_resolution(
    ruling_id: str, *, ruling_text_resolved: str, referenced_konami_ids: Sequence[int]
) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE rulings SET ruling_text_resolved = %s, referenced_konami_ids = %s::integer[] WHERE id = %s",
            (ruling_text_resolved, list(referenced_konami_ids), ruling_id),
        )
        conn.commit()
