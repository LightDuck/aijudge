import os
from datetime import date

import pytest
import requests

pytestmark = pytest.mark.skipif("DATABASE_URL" not in os.environ, reason="requires a running Postgres instance")


def setup_function():
    from aijudge.db.connection import get_connection
    from aijudge.db.migrate import run_migrations

    run_migrations()
    with get_connection() as conn:
        conn.execute("TRUNCATE cards CASCADE")
        conn.commit()


def test_seed_card_stores_card_ruling_and_confirms_a_high_confidence_effect():
    from aijudge.db.cards_repo import get_card_by_name
    from aijudge.db.effects_repo import get_confirmed_effects
    from aijudge.db.rulings_repo import get_rulings_for_card
    from aijudge.ingestion.seed import seed_card
    from aijudge.llm.client import MockLLMClient

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
    llm_client.queue_response("0.97")  # review agent confidence for the parsed effect

    card_id = seed_card(
        "Called by the Grave",
        llm_client=llm_client,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=fake_fetch_rulings,
        fetch_sets_index_fn=lambda: {"Some Set": date(2020, 1, 1)},
    )

    card = get_card_by_name("Called by the Grave")
    assert card is not None
    assert card["id"] == card_id
    assert card["ygoprodeck_id"] == "47355498"

    rulings = get_rulings_for_card(card_id)
    assert len(rulings) == 1

    effects = get_confirmed_effects(card_id)
    assert len(effects) == 1
    assert effects[0]["targeting"] == "target 1 banished monster"
    assert effects[0]["has_target"] is True

    from aijudge.db.connection import get_connection

    with get_connection() as conn:
        row = conn.execute(
            "SELECT confidence_score FROM card_effects_structured WHERE id = %s",
            (effects[0]["id"],),
        ).fetchone()
    assert row[0] == pytest.approx(0.97)


def test_seed_card_passes_konami_id_from_misc_info_to_fetch_rulings():
    from aijudge.ingestion.seed import seed_card
    from aijudge.llm.client import MockLLMClient

    desc = "You can target 1 banished monster; banish it."
    received = []

    def fake_fetch_card(name, http_get=None):
        return {
            "id": 47355498,
            "name": name,
            "type": "Quick-Play Spell",
            "desc": desc,
            "misc_info": [{"konami_id": 9729}],
            "card_sets": [{"set_name": "Some Set"}],
        }

    def fake_fetch_rulings(konami_id, http_get=None):
        received.append(konami_id)
        return []

    llm_client = MockLLMClient()
    llm_client.queue_response("0.97")  # review agent confidence for the parsed effect

    seed_card(
        "Called by the Grave",
        llm_client=llm_client,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=fake_fetch_rulings,
        fetch_sets_index_fn=lambda: {"Some Set": date(2020, 1, 1)},
    )

    assert received == [9729]


def test_seed_card_continues_when_fetching_rulings_fails():
    from aijudge.db.cards_repo import get_card_by_name
    from aijudge.db.effects_repo import get_confirmed_effects
    from aijudge.db.rulings_repo import get_rulings_for_card
    from aijudge.ingestion.seed import seed_card
    from aijudge.llm.client import MockLLMClient

    desc = "You can target 1 banished monster; banish it."

    def fake_fetch_card(name, http_get=None):
        return {
            "id": 47355498,
            "name": name,
            "type": "Quick-Play Spell",
            "desc": desc,
            "card_sets": [{"set_name": "Some Set"}],
        }

    def fake_fetch_rulings(konami_id, http_get=None):
        raise requests.exceptions.HTTPError("404 Client Error: Not Found")

    llm_client = MockLLMClient()
    llm_client.queue_response("0.97")  # review agent confidence for the parsed effect

    card_id = seed_card(
        "Called by the Grave",
        llm_client=llm_client,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=fake_fetch_rulings,
        fetch_sets_index_fn=lambda: {"Some Set": date(2020, 1, 1)},
    )

    assert get_card_by_name("Called by the Grave")["id"] == card_id
    assert get_rulings_for_card(card_id) == []
    assert len(get_confirmed_effects(card_id)) == 1


def test_seed_card_leaves_low_confidence_effect_pending():
    from aijudge.db.cards_repo import get_card_by_name
    from aijudge.db.effects_repo import get_confirmed_effects
    from aijudge.ingestion.seed import seed_card
    from aijudge.llm.client import MockLLMClient

    desc = "Target 1 face-up monster; negate its effects."

    def fake_fetch_card(name, http_get=None):
        return {
            "id": 10045474,
            "name": name,
            "type": "Trap Card",
            "desc": desc,
            "card_sets": [{"set_name": "Some Set"}],
        }

    def fake_fetch_rulings(name, http_get=None):
        return []

    llm_client = MockLLMClient()
    llm_client.queue_response("0.3")  # deliberately low confidence

    card_id = seed_card(
        "Ambiguous Trap",
        llm_client=llm_client,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=fake_fetch_rulings,
        fetch_sets_index_fn=lambda: {"Some Set": date(2020, 1, 1)},
    )

    assert get_card_by_name("Ambiguous Trap")["id"] == card_id
    assert get_confirmed_effects(card_id) == []


def test_seed_card_classifies_a_tuner_monster_subtype_as_a_monster_effect():
    """Real YGOPRODeck 'type' values include many monster subtypes beyond the
    six main Extra/Main Deck types (e.g. 'Tuner Monster', 'Ritual Monster').
    All of these should be treated as monsters, not fall through to
    spell/trap effect-type vocabulary."""
    from aijudge.db.cards_repo import get_card_by_name
    from aijudge.ingestion.seed import seed_card
    from aijudge.llm.client import MockLLMClient

    desc = "If this card is Normal Summoned: You can add 1 card from your Deck to your hand."

    def fake_fetch_card(name, http_get=None):
        return {
            "id": 97268402,
            "name": name,
            "type": "Tuner Monster",
            "desc": desc,
            "card_sets": [{"set_name": "Some Set"}],
        }

    def fake_fetch_rulings(name, http_get=None):
        return []

    llm_client = MockLLMClient()
    llm_client.queue_response("0.97")

    card_id = seed_card(
        "Some Tuner",
        llm_client=llm_client,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=fake_fetch_rulings,
        fetch_sets_index_fn=lambda: {"Some Set": date(2020, 1, 1)},
    )

    assert get_card_by_name("Some Tuner")["id"] == card_id

    from aijudge.db.connection import get_connection

    with get_connection() as conn:
        row = conn.execute(
            "SELECT effect_type FROM card_effects_structured WHERE card_id = %s",
            (card_id,),
        ).fetchone()
    assert row[0] == "trigger"


def test_seed_card_stores_damage_step_category_and_usage_limit_text():
    from aijudge.db.effects_repo import get_confirmed_effects
    from aijudge.ingestion.seed import seed_card
    from aijudge.llm.client import MockLLMClient

    desc = (
        "During your opponent's Main Phase (Quick Effect): You can send this "
        "card from your hand to the GY; until the end of this turn, negate "
        "the effects of 1 Effect Monster your opponent controls, also its "
        'ATK becomes 0. You can only use this effect of "Effect Veiler" once '
        "per turn."
    )

    def fake_fetch_card(name, http_get=None):
        return {
            "id": 95440946,
            "name": name,
            "type": "Effect Monster",
            "desc": desc,
            "card_sets": [{"set_name": "Some Set"}],
        }

    def fake_fetch_rulings(name, http_get=None):
        return []

    llm_client = MockLLMClient()
    llm_client.queue_response("0.97")

    card_id = seed_card(
        "Effect Veiler",
        llm_client=llm_client,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=fake_fetch_rulings,
        fetch_sets_index_fn=lambda: {"Some Set": date(2020, 1, 1)},
    )

    effects = get_confirmed_effects(card_id)
    assert len(effects) == 1
    assert effects[0]["damage_step_category"] == "atk_def_alter"
    assert effects[0]["usage_limit_text"] == 'You can only use this effect of "Effect Veiler" once per turn.'


def test_seed_card_uses_race_field_for_a_quick_play_spell():
    """Real YGOPRODeck API shape: `type` is the generic 'Spell Card', the
    Quick-Play subtype comes back in a separate `race` field. Both must be
    stored, and race (not a card_type substring that the real API never
    populates) must drive the resulting effect's spell speed."""
    from aijudge.db.cards_repo import get_card_by_name
    from aijudge.db.effects_repo import get_confirmed_effects
    from aijudge.ingestion.seed import seed_card
    from aijudge.llm.client import MockLLMClient

    desc = "Target 1 monster in your opponent's GY; banish it."

    def fake_fetch_card(name, http_get=None):
        return {
            "id": 47355498,
            "name": name,
            "type": "Spell Card",
            "race": "Quick-Play",
            "desc": desc,
            "card_sets": [{"set_name": "Some Set"}],
        }

    def fake_fetch_rulings(name, http_get=None):
        return []

    llm_client = MockLLMClient()
    llm_client.queue_response("0.97")  # review agent confidence

    card_id = seed_card(
        "Called by the Grave",
        llm_client=llm_client,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=fake_fetch_rulings,
        fetch_sets_index_fn=lambda: {"Some Set": date(2020, 1, 1)},
    )

    card = get_card_by_name("Called by the Grave")
    assert card["card_type"] == "Spell Card"
    assert card["race"] == "Quick-Play"

    effects = get_confirmed_effects(card_id)
    assert effects[0]["effect_type"] == "quick-like"


def test_seed_card_uses_race_field_for_a_counter_trap():
    """Same real-API-shape gap as the Quick-Play case above, but for
    Solemn Strike: type='Trap Card' (generic), race='Counter'."""
    from aijudge.db.cards_repo import get_card_by_name
    from aijudge.ingestion.seed import seed_card
    from aijudge.llm.client import MockLLMClient

    desc = "Pay 1500 LP; negate the Summon or activation, and if you do, destroy that card."

    def fake_fetch_card(name, http_get=None):
        return {
            "id": 40605147,
            "name": name,
            "type": "Trap Card",
            "race": "Counter",
            "desc": desc,
            "card_sets": [{"set_name": "Some Set"}],
        }

    def fake_fetch_rulings(name, http_get=None):
        return []

    llm_client = MockLLMClient()
    llm_client.queue_response("0.97")  # review agent confidence

    seed_card(
        "Solemn Strike",
        llm_client=llm_client,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=fake_fetch_rulings,
        fetch_sets_index_fn=lambda: {"Some Set": date(2020, 1, 1)},
    )

    card = get_card_by_name("Solemn Strike")
    assert card["card_type"] == "Trap Card"
    assert card["race"] == "Counter"


def test_seed_card_creates_one_row_per_effect_for_a_multi_effect_card():
    from aijudge.db.connection import get_connection
    from aijudge.ingestion.seed import seed_card
    from aijudge.llm.client import MockLLMClient

    effect_1 = "Once per turn: You can target 1 card on the field; destroy it."
    effect_2 = (
        'Once while face-up on the field, when a card or effect is activated (Quick Effect): '
        "You can negate the activation, and if you do, destroy that card. "
        'You can only use the previous effect of "Baronne de Fleur" once per turn.'
    )
    effect_3 = (
        "Once per turn, during the Standby Phase: You can target 1 Level 9 or lower monster "
        "in your GY; return this card to the Extra Deck, and if you do, Special Summon that monster."
    )
    desc = f"{effect_1} {effect_2} {effect_3}"

    def fake_fetch_card(name, http_get=None):
        return {
            "id": 84812061,
            "name": name,
            # Not "Synchro Monster" -- the real Baronne de Fleur is an Extra
            # Deck monster with a materials line, but this fixture's `desc`
            # (below) deliberately has no such line since this test is about
            # multi-effect clause splitting, not Card Material extraction
            # (see test_seed_card_extracts_card_material_for_extra_deck_monster
            # for that). An Extra Deck `type` here would make
            # extract_card_material swallow the entire desc as "material"
            # (no newline to split on), leaving nothing to segment.
            "type": "Effect Monster",
            "desc": desc,
            "card_sets": [{"set_name": "Some Set"}],
        }

    def fake_fetch_rulings(name, http_get=None):
        return []

    llm_client = MockLLMClient()
    llm_client.queue_response("0.95")  # split-quality confidence
    llm_client.queue_response("0.97")  # review confidence for effect 1
    llm_client.queue_response("0.97")  # review confidence for effect 2
    llm_client.queue_response("0.97")  # review confidence for effect 3

    card_id = seed_card(
        "Baronne de Fleur",
        llm_client=llm_client,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=fake_fetch_rulings,
        fetch_sets_index_fn=lambda: {"Some Set": date(2020, 1, 1)},
    )

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT effect_type, damage_step_category, status FROM card_effects_structured WHERE card_id = %s",
            (card_id,),
        ).fetchall()

    assert len(rows) == 3
    assert all(row[2] == "confirmed" for row in rows)
    assert {row[0] for row in rows} == {"ignition", "quick"}
    negates_activation_rows = [row for row in rows if row[1] == "negates_activation"]
    assert len(negates_activation_rows) == 1
    assert negates_activation_rows[0][0] == "quick"

    from aijudge.db.effects_repo import get_confirmed_effects

    effects = get_confirmed_effects(card_id)
    quick_effect = next(e for e in effects if e["effect_type"] == "quick")
    assert quick_effect["usage_limit_text"] == 'You can only use the previous effect of "Baronne de Fleur" once per turn.'


def test_seed_card_ineligible_card_gets_single_unclassified_row():
    from aijudge.db.cards_repo import get_card_by_name
    from aijudge.db.effects_repo import get_confirmed_effects
    from aijudge.ingestion.seed import seed_card
    from aijudge.llm.client import MockLLMClient

    desc = "Must be Fusion Summoned and cannot be Special Summoned by other ways."

    def fake_fetch_card(name, http_get=None):
        return {
            "id": 1,
            "name": name,
            "type": "Fusion Monster",
            "desc": desc,
            "card_sets": [{"set_name": "Old Set"}],
        }

    def fake_fetch_rulings(name, http_get=None):
        return []

    llm_client = MockLLMClient()  # no queued responses -- must never be called

    card_id = seed_card(
        "Pre-PSCT Card",
        llm_client=llm_client,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=fake_fetch_rulings,
        fetch_sets_index_fn=lambda: {"Old Set": date(2005, 1, 1)},
    )

    card = get_card_by_name("Pre-PSCT Card")
    assert card["deterministic_parse_eligible"] is False
    assert get_confirmed_effects(card_id) == []

    from aijudge.db.connection import get_connection

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT effect_type, effect, status, confidence_score FROM card_effects_structured WHERE card_id = %s",
            (card_id,),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "unclassified"
    assert rows[0][1] == desc
    assert rows[0][2] == "pending"
    assert rows[0][3] == 0.0


def test_seed_card_extracts_card_material_for_extra_deck_monster():
    from aijudge.db.connection import get_connection
    from aijudge.ingestion.seed import seed_card
    from aijudge.llm.client import MockLLMClient

    desc = (
        '"Tearlaments Kitkallos" + 1 "Tearlaments" monster\n'
        "Other Aqua monsters you control cannot be destroyed by battle."
    )

    def fake_fetch_card(name, http_get=None):
        return {
            "id": 84330567,
            "name": name,
            "type": "Fusion Monster",
            "race": "Aqua",
            "desc": desc,
            "card_sets": [{"set_name": "Darkwing Blast"}],
        }

    def fake_fetch_rulings(name, http_get=None):
        return []

    llm_client = MockLLMClient()
    llm_client.queue_response("0.97")  # review confidence for the one remaining clause

    card_id = seed_card(
        "Tearlaments Rulkallos",
        llm_client=llm_client,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=fake_fetch_rulings,
        fetch_sets_index_fn=lambda: {"Darkwing Blast": date(2022, 10, 20)},
    )

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT effect_type, effect FROM card_effects_structured WHERE card_id = %s ORDER BY effect_type",
            (card_id,),
        ).fetchall()

    material_rows = [row for row in rows if row[0] == "card_material"]
    assert len(material_rows) == 1
    assert material_rows[0][1] == '"Tearlaments Kitkallos" + 1 "Tearlaments" monster'


def test_seed_card_vanilla_extra_deck_monster_inserts_only_material_row():
    from aijudge.db.connection import get_connection
    from aijudge.ingestion.seed import seed_card
    from aijudge.llm.client import MockLLMClient

    def fake_fetch_card(name, http_get=None):
        return {
            "id": 71594310,
            "name": name,
            "type": "XYZ Monster",
            "race": "Rock",
            "desc": "2 Level 4 monsters",
            "card_sets": [{"set_name": "Wing Raiders"}],
        }

    def fake_fetch_rulings(name, http_get=None):
        return []

    llm_client = MockLLMClient()  # no queued responses -- must never be called

    card_id = seed_card(
        "Gem-Knight Pearl",
        llm_client=llm_client,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=fake_fetch_rulings,
        fetch_sets_index_fn=lambda: {"Wing Raiders": date(2015, 1, 9)},
    )

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT effect_type FROM card_effects_structured WHERE card_id = %s",
            (card_id,),
        ).fetchall()

    assert len(rows) == 1
    assert rows[0][0] == "card_material"


def test_seed_card_duplicates_usage_limit_text_across_scoped_clauses():
    from aijudge.db.effects_repo import get_confirmed_effects
    from aijudge.ingestion.seed import seed_card
    from aijudge.llm.client import MockLLMClient

    desc = (
        '"Tearlaments Kitkallos" + 1 "Tearlaments" monster\n'
        "Other Aqua monsters you control cannot be destroyed by battle. You can only use "
        'each of the following effects of "Tearlaments Rulkallos" once per turn. When your '
        "opponent activates a card or effect that includes an effect that Special Summons a "
        "monster(s) (Quick Effect): You can negate the activation, and if you do, destroy "
        'it, then, send 1 "Tearlaments" card from your hand or face-up field to the GY. If '
        "this Fusion Summoned card is sent to the GY by a card effect: You can Special "
        "Summon this card."
    )

    def fake_fetch_card(name, http_get=None):
        return {
            "id": 84330567,
            "name": name,
            "type": "Fusion Monster",
            "race": "Aqua",
            "desc": desc,
            "card_sets": [{"set_name": "Darkwing Blast"}],
        }

    def fake_fetch_rulings(name, http_get=None):
        return []

    llm_client = MockLLMClient()
    llm_client.queue_response("0.95")  # score_split_confidence for the 3 post-material clauses
    llm_client.queue_response("0.97")  # review: Continuous clause
    llm_client.queue_response("0.97")  # review: Quick clause
    llm_client.queue_response("0.97")  # review: Trigger clause

    card_id = seed_card(
        "Tearlaments Rulkallos",
        llm_client=llm_client,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=fake_fetch_rulings,
        fetch_sets_index_fn=lambda: {"Darkwing Blast": date(2022, 10, 20)},
    )

    effects = get_confirmed_effects(card_id)
    by_type = {e["effect_type"]: e for e in effects}

    expected_usage_limit = 'You can only use each of the following effects of "Tearlaments Rulkallos" once per turn.'
    assert by_type["continuous"]["usage_limit_text"] is None
    assert by_type["quick"]["usage_limit_text"] == expected_usage_limit
    assert by_type["trigger"]["usage_limit_text"] == expected_usage_limit
