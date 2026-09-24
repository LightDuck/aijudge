import os

import pytest

pytestmark = pytest.mark.skipif("TEST_DATABASE_URL" not in os.environ, reason="requires TEST_DATABASE_URL (a dedicated test Postgres database)")


def setup_function():
    from aijudge.db.connection import get_connection
    from aijudge.db.migrate import run_migrations

    run_migrations()
    with get_connection() as conn:
        conn.execute("TRUNCATE rulebook_chunks")
        conn.commit()


def test_seed_rulebook_file_chunks_and_stores_every_paragraph(tmp_path):
    from aijudge.db.rulebook_repo import list_chunks
    from aijudge.embeddings.client import MockEmbeddingClient
    from aijudge.ingestion.rulebook_seed import seed_rulebook_file

    rulebook_path = tmp_path / "rulebook.txt"
    rulebook_path.write_text(
        "Priority is the ability of a player to activate a card or effect.\n\n"
        "During the Damage Step, only specific effects may be activated.",
        encoding="utf-8",
    )

    ids = seed_rulebook_file(rulebook_path, embedding_client=MockEmbeddingClient(), source="konami_rulebook")

    assert len(ids) == 1  # both short paragraphs fit under the 800-char default chunk size
    chunks = list_chunks(source="konami_rulebook")
    assert len(chunks) == 1
    assert "Damage Step" in chunks[0]["chunk_text"]


def test_seed_rulebook_file_is_idempotent_when_run_twice(tmp_path):
    from aijudge.db.rulebook_repo import list_chunks
    from aijudge.embeddings.client import MockEmbeddingClient
    from aijudge.ingestion.rulebook_seed import seed_rulebook_file

    rulebook_path = tmp_path / "rulebook.txt"
    rulebook_path.write_text(
        "Priority is the ability of a player to activate a card or effect.\n\n"
        "During the Damage Step, only specific effects may be activated.",
        encoding="utf-8",
    )

    seed_rulebook_file(rulebook_path, embedding_client=MockEmbeddingClient(), source="konami_rulebook")
    seed_rulebook_file(rulebook_path, embedding_client=MockEmbeddingClient(), source="konami_rulebook")

    chunks = list_chunks(source="konami_rulebook")
    assert len(chunks) == 1


def test_seed_rulebook_file_splits_long_content_into_multiple_chunks(tmp_path):
    from aijudge.db.rulebook_repo import list_chunks
    from aijudge.embeddings.client import MockEmbeddingClient
    from aijudge.ingestion.rulebook_seed import seed_rulebook_file

    rulebook_path = tmp_path / "rulebook.txt"
    rulebook_path.write_text("A" * 500 + "\n\n" + "B" * 500, encoding="utf-8")

    ids = seed_rulebook_file(rulebook_path, embedding_client=MockEmbeddingClient(), source="konami_rulebook")

    assert len(ids) == 2
    assert len(list_chunks(source="konami_rulebook")) == 2
