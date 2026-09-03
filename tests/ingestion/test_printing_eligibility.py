from datetime import date


def test_eligible_via_original_printing():
    from aijudge.ingestion.printing_eligibility import is_deterministic_parse_eligible

    card_sets = [{"set_name": "Darkwing Blast"}]
    sets_index = {"Darkwing Blast": date(2022, 10, 20)}

    assert is_deterministic_parse_eligible(card_sets, sets_index) is True


def test_eligible_via_reprint_only():
    """Elemental HERO Mudballman: original 2006 printing predates the
    cutoff, but a 2011-10-04 reprint doesn't."""
    from aijudge.ingestion.printing_eligibility import is_deterministic_parse_eligible

    card_sets = [
        {"set_name": "McDonald's Promotional Cards 2"},
        {"set_name": "Legendary Collection 2"},
        {"set_name": "Ra Yellow Mega Pack"},
    ]
    sets_index = {
        "McDonald's Promotional Cards 2": date(2006, 12, 22),
        "Legendary Collection 2": date(2011, 10, 4),
        "Ra Yellow Mega Pack": date(2012, 2, 17),
    }

    assert is_deterministic_parse_eligible(card_sets, sets_index) is True


def test_ineligible_when_every_printing_predates_cutoff():
    from aijudge.ingestion.printing_eligibility import is_deterministic_parse_eligible

    card_sets = [{"set_name": "Old Set"}]
    sets_index = {"Old Set": date(2005, 1, 1)}

    assert is_deterministic_parse_eligible(card_sets, sets_index) is False


def test_ineligible_at_exact_cutoff_minus_one_day():
    from aijudge.ingestion.printing_eligibility import is_deterministic_parse_eligible

    card_sets = [{"set_name": "Edge Set"}]
    sets_index = {"Edge Set": date(2011, 7, 7)}

    assert is_deterministic_parse_eligible(card_sets, sets_index) is False


def test_eligible_at_exact_cutoff_date():
    from aijudge.ingestion.printing_eligibility import is_deterministic_parse_eligible

    card_sets = [{"set_name": "Cutoff Set"}]
    sets_index = {"Cutoff Set": date(2011, 7, 8)}

    assert is_deterministic_parse_eligible(card_sets, sets_index) is True


def test_ineligible_when_set_missing_from_index():
    from aijudge.ingestion.printing_eligibility import is_deterministic_parse_eligible

    assert is_deterministic_parse_eligible([{"set_name": "Unknown Set"}], {}) is False


def test_ineligible_with_no_card_sets():
    from aijudge.ingestion.printing_eligibility import is_deterministic_parse_eligible

    assert is_deterministic_parse_eligible([], {"Some Set": date(2020, 1, 1)}) is False


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_fetch_sets_index_builds_name_to_date_map():
    from aijudge.ingestion.printing_eligibility import fetch_sets_index

    payload = [
        {"set_name": "Legendary Collection 2", "set_code": "LCGX", "tcg_date": "2011-10-04"},
        {"set_name": "Ra Yellow Mega Pack", "set_code": "RYMP", "tcg_date": "2012-02-17"},
    ]
    calls = []

    def fake_http_get(url, timeout=None):
        calls.append(url)
        return _FakeResponse(payload)

    index = fetch_sets_index(http_get=fake_http_get)

    assert index == {
        "Legendary Collection 2": date(2011, 10, 4),
        "Ra Yellow Mega Pack": date(2012, 2, 17),
    }
    assert calls == ["https://db.ygoprodeck.com/api/v7/cardsets.php"]


def test_fetch_sets_index_skips_rows_missing_tcg_date():
    from aijudge.ingestion.printing_eligibility import fetch_sets_index

    payload = [
        {"set_name": "OCG-Only Set", "set_code": "OCG1"},
        {"set_name": "Dated Set", "set_code": "DS1", "tcg_date": "2015-05-05"},
    ]

    index = fetch_sets_index(http_get=lambda url, timeout=None: _FakeResponse(payload))

    assert index == {"Dated Set": date(2015, 5, 5)}
