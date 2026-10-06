import requests

from aijudge.ingestion.ygoresources_client import (
    fetch_card_name_index,
    fetch_rulings,
    invert_name_index,
    parse_referenced_ids,
    resolve_ruling_text,
    unresolved_display_text,
)
from tests.rulings_fixtures import (
    AMAZONESS_CALL_RULING_2017,
    DIGITRON_RULING_2019,
    NAME_INDEX_SLICE,
)


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


def _no_network(url, timeout):
    raise AssertionError(f"unexpected network call to {url}")


def test_parse_referenced_ids_returns_distinct_ids_in_first_appearance_order():
    assert parse_referenced_ids(AMAZONESS_CALL_RULING_2017) == [13174, 8963, 5505, 5682]


def test_parse_referenced_ids_ignores_text_without_numeric_placeholders():
    assert parse_referenced_ids("Q: Can I chain <<abc>> to it?\nA: No.") == []


def test_invert_name_index_maps_each_id_to_all_its_names():
    inverted = invert_name_index(NAME_INDEX_SLICE)
    assert inverted[13174] == ["Amazoness Call"]
    assert inverted[6845] == ["Cyber Angel - Benten", "Cyber Angel Benten"]


def test_fetch_card_name_index_downloads_and_inverts_the_english_index():
    def fake_get(url, timeout):
        assert url == "https://db.ygoresources.com/data/idx/card/name/en"
        return _FakeResponse(NAME_INDEX_SLICE)

    assert fetch_card_name_index(http_get=fake_get)[13192] == ["Digitron"]


def test_resolve_ruling_text_replaces_every_placeholder_with_its_name():
    index = invert_name_index(NAME_INDEX_SLICE)

    resolved, ids = resolve_ruling_text(AMAZONESS_CALL_RULING_2017, index, http_get=_no_network)

    assert ids == [13174, 8963, 5505, 5682]
    assert "<<" not in resolved
    assert resolved.startswith(
        "Q: I activate the second effect of Amazoness Call, targeting an Amazoness Queen on my field. "
        "If my opponent chains Enemy Controller and takes control of Amazoness Queen"
    )
    assert "using an effect such as Remove Brainwashing, etc." in resolved


def test_resolve_ruling_text_marks_an_id_missing_from_the_index_as_unknown():
    index = invert_name_index({"Digitron": [13192]})

    resolved, ids = resolve_ruling_text(DIGITRON_RULING_2019, index, http_get=_no_network)

    assert ids == [13489, 13034, 13192, 14436]
    assert resolved.startswith("Q: I Link Summon a [card #13489], using a [card #13034] and Digitron as materials.")


def test_resolve_ruling_text_asks_ygoresources_for_the_current_name_of_a_renamed_card():
    index = invert_name_index(NAME_INDEX_SLICE)

    def fake_get(url, timeout):
        assert url == "https://db.ygoresources.com/data/card/6845"
        return _FakeResponse({"cardData": {"en": {"name": "Cyber Angel Benten"}}})

    resolved, ids = resolve_ruling_text("Q: Does <<6845>> inflict damage?\nA: Yes.", index, http_get=fake_get)

    assert resolved == "Q: Does Cyber Angel Benten inflict damage?\nA: Yes."
    assert ids == [6845]


def test_resolve_ruling_text_marks_a_renamed_card_unknown_when_its_lookup_fails():
    index = invert_name_index(NAME_INDEX_SLICE)

    def failing_get(url, timeout):
        raise requests.ConnectionError("ygoresources unreachable")

    resolved, _ = resolve_ruling_text("Q: Does <<6845>> inflict damage?\nA: Yes.", index, http_get=failing_get)

    assert resolved == "Q: Does [card #6845] inflict damage?\nA: Yes."


def test_resolve_ruling_text_leaves_text_without_placeholders_unchanged():
    resolved, ids = resolve_ruling_text("Q: Can I chain <<abc>> to it?\nA: No.", {}, http_get=_no_network)
    assert resolved == "Q: Can I chain <<abc>> to it?\nA: No."
    assert ids == []


def test_unresolved_display_text_never_shows_a_bare_placeholder():
    assert unresolved_display_text("Q: Can <<13174>> target <<8963>>?") == "Q: Can [card #13174] target [card #8963]?"
