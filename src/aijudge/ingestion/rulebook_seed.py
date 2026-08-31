from pathlib import Path

from aijudge.db.rulebook_repo import insert_chunk
from aijudge.embeddings.client import EmbeddingClient
from aijudge.ingestion.rulebook_loader import load_rulebook_file


def seed_rulebook_file(path: Path, *, embedding_client: EmbeddingClient, source: str) -> list[str]:
    chunks = load_rulebook_file(path)
    return [
        insert_chunk(chunk_text=chunk, source=source, embedding=embedding_client.embed(chunk))
        for chunk in chunks
    ]
