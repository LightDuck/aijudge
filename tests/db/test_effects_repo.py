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


def _make_card_id() -> str:
    from aijudge.db.cards_repo import insert_card

    return insert_card(
        name="Infinite Impermanence",
        card_text="Target 1 face-up monster on the field; negate its effects...",
        card_type="Trap Card",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="10045474",
    )


def test_pending_effect_is_not_returned_as_confirmed():
    from aijudge.db.effects_repo import get_confirmed_effect, insert_pending_effect

    card_id = _make_card_id()
    insert_pending_effect(
        card_id=card_id,
        effect_type="quick-like",
        effect="negate its effects, also, if this card is in the Graveyard...",
        targeting="Target 1 face-up monster on the field",
    )

    assert get_confirmed_effect(card_id) is None


def test_confirm_effect_makes_it_retrievable():
    from aijudge.db.effects_repo import confirm_effect, get_confirmed_effect, insert_pending_effect

    card_id = _make_card_id()
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="quick-like",
        effect="negate its effects.",
        targeting="Target 1 face-up monster on the field",
    )

    confirm_effect(effect_id)
    confirmed = get_confirmed_effect(card_id)

    assert confirmed is not None
    assert confirmed["effect_type"] == "quick-like"
    assert confirmed["targeting"] == "Target 1 face-up monster on the field"


def test_get_confirmed_effect_returns_id_as_str():
    from aijudge.db.effects_repo import confirm_effect, get_confirmed_effect, insert_pending_effect

    card_id = _make_card_id()
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="quick-like",
        effect="negate its effects.",
        targeting="Target 1 face-up monster on the field",
    )

    confirm_effect(effect_id)
    confirmed = get_confirmed_effect(card_id)

    assert confirmed is not None
    assert isinstance(confirmed["id"], str), f"Expected confirmed['id'] to be str, got {type(confirmed['id'])}"
    assert confirmed["id"] == effect_id


def test_confirmed_effect_includes_has_target():
    from aijudge.db.effects_repo import confirm_effect, get_confirmed_effect, insert_pending_effect

    card_id = _make_card_id()
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="quick-like",
        effect="negate its effects.",
        targeting="Target 1 face-up monster on the field",
        has_target=True,
    )

    confirm_effect(effect_id)
    confirmed = get_confirmed_effect(card_id)

    assert confirmed is not None
    assert confirmed["has_target"] is True


def test_confirm_effect_raises_when_id_does_not_exist():
    from aijudge.db.effects_repo import confirm_effect

    with pytest.raises(ValueError):
        confirm_effect("00000000-0000-0000-0000-000000000000")


def test_confirmed_effect_includes_damage_step_category_and_usage_limit_text():
    from aijudge.db.effects_repo import confirm_effect, get_confirmed_effect, insert_pending_effect

    card_id = _make_card_id()
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="quick",
        effect="its ATK becomes 0.",
        damage_step_category="atk_def_alter",
        usage_limit_text='You can only use this effect of "Effect Veiler" once per turn.',
    )

    confirm_effect(effect_id)
    confirmed = get_confirmed_effect(card_id)

    assert confirmed is not None
    assert confirmed["damage_step_category"] == "atk_def_alter"
    assert confirmed["usage_limit_text"] == 'You can only use this effect of "Effect Veiler" once per turn.'


def test_confirmed_effect_damage_step_category_and_usage_limit_text_default_to_none():
    from aijudge.db.effects_repo import confirm_effect, get_confirmed_effect, insert_pending_effect

    card_id = _make_card_id()
    effect_id = insert_pending_effect(card_id=card_id, effect_type="ignition", effect="destroy it.")

    confirm_effect(effect_id)
    confirmed = get_confirmed_effect(card_id)

    assert confirmed["damage_step_category"] is None
    assert confirmed["usage_limit_text"] is None
