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
        conn.commit()


def test_insert_and_get_card_by_name():
    from aijudge.db.cards_repo import get_card_by_name, insert_card

    insert_card(
        name="Called by the Grave",
        card_text=(
            "During either player's turn, if a monster(s) is banished, or a card "
            "or effect in the Graveyard is activated: You can target 1 banished "
            "monster; banish it."
        ),
        card_type="Quick-Play Spell",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="47355498",
        deterministic_parse_eligible=True,
    )

    card = get_card_by_name("Called by the Grave")

    assert card is not None
    assert card["card_type"] == "Quick-Play Spell"
    assert card["has_errata"] is False
    assert card["ygoprodeck_id"] == "47355498"
    assert card["ygoresources_id"] is None


def test_insert_and_get_card_stores_race():
    from aijudge.db.cards_repo import get_card_by_name, insert_card

    insert_card(
        name="Called by the Grave",
        card_text="text",
        card_type="Spell Card",
        race="Quick-Play",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="47355498",
        deterministic_parse_eligible=True,
    )

    card = get_card_by_name("Called by the Grave")
    assert card["race"] == "Quick-Play"


def test_insert_card_race_defaults_to_none():
    from aijudge.db.cards_repo import get_card_by_name, insert_card

    insert_card(
        name="Ash Blossom & Joyous Spring",
        card_text="text",
        card_type="Tuner Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="14558127",
        deterministic_parse_eligible=True,
    )

    card = get_card_by_name("Ash Blossom & Joyous Spring")
    assert card["race"] is None


def test_get_card_by_name_returns_none_when_missing():
    from aijudge.db.cards_repo import get_card_by_name

    assert get_card_by_name("Nonexistent Card") is None


def test_insert_errata_version_sets_has_errata_flag():
    from aijudge.db.cards_repo import get_card_by_name, insert_card, insert_errata_version

    card_id = insert_card(
        name="Card With Errata",
        card_text="Original text.",
        card_type="Normal Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="11111111",
        deterministic_parse_eligible=True,
    )

    insert_errata_version(card_id=card_id, errata_date=date(2026, 8, 18), errata_text="Errata'd text.")

    card = get_card_by_name("Card With Errata")
    assert card["has_errata"] is True


def test_get_card_by_name_returns_id_as_str():
    from aijudge.db.cards_repo import get_card_by_name, insert_card

    card_id = insert_card(
        name="Test Card for ID Type",
        card_text="Test text",
        card_type="Normal Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="22222222",
        deterministic_parse_eligible=True,
    )

    card = get_card_by_name("Test Card for ID Type")

    assert card is not None
    assert isinstance(card["id"], str), f"Expected card['id'] to be str, got {type(card['id'])}"
    assert card["id"] == card_id


def test_get_card_by_ygoprodeck_id_finds_inserted_card():
    from aijudge.db.cards_repo import get_card_by_ygoprodeck_id, insert_card

    card_id = insert_card(
        name="Effect Veiler",
        card_text="During your opponent's Main Phase (Quick Effect): You can send this card from your hand to the GY, "
        "and if you do, target 1 face-up Effect Monster your opponent controls; negate that face-up monster's effects, "
        "also, if this face-up card is a Level 5 or higher monster, you cannot activate this effect.",
        card_type="Effect Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="95440946",
        deterministic_parse_eligible=True,
    )

    card = get_card_by_ygoprodeck_id("95440946")

    assert card is not None
    assert card["id"] == card_id
    assert card["ygoprodeck_id"] == "95440946"


def test_get_card_by_ygoprodeck_id_returns_none_when_missing():
    from aijudge.db.cards_repo import get_card_by_ygoprodeck_id

    assert get_card_by_ygoprodeck_id("00000000") is None


def test_get_card_by_ygoresources_id_finds_inserted_card():
    from aijudge.db.cards_repo import get_card_by_ygoresources_id, insert_card

    card_id = insert_card(
        name="Solemn Strike",
        card_text="Negate the Summon of a monster, or an attack, and if you do, destroy it. If you Tribute a "
        "monster with 3000 or more ATK: This card gains this effect. You take no damage from battles involving your "
        "opponent's monsters, until the end of this turn.",
        card_type="Counter Trap",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="40605147",
        ygoresources_id="ss-yr-001",
        deterministic_parse_eligible=True,
    )

    card = get_card_by_ygoresources_id("ss-yr-001")

    assert card is not None
    assert card["id"] == card_id
    assert card["ygoresources_id"] == "ss-yr-001"


def test_get_card_by_ygoresources_id_returns_none_for_unmatched_id():
    from aijudge.db.cards_repo import get_card_by_ygoresources_id, insert_card

    insert_card(
        name="Solemn Judgment",
        card_text="When a monster(s) would be Summoned, OR your opponent Sets a Spell/Trap Card, OR a Spell/Trap "
        "Card is activated: Pay half your LP, negate the Summon, activation, or Set, and destroy it.",
        card_type="Counter Trap",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="41420027",
        ygoresources_id="sj-yr-001",
        deterministic_parse_eligible=True,
    )

    assert get_card_by_ygoresources_id("some-other-id") is None


def test_get_card_by_ygoresources_id_returns_none_when_card_has_no_ygoresources_id():
    from aijudge.db.cards_repo import get_card_by_ygoresources_id, insert_card

    insert_card(
        name="Ash Blossom & Joyous Spring",
        card_text="You can only use each of the following effects of \"Ash Blossom & Joyous Spring\" once per turn.",
        card_type="Effect Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="14558127",
        deterministic_parse_eligible=True,
    )

    assert get_card_by_ygoresources_id("14558127") is None
    assert get_card_by_ygoresources_id("") is None


def test_list_card_names_returns_every_inserted_card_name():
    from aijudge.db.cards_repo import insert_card, list_card_names

    insert_card(
        name="Effect Veiler",
        card_text="text",
        card_type="Effect Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="95440946",
        deterministic_parse_eligible=True,
    )
    insert_card(
        name="Solemn Strike",
        card_text="text",
        card_type="Counter Trap",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="40605147",
        deterministic_parse_eligible=True,
    )

    assert set(list_card_names()) == {"Effect Veiler", "Solemn Strike"}


def test_list_card_names_returns_empty_list_when_no_cards():
    from aijudge.db.cards_repo import list_card_names

    assert list_card_names() == []


def test_get_card_by_id_finds_inserted_card():
    from aijudge.db.cards_repo import get_card_by_id, insert_card

    card_id = insert_card(
        name="Effect Veiler",
        card_text="text",
        card_type="Effect Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="95440946",
        deterministic_parse_eligible=True,
    )

    card = get_card_by_id(card_id)

    assert card is not None
    assert card["id"] == card_id
    assert card["name"] == "Effect Veiler"


def test_get_card_by_id_returns_none_when_missing():
    from aijudge.db.cards_repo import get_card_by_id

    assert get_card_by_id("00000000-0000-0000-0000-000000000000") is None


def test_get_cards_by_fname_matches_substring_case_insensitively():
    from aijudge.db.cards_repo import get_cards_by_fname, insert_card

    insert_card(
        name="Salamangreat Almiraj",
        card_text="text",
        card_type="Effect Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="11111111",
        deterministic_parse_eligible=True,
    )
    insert_card(
        name="Effect Veiler",
        card_text="text",
        card_type="Effect Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="95440946",
        deterministic_parse_eligible=True,
    )

    cards = get_cards_by_fname("salamangreat")

    assert [card["name"] for card in cards] == ["Salamangreat Almiraj"]


def test_get_cards_by_fname_returns_empty_list_when_no_match():
    from aijudge.db.cards_repo import get_cards_by_fname

    assert get_cards_by_fname("Nonexistent") == []


def test_get_cards_by_archetype_matches_exactly():
    from aijudge.db.cards_repo import get_cards_by_archetype, insert_card

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
    insert_card(
        name="Effect Veiler",
        card_text="text",
        card_type="Effect Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="95440946",
        deterministic_parse_eligible=True,
    )

    cards = get_cards_by_archetype("Salamangreat")

    assert {card["name"] for card in cards} == {"Salamangreat Almiraj", "Salamangreat Balelynx"}


def test_get_cards_by_archetype_returns_empty_list_when_no_match():
    from aijudge.db.cards_repo import get_cards_by_archetype

    assert get_cards_by_archetype("Nonexistent") == []


def test_find_card_by_priority_returns_single_on_exact_name():
    from aijudge.db.cards_repo import find_card_by_priority, insert_card

    insert_card(
        name="Effect Veiler",
        card_text="text",
        card_type="Effect Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="95440946",
        deterministic_parse_eligible=True,
    )

    status, cards = find_card_by_priority("Effect Veiler")

    assert status == "single"
    assert [card["name"] for card in cards] == ["Effect Veiler"]


def test_find_card_by_priority_falls_back_to_fname():
    from aijudge.db.cards_repo import find_card_by_priority, insert_card

    insert_card(
        name="Salamangreat Almiraj",
        card_text="text",
        card_type="Effect Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="11111111",
        deterministic_parse_eligible=True,
    )

    status, cards = find_card_by_priority("Salamangreat Alm")

    assert status == "single"
    assert cards[0]["name"] == "Salamangreat Almiraj"


def test_find_card_by_priority_falls_back_to_archetype_then_ygoprodeck_id():
    from aijudge.db.cards_repo import find_card_by_priority, insert_card

    insert_card(
        name="Effect Veiler",
        card_text="text",
        card_type="Effect Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="95440946",
        deterministic_parse_eligible=True,
    )

    status, cards = find_card_by_priority("95440946")

    assert status == "single"
    assert cards[0]["name"] == "Effect Veiler"


def test_find_card_by_priority_returns_ambiguous_on_multiple_matches():
    from aijudge.db.cards_repo import find_card_by_priority, insert_card

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

    status, cards = find_card_by_priority("Salamangreat")

    assert status == "ambiguous"
    assert cards == []


def test_find_card_by_priority_returns_none_when_nothing_matches():
    from aijudge.db.cards_repo import find_card_by_priority

    status, cards = find_card_by_priority("Nonexistent Card")

    assert status == "none"
    assert cards == []


def test_find_card_by_priority_with_explicit_field_skips_chain():
    from aijudge.db.cards_repo import find_card_by_priority, insert_card

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

    status, cards = find_card_by_priority("Salamangreat", field="name")

    assert status == "none"
    assert cards == []


def test_insert_card_requires_and_persists_deterministic_parse_eligible():
    from aijudge.db.cards_repo import get_card_by_name, insert_card

    insert_card(
        name="Eligible Test Card",
        card_text="Some effect text.",
        card_type="Effect Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 1, 1),
        ygoprodeck_id="1",
        deterministic_parse_eligible=True,
    )

    card = get_card_by_name("Eligible Test Card")

    assert card["deterministic_parse_eligible"] is True


def test_insert_card_no_longer_accepts_card_materials():
    from aijudge.db.cards_repo import insert_card

    with pytest.raises(TypeError):
        insert_card(
            name="Should Fail",
            card_text="text",
            card_type="Effect Monster",
            source="ygoprodeck",
            fetched_at=date(2026, 1, 1),
            ygoprodeck_id="2",
            deterministic_parse_eligible=True,
            card_materials="should not be accepted",
        )
