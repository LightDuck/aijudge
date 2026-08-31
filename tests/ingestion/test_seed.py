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


def test_seed_card_stores_card_ruling_and_confirms_a_high_confidence_effect():
    from aijudge.db.cards_repo import get_card_by_name
    from aijudge.db.effects_repo import get_confirmed_effect
    from aijudge.db.rulings_repo import get_rulings_for_card
    from aijudge.ingestion.seed import seed_card
    from aijudge.llm.client import MockLLMClient

    def fake_fetch_card(name, http_get=None):
        return {
            "id": 47355498,
            "name": name,
            "type": "Quick-Play Spell",
            "desc": "You can target 1 banished monster; banish it.",
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
    )

    card = get_card_by_name("Called by the Grave")
    assert card is not None
    assert card["id"] == card_id
    assert card["ygoprodeck_id"] == "47355498"

    rulings = get_rulings_for_card(card_id)
    assert len(rulings) == 1

    confirmed_effect = get_confirmed_effect(card_id)
    assert confirmed_effect is not None
    assert confirmed_effect["targeting"] == "target 1 banished monster"
    assert confirmed_effect["has_target"] is True

    from aijudge.db.connection import get_connection

    with get_connection() as conn:
        row = conn.execute(
            "SELECT confidence_score FROM card_effects_structured WHERE id = %s",
            (confirmed_effect["id"],),
        ).fetchone()
    assert row[0] == pytest.approx(0.97)


def test_seed_card_leaves_low_confidence_effect_pending():
    from aijudge.db.cards_repo import get_card_by_name
    from aijudge.db.effects_repo import get_confirmed_effect
    from aijudge.ingestion.seed import seed_card
    from aijudge.llm.client import MockLLMClient

    def fake_fetch_card(name, http_get=None):
        return {
            "id": 10045474,
            "name": name,
            "type": "Trap Card",
            "desc": "Target 1 face-up monster; negate its effects.",
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
    )

    assert get_card_by_name("Ambiguous Trap")["id"] == card_id
    assert get_confirmed_effect(card_id) is None


def test_seed_card_classifies_a_tuner_monster_subtype_as_a_monster_effect():
    """Real YGOPRODeck 'type' values include many monster subtypes beyond the
    six main Extra/Main Deck types (e.g. 'Tuner Monster', 'Ritual Monster').
    All of these should be treated as monsters, not fall through to
    spell/trap effect-type vocabulary."""
    from aijudge.db.cards_repo import get_card_by_name
    from aijudge.ingestion.seed import seed_card
    from aijudge.llm.client import MockLLMClient

    def fake_fetch_card(name, http_get=None):
        return {
            "id": 97268402,
            "name": name,
            "type": "Tuner Monster",
            "desc": "If this card is Normal Summoned: You can add 1 card from your Deck to your hand.",
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
    from aijudge.db.effects_repo import get_confirmed_effect
    from aijudge.ingestion.seed import seed_card
    from aijudge.llm.client import MockLLMClient

    def fake_fetch_card(name, http_get=None):
        return {
            "id": 95440946,
            "name": name,
            "type": "Effect Monster",
            "desc": (
                "During your opponent's Main Phase (Quick Effect): You can send this "
                "card from your hand to the GY; until the end of this turn, negate "
                "the effects of 1 Effect Monster your opponent controls, also its "
                'ATK becomes 0. You can only use this effect of "Effect Veiler" once '
                "per turn."
            ),
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
    )

    confirmed_effect = get_confirmed_effect(card_id)
    assert confirmed_effect is not None
    assert confirmed_effect["damage_step_category"] == "atk_def_alter"
    assert confirmed_effect["usage_limit_text"] == 'You can only use this effect of "Effect Veiler" once per turn.'
