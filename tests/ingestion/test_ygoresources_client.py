from aijudge.ingestion.ygoresources_client import fetch_rulings


class _FakeResponse:
    def __init__(self, json_body: dict) -> None:
        self._json_body = json_body

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._json_body


def test_fetch_rulings_returns_empty_list_when_konami_id_is_none():
    def fake_get(url, timeout):
        raise AssertionError("should not make a network call without a konami_id")

    assert fetch_rulings(None, http_get=fake_get) == []


def test_fetch_rulings_returns_empty_list_when_card_has_no_qa_entries():
    def fake_get(url, timeout):
        assert url == "https://db.ygoresources.com/data/card/9729"
        return _FakeResponse({"qaIndex": []})

    assert fetch_rulings(9729, http_get=fake_get) == []


def test_fetch_rulings_fetches_each_qa_entry_for_the_card():
    def fake_get(url, timeout):
        if url == "https://db.ygoresources.com/data/card/9729":
            return _FakeResponse({"qaIndex": [7410]})
        assert url == "https://db.ygoresources.com/data/qa/7410"
        return _FakeResponse(
            {
                "qaData": {
                    "en": {
                        "question": "Does this card negate the activation?",
                        "answer": "Yes, it negates the activation.",
                        "thisSrc": {"date": "2016-06-30"},
                    }
                }
            }
        )

    rulings = fetch_rulings(9729, http_get=fake_get)

    assert rulings == [
        {
            "text": "Q: Does this card negate the activation?\nA: Yes, it negates the activation.",
            "date": "2016-06-30",
        }
    ]


def test_fetch_rulings_skips_qa_entries_without_an_english_translation():
    def fake_get(url, timeout):
        if url == "https://db.ygoresources.com/data/card/9729":
            return _FakeResponse({"qaIndex": [7410]})
        return _FakeResponse({"qaData": {"ja": {"question": "...", "answer": "..."}}})

    assert fetch_rulings(9729, http_get=fake_get) == []


def test_fetch_rulings_omits_date_when_source_date_is_unknown():
    def fake_get(url, timeout):
        if url == "https://db.ygoresources.com/data/card/9729":
            return _FakeResponse({"qaIndex": [7410]})
        return _FakeResponse(
            {
                "qaData": {
                    "en": {
                        "question": "Q",
                        "answer": "A",
                        "thisSrc": {"date": "????-??-??"},
                    }
                }
            }
        )

    rulings = fetch_rulings(9729, http_get=fake_get)

    assert rulings == [{"text": "Q: Q\nA: A", "date": None}]
