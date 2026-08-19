import os
from datetime import date

import pytest

pytestmark = pytest.mark.skipif("DATABASE_URL" not in os.environ, reason="requires a running Postgres instance")


def setup_function():
    from aijudge.db.connection import get_connection
    from aijudge.db.migrate import run_migrations

    run_migrations()
    with get_connection() as conn:
        conn.execute("TRUNCATE cards CASCADE")
        conn.execute("TRUNCATE rulebook_chunks")
        conn.commit()


def test_lookup_card_returns_card_text_and_not_found_flag():
    from aijudge.db.cards_repo import insert_card
    from aijudge.orchestration.tools import lookup_card

    insert_card(
        name="Ash Blossom & Joyous Spring",
        card_text="You can only use each of the following effects...",
        card_type="Effect Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="14558127",
    )

    result = lookup_card({"name": "Ash Blossom & Joyous Spring"})
    assert result["found"] is True
    assert result["card_text"].startswith("You can only use")
    assert result["confirmed_effect"] is None

    missing = lookup_card({"name": "Nonexistent Card"})
    assert missing == {"found": False}


def test_lookup_card_includes_confirmed_effect_when_present():
    from aijudge.db.cards_repo import insert_card
    from aijudge.db.effects_repo import confirm_effect, insert_pending_effect
    from aijudge.orchestration.tools import lookup_card

    card_id = insert_card(
        name="Effect Veiler",
        card_text="During your opponent's Main Phase (Quick Effect): ...",
        card_type="Effect Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="95440946",
    )
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="quick",
        effect="negate that face-up monster's effects",
        activation_condition="During your opponent's Main Phase",
    )
    confirm_effect(effect_id)

    result = lookup_card({"name": "Effect Veiler"})
    assert result["confirmed_effect"]["effect_type"] == "quick"


def test_get_rulings_returns_empty_list_when_none_exist():
    from aijudge.db.cards_repo import insert_card
    from aijudge.orchestration.tools import get_rulings

    card_id = insert_card(
        name="Called by the Grave",
        card_text="During either player's turn...",
        card_type="Quick-Play Spell",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="47355498",
    )

    assert get_rulings({"card_id": card_id}) == {"rulings": []}


def test_get_rulings_serializes_ruling_date_to_isoformat():
    from aijudge.db.cards_repo import insert_card
    from aijudge.db.rulings_repo import insert_ruling
    from aijudge.orchestration.tools import get_rulings

    card_id = insert_card(
        name="Infinite Impermanence",
        card_text="Target 1 face-up monster your opponent controls...",
        card_type="Trap",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="10045474",
    )
    insert_ruling(
        card_id=card_id,
        ruling_text="This effect can target itself.",
        source="db.ygoresources",
        ruling_date=date(2020, 1, 1),
    )

    result = get_rulings({"card_id": card_id})
    assert result["rulings"][0]["ruling_date"] == "2020-01-01"
    assert result["rulings"][0]["ruling_text"] == "This effect can target itself."


def test_search_rulebook_wrapper_respects_default_max_distance():
    from aijudge.db.rulebook_repo import insert_chunk
    from aijudge.embeddings.client import MockEmbeddingClient
    from aijudge.orchestration.tools import _search_rulebook

    client = MockEmbeddingClient()
    text = "Priority is the ability to activate a card or effect in response to something."
    insert_chunk(chunk_text=text, source="konami_rulebook", embedding=client.embed(text))

    result = _search_rulebook({"query": text}, embedding_client=client)
    assert len(result["chunks"]) == 1
    assert result["chunks"][0]["chunk_text"] == text

    empty = _search_rulebook({"query": "something totally unrelated to yugioh at all"}, embedding_client=client)
    assert empty["chunks"] == []
