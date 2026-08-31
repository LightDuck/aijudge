from datetime import date

from .connection import get_connection

_CARD_COLUMNS = [
    "id", "name", "card_text", "card_type", "attribute", "monster_type",
    "level", "rank", "link_rating", "archetype", "atk", "def", "has_errata",
    "ygoprodeck_id", "ygoresources_id",
]


def insert_card(
    *,
    name: str,
    card_text: str,
    card_type: str,
    source: str,
    fetched_at: date,
    ygoprodeck_id: str,
    attribute: str | None = None,
    monster_type: str | None = None,
    level: int | None = None,
    rank: int | None = None,
    link_rating: int | None = None,
    archetype: str | None = None,
    atk: int | None = None,
    def_: int | None = None,
    ygoresources_id: str | None = None,
    card_materials: str | None = None,
) -> str:
    with get_connection() as conn:
        row = conn.execute(
            """
            INSERT INTO cards (
                name, card_text, card_type, attribute, monster_type,
                level, rank, link_rating, archetype, atk, def,
                ygoprodeck_id, ygoresources_id, source, fetched_at, card_materials
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                name, card_text, card_type, attribute, monster_type,
                level, rank, link_rating, archetype, atk, def_,
                ygoprodeck_id, ygoresources_id, source, fetched_at, card_materials,
            ),
        ).fetchone()
        conn.commit()
        return str(row[0])


def get_card_by_name(name: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, name, card_text, card_type, attribute, monster_type, "
            "level, rank, link_rating, archetype, atk, def, has_errata, "
            "ygoprodeck_id, ygoresources_id "
            "FROM cards WHERE name = %s",
            (name,),
        ).fetchone()
    if row is None:
        return None
    row_list = list(row)
    row_list[0] = str(row_list[0])
    return dict(zip(_CARD_COLUMNS, row_list))


def get_card_by_ygoprodeck_id(ygoprodeck_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, name, card_text, card_type, attribute, monster_type, "
            "level, rank, link_rating, archetype, atk, def, has_errata, "
            "ygoprodeck_id, ygoresources_id "
            "FROM cards WHERE ygoprodeck_id = %s",
            (ygoprodeck_id,),
        ).fetchone()
    if row is None:
        return None
    row_list = list(row)
    row_list[0] = str(row_list[0])
    return dict(zip(_CARD_COLUMNS, row_list))


def get_card_by_ygoresources_id(ygoresources_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, name, card_text, card_type, attribute, monster_type, "
            "level, rank, link_rating, archetype, atk, def, has_errata, "
            "ygoprodeck_id, ygoresources_id "
            "FROM cards WHERE ygoresources_id = %s",
            (ygoresources_id,),
        ).fetchone()
    if row is None:
        return None
    row_list = list(row)
    row_list[0] = str(row_list[0])
    return dict(zip(_CARD_COLUMNS, row_list))


def insert_errata_version(*, card_id: str, errata_date: date, errata_text: str) -> str:
    with get_connection() as conn:
        row = conn.execute(
            """
            INSERT INTO card_errata_versions (card_id, errata_date, errata_text)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (card_id, errata_date, errata_text),
        ).fetchone()
        conn.execute("UPDATE cards SET has_errata = TRUE WHERE id = %s", (card_id,))
        conn.commit()
        return str(row[0])


def list_card_names() -> list[str]:
    with get_connection() as conn:
        rows = conn.execute("SELECT name FROM cards").fetchall()
    return [row[0] for row in rows]
