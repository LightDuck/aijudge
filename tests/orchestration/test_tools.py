import pytest

from aijudge.embeddings.client import MockEmbeddingClient
from aijudge.orchestration.tools import build_tool_dispatch, resolve_chain
from aijudge.rules_engine.resolve import UnsupportedScenarioError


def test_resolve_chain_wrapper_returns_plain_dict():
    scenario = {
        "turn_player": "player_a",
        "steps": [
            {
                "kind": "activate",
                "effect": {
                    "card_name": "Card A",
                    "controller": "player_a",
                    "effect_type": "ignition",
                    "spell_speed": 1,
                    "prevents_response": False,
                },
            }
        ],
    }

    result = resolve_chain(scenario)

    assert result == {
        "resolution_order": [{"link_number": 1, "card_name": "Card A", "controller": "player_a"}],
        "violation": None,
    }


def test_resolve_chain_wrapper_propagates_unsupported_scenario_error():
    scenario = {"turn_player": "player_a", "steps": [{"kind": "replay"}]}

    with pytest.raises(UnsupportedScenarioError):
        resolve_chain(scenario)


def test_build_tool_dispatch_has_all_four_tools():
    dispatch = build_tool_dispatch(MockEmbeddingClient())
    assert set(dispatch.keys()) == {"lookup_card", "get_rulings", "search_rulebook", "resolve_chain"}
