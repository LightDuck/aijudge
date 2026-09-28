from .cards_repo import normalize_passcode
from .connection import get_connection

_UPSERT = """
    INSERT INTO card_bulleted (ygoprodeck_id, bullet_category_id, reason)
    VALUES (%s, %s, %s)
    ON CONFLICT (ygoprodeck_id) DO UPDATE SET
        bullet_category_id = EXCLUDED.bullet_category_id,
        reason = EXCLUDED.reason
"""


def upsert_card_bulleted(*, ygoprodeck_id: str, bullet_category_id, reason: str | None = None) -> str:
    """Insert or update a card's bullet category. Never touches `note`, which
    holds hand-written decisions that re-seeding must not wipe."""
    with get_connection() as conn:
        row = conn.execute(
            _UPSERT + " RETURNING id", (normalize_passcode(ygoprodeck_id), bullet_category_id, reason)
        ).fetchone()
        conn.commit()
    return str(row[0])


def upsert_card_bulleted_rows(rows: list[dict]) -> int:
    """Upsert many rows in one transaction: all of them are written, or none."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                _UPSERT,
                [(normalize_passcode(r["ygoprodeck_id"]), r["bullet_category_id"], r["reason"]) for r in rows],
            )
        conn.commit()
    return len(rows)


def get_card_bulleted(ygoprodeck_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT cb.ygoprodeck_id, bc.code, bc.name, bc.description, bc.note, cb.reason, cb.note "
            "FROM card_bulleted cb JOIN bullet_category bc ON bc.id = cb.bullet_category_id "
            "WHERE cb.ygoprodeck_id = %s",
            (normalize_passcode(ygoprodeck_id),),
        ).fetchone()
    if row is None:
        return None
    keys = ("ygoprodeck_id", "code", "name", "description", "category_note", "reason", "note")
    return dict(zip(keys, row))


def update_card_bulleted_note(ygoprodeck_id: str, note: str | None) -> None:
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE card_bulleted SET note = %s WHERE ygoprodeck_id = %s", (note, normalize_passcode(ygoprodeck_id))
        )
        if cur.rowcount == 0:
            raise LookupError(f"no card_bulleted row for passcode {ygoprodeck_id!r}")
        conn.commit()
