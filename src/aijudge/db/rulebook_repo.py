from .connection import get_connection


def insert_chunk(
    *, chunk_text: str, source: str, embedding: list[float], section_reference: str | None = None
) -> str:
    with get_connection() as conn:
        row = conn.execute(
            """
            INSERT INTO rulebook_chunks (chunk_text, source, section_reference, embedding)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (chunk_text, source, section_reference, embedding),
        ).fetchone()
        conn.commit()
        return str(row[0])


def list_chunks(source: str | None = None) -> list[dict]:
    query = "SELECT id, chunk_text, source, section_reference FROM rulebook_chunks"
    params: tuple = ()
    if source is not None:
        query += " WHERE source = %s"
        params = (source,)
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [
        {"id": str(r[0]), "chunk_text": r[1], "source": r[2], "section_reference": r[3]}
        for r in rows
    ]


def search_chunks(query_embedding: list[float], *, max_distance: float, limit: int = 5) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, chunk_text, source, section_reference
            FROM rulebook_chunks
            WHERE embedding <=> %s::vector < %s
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (query_embedding, max_distance, query_embedding, limit),
        ).fetchall()
    return [
        {"id": str(r[0]), "chunk_text": r[1], "source": r[2], "section_reference": r[3]}
        for r in rows
    ]
