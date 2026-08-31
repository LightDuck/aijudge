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


_EFFECT_VEILER_TEXT = (
    "During your opponent's Main Phase (Quick Effect): You can send this "
    "card from your hand to the GY; until the end of this turn, negate "
    "the effects of 1 Effect Monster your opponent controls, also its "
    'ATK becomes 0. You can only use this effect of "Effect Veiler" once '
    "per turn."
)


def test_find_matched_cards_returns_full_card_dict_for_a_mentioned_card():
    from aijudge.db.cards_repo import insert_card
    from aijudge.orchestration.preflight import find_matched_cards

    insert_card(
        name="Effect Veiler",
        card_text=_EFFECT_VEILER_TEXT,
        card_type="Effect Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="95440946",
    )

    matches = find_matched_cards("Can I activate Effect Veiler in response?")

    assert len(matches) == 1
    assert matches[0]["name"] == "Effect Veiler"


def test_find_matched_cards_returns_empty_list_when_nothing_mentioned():
    from aijudge.orchestration.preflight import find_matched_cards

    assert find_matched_cards("What happens if I attack with my dragon?") == []


def test_build_known_facts_context_includes_effect_type_and_spell_speed():
    from aijudge.db.cards_repo import get_card_by_name, insert_card
    from aijudge.db.effects_repo import confirm_effect, insert_pending_effect
    from aijudge.orchestration.preflight import build_known_facts_context

    card_id = insert_card(
        name="Effect Veiler",
        card_text=_EFFECT_VEILER_TEXT,
        card_type="Effect Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="95440946",
    )
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="quick",
        effect="negate the effects of 1 Effect Monster your opponent controls, also its ATK becomes 0.",
    )
    confirm_effect(effect_id)

    context = build_known_facts_context(get_card_by_name("Effect Veiler"))

    assert "Effect Veiler" in context
    assert "spell speed 2" in context
    assert "activatable: True" in context


def test_build_known_facts_context_includes_optional_fields_when_present():
    from aijudge.db.cards_repo import get_card_by_name, insert_card
    from aijudge.db.effects_repo import confirm_effect, insert_pending_effect
    from aijudge.orchestration.preflight import build_known_facts_context

    card_id = insert_card(
        name="Effect Veiler",
        card_text=_EFFECT_VEILER_TEXT,
        card_type="Effect Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="95440946",
    )
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="quick",
        effect="negate the effects of 1 Effect Monster your opponent controls, also its ATK becomes 0.",
        activation_condition="During your opponent's Main Phase (Quick Effect)",
        damage_step_category="atk_def_alter",
        usage_limit_text='You can only use this effect of "Effect Veiler" once per turn.',
    )
    confirm_effect(effect_id)

    context = build_known_facts_context(get_card_by_name("Effect Veiler"))

    assert "During your opponent's Main Phase (Quick Effect)" in context
    assert "atk_def_alter" in context
    assert 'You can only use this effect of "Effect Veiler" once per turn.' in context


def test_build_known_facts_context_omits_optional_fields_when_none():
    from aijudge.db.cards_repo import get_card_by_name, insert_card
    from aijudge.db.effects_repo import confirm_effect, insert_pending_effect
    from aijudge.orchestration.preflight import build_known_facts_context

    card_id = insert_card(
        name="Effect Veiler",
        card_text=_EFFECT_VEILER_TEXT,
        card_type="Effect Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="95440946",
    )
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="quick",
        effect="negate the effects of 1 Effect Monster your opponent controls, also its ATK becomes 0.",
    )
    confirm_effect(effect_id)

    context = build_known_facts_context(get_card_by_name("Effect Veiler"))

    assert "None" not in context


def test_build_known_facts_context_is_empty_when_no_confirmed_effect():
    from aijudge.db.cards_repo import get_card_by_name, insert_card
    from aijudge.orchestration.preflight import build_known_facts_context

    insert_card(
        name="Effect Veiler",
        card_text=_EFFECT_VEILER_TEXT,
        card_type="Effect Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="95440946",
    )

    assert build_known_facts_context(get_card_by_name("Effect Veiler")) == ""


def test_build_known_facts_context_covers_every_confirmed_effect_with_damage_step_legality():
    from aijudge.db.cards_repo import get_card_by_name, insert_card
    from aijudge.db.effects_repo import confirm_effect, insert_pending_effect
    from aijudge.orchestration.preflight import build_known_facts_context

    card_id = insert_card(
        name="Baronne de Fleur",
        card_text="Once per turn: ... Once while face-up on the field, when a card or effect is activated (Quick Effect): ...",
        card_type="Synchro Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="84812061",
    )
    ignition_id = insert_pending_effect(
        card_id=card_id,
        effect_type="ignition",
        effect="destroy it.",
        activation_condition="Once per turn",
    )
    confirm_effect(ignition_id)
    quick_id = insert_pending_effect(
        card_id=card_id,
        effect_type="quick",
        effect="You can negate the activation, and if you do, destroy that card.",
        activation_condition="Once while face-up on the field, when a card or effect is activated (Quick Effect)",
        damage_step_category="negates_activation",
    )
    confirm_effect(quick_id)

    context = build_known_facts_context(get_card_by_name("Baronne de Fleur"))
    lines = context.splitlines()

    assert len(lines) == 3  # header + 2 effect lines
    ignition_line = next(line for line in lines if "effect type ignition" in line)
    quick_line = next(line for line in lines if "effect type quick" in line)
    assert "damage-step legal: False" in ignition_line
    assert "damage-step legal: True" in quick_line
