from .connection import get_connection


def _row_to_dict(r) -> dict:
    return {"code": r[0], "name": r[1], "description": r[2], "note": r[3]}


def get_all_bullet_categories() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT code, name, description, note FROM bullet_categories ORDER BY code").fetchall()
    return [_row_to_dict(r) for r in rows]


def get_bullet_category(code: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT code, name, description, note FROM bullet_categories WHERE code = %s", (code,)
        ).fetchone()
    return _row_to_dict(row) if row is not None else None
