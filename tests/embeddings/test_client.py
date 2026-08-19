from aijudge.embeddings.client import EMBEDDING_DIM, MockEmbeddingClient


def test_embed_returns_a_vector_of_the_expected_dimension():
    client = MockEmbeddingClient()
    vector = client.embed("some rulebook text")
    assert len(vector) == EMBEDDING_DIM


def test_embed_is_deterministic():
    client = MockEmbeddingClient()
    assert client.embed("same text") == client.embed("same text")


def test_embed_differs_for_different_text():
    client = MockEmbeddingClient()
    assert client.embed("text one") != client.embed("text two")
