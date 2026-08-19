import pytest

from aijudge.rules_engine.models import SpellSpeed
from aijudge.rules_engine.timing import TimingEventType, check_missing_timing


def test_activating_at_the_very_next_opportunity_does_not_miss_timing():
    assert (
        check_missing_timing(
            trigger_step=3,
            current_step=3,
            last_event_type=TimingEventType.RESOLVED,
            spell_speed=SpellSpeed.NORMAL,
        )
        is False
    )


def test_any_intervening_step_means_timing_is_missed():
    assert (
        check_missing_timing(
            trigger_step=3,
            current_step=4,
            last_event_type=TimingEventType.RESOLVED,
            spell_speed=SpellSpeed.NORMAL,
        )
        is True
    )


def test_current_step_cannot_precede_trigger_step():
    with pytest.raises(ValueError):
        check_missing_timing(
            trigger_step=3,
            current_step=2,
            last_event_type=TimingEventType.RESOLVED,
            spell_speed=SpellSpeed.NORMAL,
        )


def test_spell_speed_1_can_trigger_off_a_resolved_event_at_the_exact_step():
    assert (
        check_missing_timing(
            3, 3, last_event_type=TimingEventType.RESOLVED, spell_speed=SpellSpeed.NORMAL
        )
        is False
    )


def test_spell_speed_1_can_trigger_off_a_game_action_event_at_the_exact_step():
    assert (
        check_missing_timing(
            3, 3, last_event_type=TimingEventType.GAME_ACTION, spell_speed=SpellSpeed.NORMAL
        )
        is False
    )


def test_spell_speed_1_cannot_trigger_off_a_bare_activation_at_the_exact_step():
    assert (
        check_missing_timing(
            3, 3, last_event_type=TimingEventType.ACTIVATED, spell_speed=SpellSpeed.NORMAL
        )
        is True
    )


def test_spell_speed_2_can_trigger_off_an_activation_at_the_exact_step():
    assert (
        check_missing_timing(
            3, 3, last_event_type=TimingEventType.ACTIVATED, spell_speed=SpellSpeed.QUICK
        )
        is False
    )


def test_spell_speed_2_cannot_trigger_off_a_resolved_event_at_the_exact_step():
    assert (
        check_missing_timing(
            3, 3, last_event_type=TimingEventType.RESOLVED, spell_speed=SpellSpeed.QUICK
        )
        is True
    )
