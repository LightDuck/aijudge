import pytest

from aijudge.ingestion.ygoprodeck_client import AmbiguousCardError, CardNotFoundError, fetch_card


class _FakeResponse:
    def __init__(self, status_code: int, json_body: dict) -> None:
        self.status_code = status_code
        self._json_body = json_body

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._json_body


def _card(name: str, **extra) -> dict:
    return {"name": name, "type": "Quick-Play Spell", **extra}


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


def test_fetch_card_falls_back_to_fname_when_name_not_found():
    def fake_get(url, params, timeout):
        if "name" in params:
            return _FakeResponse(400, {})
        assert params == {"fname": "Salamangreat", "misc": "yes"}
        return _FakeResponse(200, {"data": [_card("Salamangreat Almiraj")]})

    card = fetch_card("Salamangreat", http_get=fake_get)

    assert card["name"] == "Salamangreat Almiraj"


def test_fetch_card_falls_back_to_archetype_when_name_and_fname_not_found():
    calls = []

    def fake_get(url, params, timeout):
        calls.append(dict(params))
        if "archetype" in params:
            return _FakeResponse(200, {"data": [_card("Solo Match")]})
        return _FakeResponse(400, {})

    card = fetch_card("Salamangreat", http_get=fake_get)

    assert card["name"] == "Solo Match"
    assert [set(c) for c in calls] == [{"name", "misc"}, {"fname", "misc"}, {"archetype", "misc"}]


def test_fetch_card_falls_back_to_id_as_last_resort():
    def fake_get(url, params, timeout):
        if "id" in params:
            return _FakeResponse(200, {"data": [_card("Ash Blossom & Joyous Spring")]})
        return _FakeResponse(400, {})

    card = fetch_card("14558127", http_get=fake_get)

    assert card["name"] == "Ash Blossom & Joyous Spring"


def test_fetch_card_raises_card_not_found_when_all_fields_exhausted():
    def fake_get(url, params, timeout):
        return _FakeResponse(400, {})

    with pytest.raises(CardNotFoundError):
        fetch_card("Totally Not A Card", http_get=fake_get)


def test_fetch_card_raises_ambiguous_card_error_on_multiple_matches():
    def fake_get(url, params, timeout):
        if "archetype" in params:
            return _FakeResponse(200, {"data": [_card("Salamangreat Almiraj"), _card("Salamangreat Balelynx")]})
        return _FakeResponse(400, {})

    with pytest.raises(AmbiguousCardError):
        fetch_card("Salamangreat", http_get=fake_get)


def test_fetch_card_with_explicit_field_skips_priority_chain():
    calls = []

    def fake_get(url, params, timeout):
        calls.append(dict(params))
        return _FakeResponse(200, {"data": [_card("Solo Match")]})

    card = fetch_card("Salamangreat", field="archetype", http_get=fake_get)

    assert card["name"] == "Solo Match"
    assert calls == [{"archetype": "Salamangreat", "misc": "yes"}]


def test_fetch_card_with_explicit_field_raises_not_found_without_trying_others():
    calls = []

    def fake_get(url, params, timeout):
        calls.append(dict(params))
        return _FakeResponse(400, {})

    with pytest.raises(CardNotFoundError):
        fetch_card("Nonexistent", field="name", http_get=fake_get)

    assert calls == [{"name": "Nonexistent", "misc": "yes"}]


def test_fetch_card_extracts_konami_id_from_misc_info():
    def fake_get(url, params, timeout):
        assert params["misc"] == "yes"
        return _FakeResponse(
            200,
            {"data": [_card("Galaxy-Eyes Photon Dragon", misc_info=[{"konami_id": 9729}])]},
        )

    card = fetch_card("Galaxy-Eyes Photon Dragon", http_get=fake_get)

    assert card["misc_info"][0]["konami_id"] == 9729
