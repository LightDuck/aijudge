import os
from datetime import date

import pytest

pytestmark = pytest.mark.skipif("TEST_DATABASE_URL" not in os.environ, reason="requires TEST_DATABASE_URL (a dedicated test Postgres database)")


def setup_function():
    from aijudge.db.connection import get_connection
    from aijudge.db.migrate import run_migrations

    run_migrations()
    with get_connection() as conn:
        conn.execute("TRUNCATE card CASCADE")
        conn.commit()


def test_insert_and_get_rulings_for_card():
    from aijudge.db.cards_repo import insert_card
    from aijudge.db.rulings_repo import get_rulings_for_card, insert_ruling

    card_id = insert_card(
        name="Ash Blossom & Joyous Spring",
        card_text="You can only use each of the following effects of \"Ash Blossom & Joyous Spring\" once per turn.",
        card_type="Effect Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="14558127",
        deterministic_parse_eligible=True,
    )

    insert_ruling(
        card_id=card_id,
        ruling_text="Ash Blossom's effect cannot be activated in response to itself.",
        source="db.ygoresources",
        ruling_date=date(2021, 1, 1),
    )

    rulings = get_rulings_for_card(card_id)

    assert len(rulings) == 1
    assert rulings[0]["source"] == "db.ygoresources"


def test_get_rulings_for_card_returns_empty_list_when_none_exist():
    from aijudge.db.cards_repo import insert_card
    from aijudge.db.rulings_repo import get_rulings_for_card

    card_id = insert_card(
        name="No Rulings Card",
        card_text="Text.",
        card_type="Normal Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="99999999",
        deterministic_parse_eligible=True,
    )

    assert get_rulings_for_card(card_id) == []


def _insert_amazoness_call():
    from aijudge.db.cards_repo import insert_card

    return insert_card(
        name="Amazoness Call",
        card_text=(
            'Take 1 "Amazoness" card from your Deck, except "Amazoness Call", and either add it to your hand or '
            'send it to the GY. During your Main Phase: You can banish this card from your GY, then target 1 '
            '"Amazoness" monster you control; this turn, that monster can attack all monsters your opponent '
            'controls, once each, also other monsters you control cannot attack. You can only activate 1 '
            '"Amazoness Call" per turn.'
        ),
        card_type="Spell Card",
        race="Quick-Play",
        source="ygoprodeck",
        fetched_at=date(2026, 10, 5),
        ygoprodeck_id="57312333",
        deterministic_parse_eligible=True,
    )


def test_insert_ruling_stores_resolved_text_and_referenced_ids():
    from aijudge.db.rulings_repo import get_rulings_for_card, insert_ruling
    from tests.rulings_fixtures import AMAZONESS_CALL_RULING_2017

    card_id = _insert_amazoness_call()
    insert_ruling(
        card_id=card_id,
        ruling_text=AMAZONESS_CALL_RULING_2017,
        source="db.ygoresources",
        ruling_date=date(2017, 7, 22),
        ruling_text_resolved="Q: I activate the second effect of Amazoness Call ...",
        referenced_konami_ids=[13174, 8963, 5505, 5682],
    )

    [ruling] = get_rulings_for_card(card_id)
    assert ruling["ruling_text"] == AMAZONESS_CALL_RULING_2017
    assert ruling["ruling_text_resolved"] == "Q: I activate the second effect of Amazoness Call ..."
    assert ruling["referenced_konami_ids"] == [13174, 8963, 5505, 5682]


def test_insert_ruling_defaults_to_unresolved_with_no_ids():
    from aijudge.db.rulings_repo import get_rulings_for_card, insert_ruling
    from tests.rulings_fixtures import AMAZONESS_CALL_RULING_2017

    card_id = _insert_amazoness_call()
    insert_ruling(card_id=card_id, ruling_text=AMAZONESS_CALL_RULING_2017, source="db.ygoresources")

    [ruling] = get_rulings_for_card(card_id)
    assert ruling["ruling_text_resolved"] is None
    assert ruling["referenced_konami_ids"] == []


def _ruling_row(ruling_text, ruling_date, referenced_konami_ids):
    return {
        "ruling_text": ruling_text,
        "source": "db.ygoresources",
        "ruling_date": ruling_date,
        "ruling_text_resolved": None,
        "referenced_konami_ids": referenced_konami_ids,
    }


def test_insert_rulings_stores_every_row_and_returns_their_ids():
    from aijudge.db.rulings_repo import get_rulings_for_card, insert_rulings
    from tests.rulings_fixtures import AMAZONESS_CALL_RULING_2017, AMAZONESS_CALL_RULING_2026

    card_id = _insert_amazoness_call()
    ids = insert_rulings(card_id, [
        _ruling_row(AMAZONESS_CALL_RULING_2017, date(2017, 7, 22), [13174, 8963, 5505, 5682]),
        _ruling_row(AMAZONESS_CALL_RULING_2026, None, [13174, 8963, 5914]),
    ])

    stored = {r["id"]: r for r in get_rulings_for_card(card_id)}
    assert set(stored) == set(ids) and len(ids) == 2
    assert stored[ids[0]]["ruling_text"] == AMAZONESS_CALL_RULING_2017
    assert stored[ids[0]]["ruling_date"] == date(2017, 7, 22)
    assert stored[ids[1]]["ruling_date"] is None
    assert stored[ids[1]]["referenced_konami_ids"] == [13174, 8963, 5914]


def test_insert_rulings_is_all_or_nothing():
    import psycopg

    from aijudge.db.rulings_repo import get_rulings_for_card, insert_rulings
    from tests.rulings_fixtures import AMAZONESS_CALL_RULING_2017, AMAZONESS_CALL_RULING_2026

    card_id = _insert_amazoness_call()
    with pytest.raises(psycopg.Error):
        insert_rulings(card_id, [
            _ruling_row(AMAZONESS_CALL_RULING_2017, date(2017, 7, 22), [13174, 8963, 5505, 5682]),
            _ruling_row(AMAZONESS_CALL_RULING_2026, None, ["not-an-int"]),
        ])

    assert get_rulings_for_card(card_id) == []


def test_update_ruling_referenced_ids_leaves_the_ruling_unresolved():
    from aijudge.db.rulings_repo import (
        get_rulings_for_card,
        insert_ruling,
        list_unresolved_rulings,
        update_ruling_referenced_ids,
    )
    from tests.rulings_fixtures import AMAZONESS_CALL_RULING_2017

    card_id = _insert_amazoness_call()
    ruling_id = insert_ruling(card_id=card_id, ruling_text=AMAZONESS_CALL_RULING_2017, source="db.ygoresources")

    update_ruling_referenced_ids(ruling_id, [13174, 8963, 5505, 5682])

    [ruling] = get_rulings_for_card(card_id)
    assert ruling["referenced_konami_ids"] == [13174, 8963, 5505, 5682]
    assert ruling["ruling_text_resolved"] is None
    assert ruling["ruling_text"] == AMAZONESS_CALL_RULING_2017
    assert [r["id"] for r in list_unresolved_rulings()] == [ruling_id]


def test_list_unresolved_rulings_and_update_ruling_resolution():
    from aijudge.db.rulings_repo import (
        get_rulings_for_card,
        insert_ruling,
        list_unresolved_rulings,
        update_ruling_resolution,
    )
    from tests.rulings_fixtures import AMAZONESS_CALL_RULING_2017

    card_id = _insert_amazoness_call()
    ruling_id = insert_ruling(card_id=card_id, ruling_text=AMAZONESS_CALL_RULING_2017, source="db.ygoresources")

    unresolved = list_unresolved_rulings()
    assert [r["id"] for r in unresolved] == [ruling_id]
    assert unresolved[0]["card_id"] == card_id

    update_ruling_resolution(ruling_id, ruling_text_resolved="resolved text", referenced_konami_ids=[13174, 8963])

    assert list_unresolved_rulings() == []
    [ruling] = get_rulings_for_card(card_id)
    assert ruling["ruling_text_resolved"] == "resolved text"
    assert ruling["referenced_konami_ids"] == [13174, 8963]
    assert ruling["ruling_text"] == AMAZONESS_CALL_RULING_2017
