import pytest

from aijudge.embeddings.client import MockEmbeddingClient
from aijudge.llm.client import MockLLMClient
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


def test_build_tool_dispatch_has_only_active_tools():
    # search_rulebook and resolve_chain are temporarily disabled (pipeline instability).
    dispatch = build_tool_dispatch(MockLLMClient(), MockEmbeddingClient())
    assert set(dispatch.keys()) == {"lookup_card", "get_rulings"}


def test_build_tool_dispatch_lookup_card_skips_ingest_when_disabled(monkeypatch):
    from aijudge.orchestration import tools as tools_module

    monkeypatch.setattr(tools_module, "get_card_by_name", lambda name: None)

    seed_calls = []
    monkeypatch.setattr(tools_module, "seed_card", lambda *args, **kwargs: seed_calls.append((args, kwargs)))

    dispatch = build_tool_dispatch(MockLLMClient(), MockEmbeddingClient(), online_ingest_enabled=False)
    result = dispatch["lookup_card"]({"name": "Nonexistent Card"})

    assert result == {"found": False}
    assert seed_calls == []
