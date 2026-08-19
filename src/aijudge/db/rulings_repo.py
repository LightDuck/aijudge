from datetime import date

from .connection import get_connection


def insert_ruling(*, card_id: str, ruling_text: str, source: str, ruling_date: date | None = None) -> str:
    with get_connection() as conn:
        row = conn.execute(
            """
            INSERT INTO rulings (card_id, ruling_text, source, ruling_date)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (card_id, ruling_text, source, ruling_date),
        ).fetchone()
        conn.commit()
        return str(row[0])


def get_rulings_for_card(card_id: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, ruling_text, source, ruling_date FROM rulings WHERE card_id = %s",
            (card_id,),
        ).fetchall()
    return [
        {"id": str(r[0]), "ruling_text": r[1], "source": r[2], "ruling_date": r[3]}
        for r in rows
    ]
