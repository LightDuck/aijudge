from aijudge.ingestion.ygoresources_client import fetch_rulings


class _FakeResponse:
    def __init__(self, json_body: dict) -> None:
        self._json_body = json_body

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._json_body


def test_fetch_rulings_returns_text_and_date_pairs():
    def fake_get(url, params, timeout):
        return _FakeResponse({"rulings": [{"text": "Ash Blossom cannot respond to itself.", "date": "2021-01-01"}]})

    rulings = fetch_rulings("Ash Blossom & Joyous Spring", http_get=fake_get)

    assert rulings == [{"text": "Ash Blossom cannot respond to itself.", "date": "2021-01-01"}]


def test_fetch_rulings_returns_empty_list_when_none_exist():
    def fake_get(url, params, timeout):
        return _FakeResponse({"rulings": []})

    assert fetch_rulings("No Rulings Card", http_get=fake_get) == []
