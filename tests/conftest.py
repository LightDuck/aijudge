import os
from unittest import mock

import pytest
from dotenv import load_dotenv

load_dotenv()


@pytest.fixture(autouse=True)
def mock_db_if_unavailable(monkeypatch):
    """Auto-mock database functions for test cards when database is not running."""
    # Mock get_confirmed_effects to return fake data for test cards
    # This allows tests to run without a live database
    from aijudge.orchestration import preflight

    original_get_confirmed_effects = preflight.get_confirmed_effects

    def mock_get_confirmed_effects(card_id):
        # If card_id looks like a fake test ID (e.g., "abc"), return fake effect data
        if not _looks_like_real_uuid(card_id):
            return [
                {
                    "id": card_id,
                    "effect_type": "ignition",
                    "activation_condition": None,
                    "cost": None,
                    "targeting": None,
                    "has_target": False,
                    "effect": f"Test effect for {card_id}",
                    "damage_step_category": None,
                    "usage_limit_text": None,
                }
            ]
        # Otherwise, call the real function
        return original_get_confirmed_effects(card_id)

    monkeypatch.setattr(preflight, "get_confirmed_effects", mock_get_confirmed_effects)


def _looks_like_real_uuid(value):
    """Check if a value looks like a real UUID."""
    try:
        import uuid

        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError):
        return False
