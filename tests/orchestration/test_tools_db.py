import os
from datetime import date

import pytest

pytestmark = pytest.mark.skipif("DATABASE_URL" not in os.environ, reason="requires a running Postgres instance")


def setup_function():
    from aijudge.db.connection import get_connection
    from aijudge.db.migrate import run_migrations

    run_migrations()
    with get_connection() as conn:
        conn.execute("TRUNCATE card CASCADE")
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
        deterministic_parse_eligible=True,
    )

    result = lookup_card({"name": "Ash Blossom & Joyous Spring"})
    assert result["found"] is True
    assert result["card_text"].startswith("You can only use")
    assert result["confirmed_effects"] == []

    missing = lookup_card({"name": "Nonexistent Card"})
    assert missing == {"found": False}


def test_lookup_card_includes_confirmed_effects_when_present():
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
        deterministic_parse_eligible=True,
    )
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="quick",
        effect="negate that face-up monster's effects",
        activation_condition="During your opponent's Main Phase",
    )
    confirm_effect(effect_id)

    result = lookup_card({"name": "Effect Veiler"})
    assert len(result["confirmed_effects"]) == 1
    assert result["confirmed_effects"][0]["effect_type"] == "quick"


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
        deterministic_parse_eligible=True,
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
        deterministic_parse_eligible=True,
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


def test_lookup_card_ingests_unknown_card_on_miss_when_online_ingest_enabled():
    from aijudge.db.cards_repo import get_card_by_name
    from aijudge.llm.client import MockLLMClient
    from aijudge.orchestration.tools import lookup_card

    desc = "You can target 1 banished monster; banish it."

    def fake_fetch_card(name, http_get=None):
        return {
            "id": 47355498,
            "name": name,
            "type": "Quick-Play Spell",
            "desc": desc,
            "card_sets": [{"set_name": "Some Set"}],
        }

    def fake_fetch_rulings(name, http_get=None):
        return [{"text": "Can target monsters banished this turn.", "date": "2021-01-01"}]

    llm_client = MockLLMClient()
    llm_client.queue_response("0.97")  # review agent confidence

    result = lookup_card(
        {"name": "Called by the Grave"},
        llm_client=llm_client,
        online_ingest_enabled=True,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=fake_fetch_rulings,
        fetch_sets_index_fn=lambda: {"Some Set": date(2020, 1, 1)},
    )

    assert result["found"] is True
    assert result["name"] == "Called by the Grave"
    assert result["card_text"] == desc
    assert len(result["confirmed_effects"]) == 1
    assert get_card_by_name("Called by the Grave") is not None


def test_lookup_card_returns_not_found_when_card_not_found_error_is_raised():
    from aijudge.db.cards_repo import get_card_by_name
    from aijudge.ingestion.ygoprodeck_client import CardNotFoundError
    from aijudge.llm.client import MockLLMClient
    from aijudge.orchestration.tools import lookup_card

    def fake_fetch_card(name, http_get=None):
        raise CardNotFoundError(f"no card found for name={name!r}")

    result = lookup_card(
        {"name": "Definitely Not A Real Card"},
        llm_client=MockLLMClient(),
        online_ingest_enabled=True,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=lambda name, http_get=None: [],
    )

    assert result == {"found": False}
    assert get_card_by_name("Definitely Not A Real Card") is None


def test_lookup_card_reuses_existing_row_on_unique_violation_race():
    from datetime import date

    from aijudge.db.cards_repo import get_card_by_name, insert_card
    from aijudge.llm.client import MockLLMClient
    from aijudge.orchestration.tools import lookup_card

    def fake_fetch_card(name, http_get=None):
        # Simulate a concurrent request winning the insert race: by the time
        # our own seed_card() tries to INSERT, this row already exists.
        insert_card(
            name=name,
            card_text="a pre-existing race winner's text",
            card_type="Trap",
            deterministic_parse_eligible=True,
            source="ygoprodeck",
            fetched_at=date(2026, 8, 31),
            ygoprodeck_id="99999999",
        )
        return {"id": 12345678, "name": name, "type": "Trap Card", "desc": "irrelevant, insert fails first"}

    llm_client = MockLLMClient()  # no responses queued: insert_card raises
    # before seed_card ever reaches clause-splitting/review

    result = lookup_card(
        {"name": "Race Card"},
        llm_client=llm_client,
        online_ingest_enabled=True,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=lambda name, http_get=None: [],
    )

    assert result["found"] is True
    assert result["card_text"] == "a pre-existing race winner's text"
    assert get_card_by_name("Race Card") is not None


def test_lookup_card_online_ingest_disabled_never_calls_fetch_card_fn():
    from aijudge.orchestration.tools import lookup_card

    calls = []

    def fake_fetch_card(name, http_get=None):
        calls.append(name)
        raise AssertionError("fetch_card_fn should never be called when online_ingest_enabled is False")

    result = lookup_card({"name": "Some Card"}, fetch_card_fn=fake_fetch_card)

    assert result == {"found": False}
    assert calls == []


def test_lookup_card_calls_on_ingest_start_once_on_miss_and_not_on_hit():
    from aijudge.llm.client import MockLLMClient
    from aijudge.orchestration.tools import lookup_card

    calls = []

    def fake_fetch_card(name, http_get=None):
        return {"id": 55667788, "name": name, "type": "Trap Card", "desc": "Target 1 card; destroy it."}

    llm_client = MockLLMClient()
    llm_client.queue_response("Target 1 card; destroy it.")
    llm_client.queue_response("0.97")

    result = lookup_card(
        {"name": "Fresh Card"},
        llm_client=llm_client,
        online_ingest_enabled=True,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=lambda name, http_get=None: [],
        on_ingest_start=calls.append,
    )
    assert result["found"] is True
    assert calls == ["Fresh Card"]

    calls.clear()
    hit = lookup_card(
        {"name": "Fresh Card"},
        llm_client=llm_client,
        online_ingest_enabled=True,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=lambda name, http_get=None: [],
        on_ingest_start=calls.append,
    )
    assert hit["found"] is True
    assert calls == []


def test_lookup_card_logs_and_returns_not_found_on_unexpected_ingest_error():
    from aijudge.llm.client import MockLLMClient
    from aijudge.orchestration.tools import lookup_card

    def fake_fetch_card(name, http_get=None):
        raise RuntimeError("network exploded")

    result = lookup_card(
        {"name": "Unlucky Card"},
        llm_client=MockLLMClient(),
        online_ingest_enabled=True,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=lambda name, http_get=None: [],
    )

    assert result == {"found": False}


def test_lookup_card_returns_ambiguous_when_local_priority_chain_matches_multiple():
    from aijudge.db.cards_repo import insert_card
    from aijudge.orchestration.tools import lookup_card

    insert_card(
        name="Salamangreat Almiraj",
        card_text="text",
        card_type="Effect Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="11111111",
        archetype="Salamangreat",
        deterministic_parse_eligible=True,
    )
    insert_card(
        name="Salamangreat Balelynx",
        card_text="text",
        card_type="Effect Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="22222222",
        archetype="Salamangreat",
        deterministic_parse_eligible=True,
    )

    def fake_fetch_card(name, http_get=None):
        raise AssertionError("fetch_card_fn should never be called on a local ambiguous match")

    result = lookup_card(
        {"name": "Salamangreat"},
        online_ingest_enabled=True,
        fetch_card_fn=fake_fetch_card,
    )

    assert result == {"found": False, "ambiguous": True}


def test_lookup_card_field_skips_local_priority_chain():
    from aijudge.db.cards_repo import insert_card
    from aijudge.orchestration.tools import lookup_card

    insert_card(
        name="Salamangreat Almiraj",
        card_text="text",
        card_type="Effect Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="11111111",
        archetype="Salamangreat",
        deterministic_parse_eligible=True,
    )

    calls = []

    def fake_fetch_card(name, field=None, http_get=None):
        calls.append((name, field))
        raise RuntimeError("simulate an offline API for this test")

    result = lookup_card(
        {"name": "Salamangreat", "field": "name"},
        online_ingest_enabled=True,
        fetch_card_fn=fake_fetch_card,
    )

    assert result == {"found": False}
    assert calls == [("Salamangreat", "name")]


def test_lookup_card_reloads_by_id_after_ingest_matched_via_non_name_field():
    from aijudge.llm.client import MockLLMClient
    from aijudge.orchestration.tools import lookup_card

    desc = "You can only use each of the following effects once per turn."

    def fake_fetch_card(name, http_get=None):
        return {"id": 14558127, "name": "Ash Blossom & Joyous Spring", "type": "Effect Monster", "desc": desc}

    llm_client = MockLLMClient()
    llm_client.queue_response(desc)
    llm_client.queue_response("0.97")

    result = lookup_card(
        {"name": "14558127"},
        llm_client=llm_client,
        online_ingest_enabled=True,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=lambda name, http_get=None: [],
    )

    assert result["found"] is True
    assert result["name"] == "Ash Blossom & Joyous Spring"


def test_lookup_card_returns_ambiguous_when_ingest_fetch_raises_ambiguous_card_error():
    from aijudge.ingestion.ygoprodeck_client import AmbiguousCardError
    from aijudge.llm.client import MockLLMClient
    from aijudge.orchestration.tools import lookup_card

    def fake_fetch_card(name, http_get=None):
        raise AmbiguousCardError("multiple cards matched")

    result = lookup_card(
        {"name": "Salamangreat"},
        llm_client=MockLLMClient(),
        online_ingest_enabled=True,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=lambda name, http_get=None: [],
    )

    assert result == {"found": False, "ambiguous": True}


def test_lookup_card_default_fetch_sets_index_fn_is_cached_across_calls():
    """fetch_sets_index is a large, slowly-changing catalog -- meant to be
    fetched once and reused, not once per lookup_card call. Unlike
    ingestion.seed.run_seed, each lookup_card online-ingest call is its own
    independent invocation with no natural batch boundary, so tools.py's
    default fetch_sets_index_fn is a small lru_cache(maxsize=1) wrapper
    around the real fetch. Confirm it only calls the underlying fetch once
    across two separate online-ingest lookups in this test."""
    import aijudge.orchestration.tools as tools_module
    from aijudge.llm.client import MockLLMClient

    tools_module._cached_fetch_sets_index.cache_clear()

    fetch_calls = []

    def fake_fetch_sets_index():
        fetch_calls.append(1)
        return {"Some Set": date(2020, 1, 1)}

    original_fetch_sets_index = tools_module.fetch_sets_index
    tools_module.fetch_sets_index = fake_fetch_sets_index
    try:
        def make_fake_fetch_card(card_id):
            def fake_fetch_card(name, http_get=None):
                return {
                    "id": card_id,
                    "name": name,
                    "type": "Quick-Play Spell",
                    "desc": "You can target 1 banished monster; banish it.",
                    "card_sets": [{"set_name": "Some Set"}],
                }

            return fake_fetch_card

        llm_client = MockLLMClient()
        llm_client.queue_response("0.97")  # review confidence, first card
        llm_client.queue_response("0.97")  # review confidence, second card

        first = tools_module.lookup_card(
            {"name": "Called by the Grave"},
            llm_client=llm_client,
            online_ingest_enabled=True,
            fetch_card_fn=make_fake_fetch_card(47355498),
            fetch_rulings_fn=lambda name, http_get=None: [],
        )
        second = tools_module.lookup_card(
            {"name": "Infinite Impermanence"},
            llm_client=llm_client,
            online_ingest_enabled=True,
            fetch_card_fn=make_fake_fetch_card(10045474),
            fetch_rulings_fn=lambda name, http_get=None: [],
        )
    finally:
        tools_module.fetch_sets_index = original_fetch_sets_index
        tools_module._cached_fetch_sets_index.cache_clear()

    assert first["found"] is True
    assert second["found"] is True
    assert len(fetch_calls) == 1
