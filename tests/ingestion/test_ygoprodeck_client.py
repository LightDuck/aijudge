import pytest

from aijudge.ingestion.ygoprodeck_client import CardNotFoundError, fetch_card


class _FakeResponse:
    def __init__(self, status_code: int, json_body: dict) -> None:
        self.status_code = status_code
        self._json_body = json_body

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._json_body


def test_fetch_card_returns_first_match():
    def fake_get(url, params, timeout):
        return _FakeResponse(200, {"data": [{"name": params["name"], "type": "Quick-Play Spell"}]})

    card = fetch_card("Called by the Grave", http_get=fake_get)

    assert card["name"] == "Called by the Grave"
    assert card["type"] == "Quick-Play Spell"


def test_fetch_card_raises_card_not_found_on_400():
    def fake_get(url, params, timeout):
        return _FakeResponse(400, {})

    with pytest.raises(CardNotFoundError):
        fetch_card("Nonexistent Card", http_get=fake_get)
