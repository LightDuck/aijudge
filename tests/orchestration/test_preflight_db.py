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
        deterministic_parse_eligible=True,
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
        deterministic_parse_eligible=True,
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
        deterministic_parse_eligible=True,
    )
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="quick",
        effect="negate the effects of 1 Effect Monster your opponent controls, also its ATK becomes 0.",
        activation_condition="During your opponent's Main Phase (Quick Effect)",
        cost="Send this card from your hand to the GY",
        targeting="1 Effect Monster your opponent controls",
        damage_step_category="atk_def_alter",
        usage_limit_text='You can only use this effect of "Effect Veiler" once per turn.',
    )
    confirm_effect(effect_id)

    context = build_known_facts_context(get_card_by_name("Effect Veiler"))

    assert "During your opponent's Main Phase (Quick Effect)" in context
    assert "Send this card from your hand to the GY" in context
    assert "1 Effect Monster your opponent controls" in context
    assert "atk_def_alter" in context
    assert 'You can only use this effect of "Effect Veiler" once per turn.' in context


def test_build_known_facts_context_marks_absent_optional_fields_as_none():
    # Absent fields are shown explicitly as "none" (not the Python `None`
    # repr, and not silently omitted) -- so the model can state e.g. "this
    # effect has no cost" as a known fact instead of never being told the
    # field exists at all.
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
        deterministic_parse_eligible=True,
    )
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="quick",
        effect="negate the effects of 1 Effect Monster your opponent controls, also its ATK becomes 0.",
    )
    confirm_effect(effect_id)

    context = build_known_facts_context(get_card_by_name("Effect Veiler"))

    assert "None" not in context
    assert "activation condition: none" in context
    assert "cost: none" in context
    assert "targeting: none" in context
    assert "damage step category: none" in context
    assert "usage limit: none" in context


def test_build_known_facts_context_flags_an_effect_choice_clause():
    from aijudge.db.cards_repo import get_card_by_name, insert_card
    from aijudge.db.effects_repo import confirm_effect, insert_pending_effect
    from aijudge.orchestration.preflight import build_known_facts_context

    card_id = insert_card(
        name="Abyss Actor - Super Producer",
        card_text="destroy it, then you can apply 1 of these effects. ...",
        card_type="Link Monster",
        race="Fiend",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="47404795",
        deterministic_parse_eligible=True,
    )
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="quick",
        effect="destroy it, then you can apply 1 of these effects. ...",
        has_effect_choice=True,
    )
    confirm_effect(effect_id)

    context = build_known_facts_context(get_card_by_name("Abyss Actor - Super Producer"))

    assert "choose 1 or more of several listed effects at resolution: True" in context


def test_build_known_facts_context_shows_no_effect_choice_explicitly_when_absent():
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
        deterministic_parse_eligible=True,
    )
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="quick",
        effect="negate the effects of 1 Effect Monster your opponent controls, also its ATK becomes 0.",
    )
    confirm_effect(effect_id)

    context = build_known_facts_context(get_card_by_name("Effect Veiler"))

    assert "choose 1 or more of several listed effects at resolution: False" in context


def test_build_known_facts_context_includes_a_citable_id_for_the_card():
    # Without this, an LLM answering directly from KNOWN FACTS (skipping
    # lookup_card entirely, since the facts already answer the question)
    # has no legitimate id to put in its required CITES trailer and
    # fabricates one instead -- which compute_confidence then correctly
    # flags, escalating every such answer. Giving it the real citable id
    # here closes that gap.
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
        deterministic_parse_eligible=True,
    )
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="quick",
        effect="negate the effects of 1 Effect Monster your opponent controls, also its ATK becomes 0.",
    )
    confirm_effect(effect_id)

    card = get_card_by_name("Effect Veiler")
    context = build_known_facts_context(card)

    assert f"card:{card['id']}" in context


def test_build_known_facts_context_includes_card_type_and_card_text():
    # Before this branch, the LLM could get card_type/card_text by calling
    # the lookup_card tool; the restricted answering turn (tools={}) removed
    # that access and put nothing in its place, which was confirmed to cause
    # a real fabrication in manual testing (a Tuner Monster described as a
    # "Quick-Effect spell card"). KNOWN FACTS must carry both fields itself.
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
        deterministic_parse_eligible=True,
    )
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="quick",
        effect="negate the effects of 1 Effect Monster your opponent controls, also its ATK becomes 0.",
    )
    confirm_effect(effect_id)

    context = build_known_facts_context(get_card_by_name("Effect Veiler"))

    assert "Effect Monster" in context
    assert _EFFECT_VEILER_TEXT in context
    assert "without calling lookup_card" not in context


def test_build_grounded_result_returns_a_lookup_card_shaped_dict():
    from aijudge.db.cards_repo import get_card_by_name, insert_card
    from aijudge.db.effects_repo import confirm_effect, insert_pending_effect
    from aijudge.orchestration.preflight import build_grounded_result

    card_id = insert_card(
        name="Effect Veiler",
        card_text=_EFFECT_VEILER_TEXT,
        card_type="Effect Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="95440946",
        deterministic_parse_eligible=True,
    )
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="quick",
        effect="negate the effects of 1 Effect Monster your opponent controls, also its ATK becomes 0.",
    )
    confirm_effect(effect_id)

    card = get_card_by_name("Effect Veiler")
    result = build_grounded_result(card)

    assert result["found"] is True
    assert result["id"] == card["id"]
    assert result["ygoprodeck_id"] == "95440946"
    assert result["name"] == "Effect Veiler"
    assert result["card_text"] == _EFFECT_VEILER_TEXT
    assert len(result["confirmed_effects"]) == 1


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
        deterministic_parse_eligible=True,
    )

    assert build_known_facts_context(get_card_by_name("Effect Veiler")) == ""


def test_build_known_facts_context_reads_counter_trap_speed_from_race_not_card_type():
    """Real YGOPRODeck API shape: card_type is the generic 'Trap Card', the
    Counter subtype lives in `race`. spell_speed_for must read that race
    field back off the stored card row -- a card_type substring check can
    never see "Counter" since the real API never puts it there."""
    from aijudge.db.cards_repo import get_card_by_name, insert_card
    from aijudge.db.effects_repo import confirm_effect, insert_pending_effect
    from aijudge.orchestration.preflight import build_known_facts_context

    card_id = insert_card(
        name="Solemn Strike",
        card_text="Negate the Summon of a monster, or an attack, and if you do, destroy it.",
        card_type="Trap Card",
        race="Counter",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="40605147",
        deterministic_parse_eligible=True,
    )
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="trigger-like",
        effect="negate the Summon or activation, and if you do, destroy that card.",
    )
    confirm_effect(effect_id)

    context = build_known_facts_context(get_card_by_name("Solemn Strike"))

    assert "spell speed 3" in context


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
        deterministic_parse_eligible=True,
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


def test_build_known_facts_context_renders_card_material_distinctly():
    from aijudge.db.cards_repo import get_card_by_name, insert_card
    from aijudge.db.effects_repo import confirm_effect, insert_pending_effect
    from aijudge.orchestration.preflight import build_known_facts_context

    card_id = insert_card(
        name="Tearlaments Rulkallos",
        card_text='"Tearlaments Kitkallos" + 1 "Tearlaments" monster\nOther Aqua monsters...',
        card_type="Fusion Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="84330567",
        deterministic_parse_eligible=True,
    )
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="card_material",
        effect='"Tearlaments Kitkallos" + 1 "Tearlaments" monster',
    )
    confirm_effect(effect_id)

    context = build_known_facts_context(get_card_by_name("Tearlaments Rulkallos"))

    assert 'Card Material: "\\"Tearlaments Kitkallos\\" + 1 \\"Tearlaments\\" monster"' in context or (
        "Card Material:" in context and '"Tearlaments Kitkallos" + 1 "Tearlaments" monster' in context
    )
    assert "spell speed" not in context
    assert "activatable:" not in context


def test_build_known_facts_context_renders_summoning_condition_distinctly():
    from aijudge.db.cards_repo import get_card_by_name, insert_card
    from aijudge.db.effects_repo import confirm_effect, insert_pending_effect
    from aijudge.orchestration.preflight import build_known_facts_context

    card_id = insert_card(
        name="Elemental HERO Mudballman",
        card_text='"Elemental HERO Bubbleman" + "Elemental HERO Clayman"\nMust be Fusion Summoned...',
        card_type="Fusion Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="52031567",
        deterministic_parse_eligible=True,
    )
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="summoning_condition",
        effect="Must be Fusion Summoned and cannot be Special Summoned by other ways.",
    )
    confirm_effect(effect_id)

    context = build_known_facts_context(get_card_by_name("Elemental HERO Mudballman"))

    assert "Summoning Condition:" in context
    assert "Must be Fusion Summoned and cannot be Special Summoned by other ways." in context
    assert "spell speed" not in context
    assert "activatable:" not in context


def test_build_known_facts_context_mixes_card_material_with_normal_effects():
    from aijudge.db.cards_repo import get_card_by_name, insert_card
    from aijudge.db.effects_repo import confirm_effect, insert_pending_effect
    from aijudge.orchestration.preflight import build_known_facts_context

    card_id = insert_card(
        name="Tearlaments Rulkallos",
        card_text="...",
        card_type="Fusion Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="84330567",
        deterministic_parse_eligible=True,
    )
    material_id = insert_pending_effect(
        card_id=card_id,
        effect_type="card_material",
        effect='"Tearlaments Kitkallos" + 1 "Tearlaments" monster',
    )
    confirm_effect(material_id)
    quick_id = insert_pending_effect(
        card_id=card_id,
        effect_type="quick",
        effect="You can negate the activation, and if you do, destroy it.",
        activation_condition="When your opponent activates a card or effect... (Quick Effect)",
    )
    confirm_effect(quick_id)

    context = build_known_facts_context(get_card_by_name("Tearlaments Rulkallos"))
    lines = context.splitlines()

    assert len(lines) == 3  # header + material line + quick effect line
    assert "Card Material:" in lines[1]
    assert "effect type quick" in lines[2]
