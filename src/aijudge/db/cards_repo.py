from datetime import date

from .connection import get_connection

_CARD_COLUMNS = [
    "id", "name", "card_text", "card_type", "race", "attribute", "monster_type",
    "level", "rank", "link_rating", "archetype", "atk", "def", "has_errata",
    "ygoprodeck_id", "ygoresources_id", "deterministic_parse_eligible",
]


def insert_card(
    *,
    name: str,
    card_text: str,
    card_type: str,
    source: str,
    fetched_at: date,
    ygoprodeck_id: str,
    deterministic_parse_eligible: bool,
    race: str | None = None,
    attribute: str | None = None,
    monster_type: str | None = None,
    level: int | None = None,
    rank: int | None = None,
    link_rating: int | None = None,
    archetype: str | None = None,
    atk: int | None = None,
    def_: int | None = None,
    ygoresources_id: str | None = None,
) -> str:
    with get_connection() as conn:
        row = conn.execute(
            """
            INSERT INTO cards (
                name, card_text, card_type, race, attribute, monster_type,
                level, rank, link_rating, archetype, atk, def,
                ygoprodeck_id, ygoresources_id, source, fetched_at, deterministic_parse_eligible
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                name, card_text, card_type, race, attribute, monster_type,
                level, rank, link_rating, archetype, atk, def_,
                ygoprodeck_id, ygoresources_id, source, fetched_at, deterministic_parse_eligible,
            ),
        ).fetchone()
        conn.commit()
        return str(row[0])


def get_card_by_name(name: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, name, card_text, card_type, race, attribute, monster_type, "
            "level, rank, link_rating, archetype, atk, def, has_errata, "
            "ygoprodeck_id, ygoresources_id, deterministic_parse_eligible "
            "FROM cards WHERE name = %s",
            (name,),
        ).fetchone()
    if row is None:
        return None
    row_list = list(row)
    row_list[0] = str(row_list[0])
    return dict(zip(_CARD_COLUMNS, row_list))


def get_card_by_id(card_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, name, card_text, card_type, race, attribute, monster_type, "
            "level, rank, link_rating, archetype, atk, def, has_errata, "
            "ygoprodeck_id, ygoresources_id, deterministic_parse_eligible "
            "FROM cards WHERE id = %s",
            (card_id,),
        ).fetchone()
    if row is None:
        return None
    row_list = list(row)
    row_list[0] = str(row_list[0])
    return dict(zip(_CARD_COLUMNS, row_list))


def get_cards_by_fname(fname: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, card_text, card_type, race, attribute, monster_type, "
            "level, rank, link_rating, archetype, atk, def, has_errata, "
            "ygoprodeck_id, ygoresources_id, deterministic_parse_eligible "
            "FROM cards WHERE name ILIKE %s",
            (f"%{fname}%",),
        ).fetchall()
    return [dict(zip(_CARD_COLUMNS, [str(row[0])] + list(row[1:]))) for row in rows]


def get_cards_by_archetype(archetype: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, card_text, card_type, race, attribute, monster_type, "
            "level, rank, link_rating, archetype, atk, def, has_errata, "
            "ygoprodeck_id, ygoresources_id, deterministic_parse_eligible "
            "FROM cards WHERE archetype = %s",
            (archetype,),
        ).fetchall()
    return [dict(zip(_CARD_COLUMNS, [str(row[0])] + list(row[1:]))) for row in rows]


def get_card_by_ygoprodeck_id(ygoprodeck_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, name, card_text, card_type, race, attribute, monster_type, "
            "level, rank, link_rating, archetype, atk, def, has_errata, "
            "ygoprodeck_id, ygoresources_id, deterministic_parse_eligible "
            "FROM cards WHERE ygoprodeck_id = %s",
            (ygoprodeck_id,),
        ).fetchone()
    if row is None:
        return None
    row_list = list(row)
    row_list[0] = str(row_list[0])
    return dict(zip(_CARD_COLUMNS, row_list))


def find_card_by_priority(query: str, *, field: str | None = None) -> tuple[str, list[dict]]:
    def by_name() -> list[dict]:
        card = get_card_by_name(query)
        return [card] if card is not None else []

    def by_id() -> list[dict]:
        card = get_card_by_ygoprodeck_id(query)
        return [card] if card is not None else []

    steps = {
        "name": by_name,
        "fname": lambda: get_cards_by_fname(query),
        "archetype": lambda: get_cards_by_archetype(query),
        "id": by_id,
    }
    fields = [field] if field is not None else ["name", "fname", "archetype", "id"]

    for candidate_field in fields:
        matches = steps[candidate_field]()
        if len(matches) == 1:
            return "single", matches
        if len(matches) > 1:
            return "ambiguous", []
    return "none", []


def get_card_by_ygoresources_id(ygoresources_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, name, card_text, card_type, race, attribute, monster_type, "
            "level, rank, link_rating, archetype, atk, def, has_errata, "
            "ygoprodeck_id, ygoresources_id, deterministic_parse_eligible "
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
