from .connection import get_connection

_COLUMNS = "id, code, name, description, note"


def _row_to_dict(r) -> dict:
    return {"id": r[0], "code": r[1], "name": r[2], "description": r[3], "note": r[4]}


def get_all_bullet_categories() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(f"SELECT {_COLUMNS} FROM bullet_category ORDER BY code").fetchall()
    return [_row_to_dict(r) for r in rows]


def get_bullet_category(code: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(f"SELECT {_COLUMNS} FROM bullet_category WHERE code = %s", (code,)).fetchone()
    return _row_to_dict(row) if row is not None else None
