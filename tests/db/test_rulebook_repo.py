import os

import pytest

pytestmark = pytest.mark.skipif("DATABASE_URL" not in os.environ, reason="requires a running Postgres instance")


def setup_function():
    from aijudge.db.connection import get_connection
    from aijudge.db.migrate import run_migrations

    run_migrations()
    with get_connection() as conn:
        conn.execute("TRUNCATE rulebook_chunks")
        conn.commit()


def test_insert_and_list_chunks():
    from aijudge.db.rulebook_repo import insert_chunk, list_chunks
    from aijudge.embeddings.client import MockEmbeddingClient

    embedding = MockEmbeddingClient().embed("Priority is the ability of a player to activate...")
    insert_chunk(
        chunk_text="Priority is the ability of a player to activate...",
        source="konami_rulebook",
        embedding=embedding,
        section_reference="3.2",
    )

    chunks = list_chunks(source="konami_rulebook")

    assert len(chunks) == 1
    assert chunks[0]["section_reference"] == "3.2"


def test_list_chunks_filters_by_source():
    from aijudge.db.rulebook_repo import insert_chunk, list_chunks
    from aijudge.embeddings.client import MockEmbeddingClient

    embedding = MockEmbeddingClient().embed("some PSCT guidance")
    insert_chunk(chunk_text="some PSCT guidance", source="psct_guide", embedding=embedding)

    assert list_chunks(source="konami_rulebook") == []
    assert len(list_chunks(source="psct_guide")) == 1
