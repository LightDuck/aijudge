import pytest

from aijudge.rules_engine.timing import check_missing_timing


def test_activating_at_the_very_next_opportunity_does_not_miss_timing():
    assert check_missing_timing(trigger_step=3, current_step=3) is False


def test_any_intervening_step_means_timing_is_missed():
    assert check_missing_timing(trigger_step=3, current_step=4) is True


def test_current_step_cannot_precede_trigger_step():
    with pytest.raises(ValueError):
        check_missing_timing(trigger_step=3, current_step=2)
