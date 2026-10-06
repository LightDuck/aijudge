import os
from datetime import date

import pytest
import requests

pytestmark = pytest.mark.skipif("TEST_DATABASE_URL" not in os.environ, reason="requires TEST_DATABASE_URL (a dedicated test Postgres database)")


def setup_function():
    from aijudge.db.connection import get_connection
    from aijudge.db.migrate import run_migrations

    run_migrations()
    with get_connection() as conn:
        conn.execute("TRUNCATE card CASCADE")
        conn.commit()


def _insert_legacy_card(name, passcode, card_type, race, card_text):
    """A card as ingested before this change: no Konami id, NULL status."""
    from aijudge.db.cards_repo import insert_card

    return insert_card(
        name=name,
        card_text=card_text,
        card_type=card_type,
        race=race,
        source="ygoprodeck",
        fetched_at=date(2026, 9, 1),
        ygoprodeck_id=passcode,
        deterministic_parse_eligible=True,
    )


def _index():
    from aijudge.ingestion.ygoresources_client import invert_name_index
    from tests.rulings_fixtures import NAME_INDEX_SLICE

    return invert_name_index(NAME_INDEX_SLICE)


def _fake_fetch_card(konami_ids):
    def fetch(query, *, field=None):
        assert field == "id"
        return {"misc_info": [{"konami_id": konami_ids[query]}]}

    return fetch


def test_backfill_refetches_a_legacy_card_with_zero_rulings_and_resolves_them():
    from aijudge.db.cards_repo import get_card_by_id
    from aijudge.db.rulings_repo import get_rulings_for_card
    from aijudge.ingestion.rulings_backfill import backfill_rulings
    from tests.rulings_fixtures import DIGITRON_RULING_2019

    card_id = _insert_legacy_card(
        "Digitron", "32295838", "Normal Monster", "Cyberse", "A Cyberse born from the depths of cyberspace."
    )

    report = backfill_rulings(
        fetch_card_fn=_fake_fetch_card({"32295838": 13192}),
        fetch_rulings_fn=lambda konami_id: [{"text": DIGITRON_RULING_2019, "date": "2019-03-23"}],
        fetch_card_name_index_fn=_index,
    )

    card = get_card_by_id(card_id)
    assert card["ygoresources_id"] == "13192"
    assert card["rulings_status"] == "fetched"
    [ruling] = get_rulings_for_card(card_id)
    assert ruling["ruling_text_resolved"].startswith("Q: I Link Summon a Security Dragon, using a Link Spider and Digitron")
    assert (report.konami_ids_stored, report.rulings_refetched, report.rulings_resolved) == (1, 1, 1)
    assert report.failures == []


def test_backfill_marks_a_card_with_existing_rulings_fetched_without_duplicating_them():
    from aijudge.db.cards_repo import get_card_by_id
    from aijudge.db.rulings_repo import get_rulings_for_card, insert_ruling
    from aijudge.ingestion.rulings_backfill import backfill_rulings
    from tests.rulings_fixtures import AMAZONESS_CALL_RULING_2017

    card_id = _insert_legacy_card(
        "Amazoness Call", "57312333", "Spell Card", "Quick-Play",
        'Take 1 "Amazoness" card from your Deck, except "Amazoness Call", and either add it to your hand or send it to the GY.',
    )
    insert_ruling(card_id=card_id, ruling_text=AMAZONESS_CALL_RULING_2017, source="db.ygoresources")

    def must_not_refetch(konami_id):
        raise AssertionError("existing rulings prove the original fetch worked")

    backfill_rulings(
        fetch_card_fn=_fake_fetch_card({"57312333": 13174}),
        fetch_rulings_fn=must_not_refetch,
        fetch_card_name_index_fn=_index,
    )

    assert get_card_by_id(card_id)["rulings_status"] == "fetched"
    [ruling] = get_rulings_for_card(card_id)
    assert ruling["ruling_text_resolved"].startswith("Q: I activate the second effect of Amazoness Call")


def test_backfill_records_a_failed_refetch_and_reports_it():
    from aijudge.db.cards_repo import get_card_by_id
    from aijudge.ingestion.rulings_backfill import backfill_rulings

    card_id = _insert_legacy_card(
        "Digitron", "32295838", "Normal Monster", "Cyberse", "A Cyberse born from the depths of cyberspace."
    )

    def failing_fetch(konami_id):
        raise requests.ConnectionError("ygoresources unreachable")

    report = backfill_rulings(
        fetch_card_fn=_fake_fetch_card({"32295838": 13192}),
        fetch_rulings_fn=failing_fetch,
        fetch_card_name_index_fn=_index,
    )

    assert get_card_by_id(card_id)["rulings_status"] == "failed"
    assert report.failures == ["Digitron"]


def test_backfill_is_a_no_op_on_a_second_run():
    from aijudge.db.rulings_repo import get_rulings_for_card
    from aijudge.ingestion.rulings_backfill import backfill_rulings
    from tests.rulings_fixtures import DIGITRON_RULING_2019

    card_id = _insert_legacy_card(
        "Digitron", "32295838", "Normal Monster", "Cyberse", "A Cyberse born from the depths of cyberspace."
    )
    kwargs = dict(
        fetch_card_fn=_fake_fetch_card({"32295838": 13192}),
        fetch_rulings_fn=lambda konami_id: [{"text": DIGITRON_RULING_2019, "date": "2019-03-23"}],
        fetch_card_name_index_fn=_index,
    )
    backfill_rulings(**kwargs)

    second = backfill_rulings(**kwargs)

    assert (second.konami_ids_stored, second.rulings_refetched, second.rulings_resolved) == (0, 0, 0)
    assert len(get_rulings_for_card(card_id)) == 1


def _insert_legacy_amazoness_call():
    return _insert_legacy_card(
        "Amazoness Call", "57312333", "Spell Card", "Quick-Play",
        'Take 1 "Amazoness" card from your Deck, except "Amazoness Call", and either add it to your hand or send it to the GY.',
    )


def _insert_legacy_digitron():
    return _insert_legacy_card(
        "Digitron", "32295838", "Normal Monster", "Cyberse", "A Cyberse born from the depths of cyberspace."
    )


def test_backfill_refetches_a_failed_card_that_already_has_its_konami_id():
    from aijudge.db.cards_repo import get_card_by_id, insert_card
    from aijudge.db.rulings_repo import get_rulings_for_card
    from aijudge.ingestion.rulings_backfill import backfill_rulings
    from tests.rulings_fixtures import DIGITRON_RULING_2019

    card_id = insert_card(
        name="Digitron",
        card_text="A Cyberse born from the depths of cyberspace.",
        card_type="Normal Monster",
        race="Cyberse",
        source="ygoprodeck",
        fetched_at=date(2026, 10, 5),
        ygoprodeck_id="32295838",
        deterministic_parse_eligible=True,
        ygoresources_id="13192",
        rulings_status="failed",
    )
    ygoprodeck_calls = []
    fetched_konami_ids = []

    def fetch_rulings(konami_id):
        fetched_konami_ids.append(konami_id)
        return [{"text": DIGITRON_RULING_2019, "date": "2019-03-23"}]

    report = backfill_rulings(
        fetch_card_fn=lambda *args, **kwargs: ygoprodeck_calls.append(args),
        fetch_rulings_fn=fetch_rulings,
        fetch_card_name_index_fn=_index,
    )

    assert ygoprodeck_calls == []
    assert fetched_konami_ids == [13192]
    assert get_card_by_id(card_id)["rulings_status"] == "fetched"
    assert len(get_rulings_for_card(card_id)) == 1
    assert report.failures == []


def test_backfill_marks_a_card_without_a_konami_id_and_skips_it_next_run():
    from aijudge.db.cards_repo import get_card_by_id
    from aijudge.ingestion.rulings_backfill import backfill_rulings

    card_id = _insert_legacy_digitron()
    ygoprodeck_calls = []

    def fetch_card_without_konami_id(query, *, field=None):
        ygoprodeck_calls.append(query)
        return {"misc_info": [{}]}

    def must_not_fetch_rulings(konami_id):
        raise AssertionError("no konami_id, nothing to fetch")

    kwargs = dict(
        fetch_card_fn=fetch_card_without_konami_id,
        fetch_rulings_fn=must_not_fetch_rulings,
        fetch_card_name_index_fn=_index,
    )
    first = backfill_rulings(**kwargs)
    assert get_card_by_id(card_id)["rulings_status"] == "no_konami_id"

    second = backfill_rulings(**kwargs)

    assert ygoprodeck_calls == ["32295838"]
    assert first.failures == [] and second.failures == []
    assert get_card_by_id(card_id)["rulings_status"] == "no_konami_id"


def test_backfill_reports_a_failed_ygoprodeck_lookup_and_processes_the_other_cards():
    from aijudge.db.cards_repo import get_card_by_id
    from aijudge.db.rulings_repo import get_rulings_for_card
    from aijudge.ingestion.rulings_backfill import backfill_rulings
    from tests.rulings_fixtures import DIGITRON_RULING_2019

    call_id = _insert_legacy_amazoness_call()
    digitron_id = _insert_legacy_digitron()

    def fetch_card(query, *, field=None):
        if query == "57312333":
            raise requests.ConnectionError("YGOPRODeck unreachable")
        return {"misc_info": [{"konami_id": 13192}]}

    report = backfill_rulings(
        fetch_card_fn=fetch_card,
        fetch_rulings_fn=lambda konami_id: [{"text": DIGITRON_RULING_2019, "date": "2019-03-23"}],
        fetch_card_name_index_fn=_index,
    )

    assert report.failures == ["Amazoness Call"]
    call = get_card_by_id(call_id)
    assert (call["rulings_status"], call["ygoresources_id"]) == (None, None)
    assert get_card_by_id(digitron_id)["rulings_status"] == "fetched"
    assert len(get_rulings_for_card(digitron_id)) == 1


def test_backfill_fills_referenced_ids_but_leaves_rulings_unresolved_when_the_name_index_is_unavailable():
    from aijudge.db.rulings_repo import get_rulings_for_card, insert_ruling
    from aijudge.ingestion.rulings_backfill import backfill_rulings
    from tests.rulings_fixtures import AMAZONESS_CALL_RULING_2017

    card_id = _insert_legacy_amazoness_call()
    insert_ruling(card_id=card_id, ruling_text=AMAZONESS_CALL_RULING_2017, source="db.ygoresources")

    def failing_index():
        raise requests.ConnectionError("ygoresources unreachable")

    report = backfill_rulings(
        fetch_card_fn=_fake_fetch_card({"57312333": 13174}),
        fetch_rulings_fn=lambda konami_id: [],
        fetch_card_name_index_fn=failing_index,
    )

    [ruling] = get_rulings_for_card(card_id)
    assert ruling["referenced_konami_ids"] == [13174, 8963, 5505, 5682]
    assert ruling["ruling_text_resolved"] is None  # a later run with the index still resolves it
    assert report.failures == ["card name index"]
    assert report.rulings_resolved == 0


def test_backfill_continues_past_a_card_whose_rulings_cannot_be_stored(monkeypatch):
    from aijudge.db import rulings_repo
    from aijudge.db.cards_repo import get_card_by_id
    from aijudge.db.rulings_repo import get_rulings_for_card
    from aijudge.ingestion import rulings_backfill
    from tests.rulings_fixtures import AMAZONESS_CALL_RULING_2017, DIGITRON_RULING_2019

    call_id = _insert_legacy_amazoness_call()
    digitron_id = _insert_legacy_digitron()

    def insert_failing_for_amazoness_call(card_id, rulings):
        if card_id == call_id:
            # The real insert, with a row the DB rejects.
            rulings = [{**rulings[0], "referenced_konami_ids": ["not-an-int"]}]
        return rulings_repo.insert_rulings(card_id, rulings)

    monkeypatch.setattr(rulings_backfill, "insert_rulings", insert_failing_for_amazoness_call)
    rulings_by_konami_id = {
        13174: [{"text": AMAZONESS_CALL_RULING_2017, "date": "2017-07-22"}],
        13192: [{"text": DIGITRON_RULING_2019, "date": "2019-03-23"}],
    }

    report = rulings_backfill.backfill_rulings(
        fetch_card_fn=_fake_fetch_card({"57312333": 13174, "32295838": 13192}),
        fetch_rulings_fn=rulings_by_konami_id.__getitem__,
        fetch_card_name_index_fn=_index,
    )

    assert report.failures == ["Amazoness Call"]
    assert get_card_by_id(call_id)["rulings_status"] is None  # never marked fetched
    assert get_rulings_for_card(call_id) == []
    assert get_card_by_id(digitron_id)["rulings_status"] == "fetched"
    assert len(get_rulings_for_card(digitron_id)) == 1
