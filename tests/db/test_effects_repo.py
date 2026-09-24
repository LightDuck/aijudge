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


def _make_card_id() -> str:
    from aijudge.db.cards_repo import insert_card

    return insert_card(
        name="Infinite Impermanence",
        card_text="Target 1 face-up monster on the field; negate its effects...",
        card_type="Trap Card",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="10045474",
        deterministic_parse_eligible=True,
    )


def test_pending_effect_is_not_returned_as_confirmed():
    from aijudge.db.effects_repo import get_confirmed_effects, insert_pending_effect

    card_id = _make_card_id()
    insert_pending_effect(
        card_id=card_id,
        effect_type="quick-like",
        effect="negate its effects, also, if this card is in the Graveyard...",
        targeting="Target 1 face-up monster on the field",
    )

    assert get_confirmed_effects(card_id) == []


def test_confirm_effect_makes_it_retrievable():
    from aijudge.db.effects_repo import confirm_effect, get_confirmed_effects, insert_pending_effect

    card_id = _make_card_id()
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="quick-like",
        effect="negate its effects.",
        targeting="Target 1 face-up monster on the field",
    )

    confirm_effect(effect_id)
    effects = get_confirmed_effects(card_id)

    assert len(effects) == 1
    assert effects[0]["effect_type"] == "quick-like"
    assert effects[0]["targeting"] == "Target 1 face-up monster on the field"


def test_get_confirmed_effects_returns_id_as_str():
    from aijudge.db.effects_repo import confirm_effect, get_confirmed_effects, insert_pending_effect

    card_id = _make_card_id()
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="quick-like",
        effect="negate its effects.",
        targeting="Target 1 face-up monster on the field",
    )

    confirm_effect(effect_id)
    effects = get_confirmed_effects(card_id)

    assert isinstance(effects[0]["id"], str), f"Expected id to be str, got {type(effects[0]['id'])}"
    assert effects[0]["id"] == effect_id


def test_confirmed_effects_include_has_target():
    from aijudge.db.effects_repo import confirm_effect, get_confirmed_effects, insert_pending_effect

    card_id = _make_card_id()
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="quick-like",
        effect="negate its effects.",
        targeting="Target 1 face-up monster on the field",
        has_target=True,
    )

    confirm_effect(effect_id)
    effects = get_confirmed_effects(card_id)

    assert effects[0]["has_target"] is True


def test_confirm_effect_raises_when_id_does_not_exist():
    from aijudge.db.effects_repo import confirm_effect

    with pytest.raises(ValueError):
        confirm_effect("00000000-0000-0000-0000-000000000000")


def test_confirmed_effects_include_damage_step_category_and_usage_limit_text():
    from aijudge.db.effects_repo import confirm_effect, get_confirmed_effects, insert_pending_effect

    card_id = _make_card_id()
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="quick",
        effect="its ATK becomes 0.",
        damage_step_category="atk_def_alter",
        usage_limit_text='You can only use this effect of "Effect Veiler" once per turn.',
    )

    confirm_effect(effect_id)
    effects = get_confirmed_effects(card_id)

    assert effects[0]["damage_step_category"] == "atk_def_alter"
    assert effects[0]["usage_limit_text"] == 'You can only use this effect of "Effect Veiler" once per turn.'


def test_confirmed_effects_damage_step_category_and_usage_limit_text_default_to_none():
    from aijudge.db.effects_repo import confirm_effect, get_confirmed_effects, insert_pending_effect

    card_id = _make_card_id()
    effect_id = insert_pending_effect(card_id=card_id, effect_type="ignition", effect="destroy it.")

    confirm_effect(effect_id)
    effects = get_confirmed_effects(card_id)

    assert effects[0]["damage_step_category"] is None
    assert effects[0]["usage_limit_text"] is None


def test_confirmed_effects_include_has_effect_choice():
    from aijudge.db.effects_repo import confirm_effect, get_confirmed_effects, insert_pending_effect

    card_id = _make_card_id()
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="ignition",
        effect="you can apply 1 of these effects. * Draw 1 card.",
        has_effect_choice=True,
    )

    confirm_effect(effect_id)
    effects = get_confirmed_effects(card_id)

    assert effects[0]["has_effect_choice"] is True


def test_confirmed_effects_has_effect_choice_defaults_to_false():
    from aijudge.db.effects_repo import confirm_effect, get_confirmed_effects, insert_pending_effect

    card_id = _make_card_id()
    effect_id = insert_pending_effect(card_id=card_id, effect_type="ignition", effect="destroy it.")

    confirm_effect(effect_id)
    effects = get_confirmed_effects(card_id)

    assert effects[0]["has_effect_choice"] is False


def test_get_confirmed_effects_returns_every_confirmed_row_for_a_card():
    from aijudge.db.effects_repo import confirm_effect, get_confirmed_effects, insert_pending_effect

    card_id = _make_card_id()
    first_id = insert_pending_effect(card_id=card_id, effect_type="ignition", effect="destroy it.")
    second_id = insert_pending_effect(card_id=card_id, effect_type="quick", effect="negate the activation.")
    # A pending (unconfirmed) row must never be returned alongside the confirmed ones.
    insert_pending_effect(card_id=card_id, effect_type="trigger", effect="draw 1 card.")
    confirm_effect(first_id)
    confirm_effect(second_id)

    effects = get_confirmed_effects(card_id)

    assert len(effects) == 2
    assert {e["effect_type"] for e in effects} == {"ignition", "quick"}
