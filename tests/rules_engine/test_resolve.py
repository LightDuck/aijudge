import pytest

from aijudge.rules_engine.resolve import UnsupportedScenarioError, resolve_chain


def _effect(card_name, controller, effect_type="ignition", spell_speed=1, prevents_response=False):
    return {
        "card_name": card_name,
        "controller": controller,
        "effect_type": effect_type,
        "spell_speed": spell_speed,
        "prevents_response": prevents_response,
    }


def test_single_activate_step_resolves_alone():
    scenario = {
        "turn_player": "player_a",
        "steps": [{"kind": "activate", "effect": _effect("Card A", "player_a")}],
    }

    result = resolve_chain(scenario)

    assert result.violation is None
    assert [link.card_name for link in result.resolution_order] == ["Card A"]


def test_segoc_batch_then_activate_resolves_lifo():
    scenario = {
        "turn_player": "player_a",
        "steps": [
            {
                "kind": "segoc_batch",
                "effects": [
                    _effect("Turn Player's Trigger", "player_a"),
                    _effect("Opponent's Trigger", "player_b"),
                ],
            },
            {
                "kind": "activate",
                "effect": _effect("Quick Effect Response", "player_b", effect_type="quick", spell_speed=2),
            },
        ],
    }

    result = resolve_chain(scenario)

    assert result.violation is None
    assert [link.card_name for link in result.resolution_order] == [
        "Quick Effect Response",
        "Opponent's Trigger",
        "Turn Player's Trigger",
    ]


def test_illegal_activate_step_produces_violation_and_halts():
    scenario = {
        "turn_player": "player_a",
        "steps": [
            {"kind": "activate", "effect": _effect("Card A", "player_a")},
            {"kind": "activate", "effect": _effect("Card B", "player_b")},
        ],
    }

    result = resolve_chain(scenario)

    assert result.violation is not None
    assert result.violation.step_index == 1
    assert result.violation.reason == "priority_violation"
    assert [link.card_name for link in result.resolution_order] == ["Card A"]


def test_unrecognized_step_kind_raises_unsupported_scenario_error():
    scenario = {"turn_player": "player_a", "steps": [{"kind": "replay"}]}

    with pytest.raises(UnsupportedScenarioError):
        resolve_chain(scenario)


def test_activate_step_with_continuous_effect_type_is_not_activatable():
    scenario = {
        "turn_player": "player_a",
        "steps": [{"kind": "activate", "effect": _effect("Skill Drain", "player_a", effect_type="continuous")}],
    }

    result = resolve_chain(scenario)

    assert result.violation is not None
    assert result.violation.step_index == 0
    assert result.violation.reason == "not_activatable"
    assert result.resolution_order == []
