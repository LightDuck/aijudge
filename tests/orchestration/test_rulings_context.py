from datetime import date

import pytest

from aijudge.ingestion.ygoresources_client import invert_name_index, parse_referenced_ids, resolve_ruling_text
from aijudge.orchestration import rulings_context
from aijudge.orchestration.rulings_context import (
    RULINGS_HEADER,
    RulingsGrounding,
    attach_rulings,
    build_rulings_grounding,
    join_context,
)
from tests.rulings_fixtures import (
    AMAZONESS_CALL_RULING_2017,
    AMAZONESS_CALL_RULING_2025,
    AMAZONESS_CALL_RULING_2026,
    DIGITRON_RULING_2019,
    NAME_INDEX_SLICE,
)

AMAZONESS_CALL = {
    "id": "card-amazoness-call",
    "name": "Amazoness Call",
    "ygoresources_id": "13174",
    "rulings_status": "fetched",
}
AMAZONESS_QUEEN = {
    "id": "card-amazoness-queen",
    "name": "Amazoness Queen",
    "ygoresources_id": "8963",
    "rulings_status": "fetched",
}
DIGITRON = {"id": "card-digitron", "name": "Digitron", "ygoresources_id": "13192", "rulings_status": "fetched"}


_NAMES = invert_name_index(NAME_INDEX_SLICE)


def _ruling(ruling_id, raw_text, ruling_date, resolve=True):
    return {
        "id": ruling_id,
        "ruling_text": raw_text,
        "source": "db.ygoresources",
        "ruling_date": ruling_date,
        "ruling_text_resolved": resolve_ruling_text(raw_text, _NAMES)[0] if resolve else None,
        "referenced_konami_ids": parse_referenced_ids(raw_text),
    }


# 2026 and 2017 reference Amazoness Queen (8963); the 2025 ruling does not.
CALL_2017 = _ruling("r-2017", AMAZONESS_CALL_RULING_2017, date(2017, 7, 22))
CALL_2026 = _ruling("r-2026", AMAZONESS_CALL_RULING_2026, date(2026, 1, 1))
CALL_NO_QUEEN = _ruling("r-2025", AMAZONESS_CALL_RULING_2025, date(2025, 7, 13))
DIGITRON_2019 = _ruling("r-dig", DIGITRON_RULING_2019, date(2019, 3, 23), resolve=False)


@pytest.fixture
def stored(monkeypatch):
    by_card = {}
    monkeypatch.setattr(rulings_context, "get_rulings_for_card", lambda card_id: list(by_card.get(card_id, [])))
    return by_card


def _ids(grounding, card):
    return [r["id"] for r in grounding.rulings_by_card_id[card["id"]]]


def test_no_cards_gives_an_empty_grounding(stored):
    assert build_rulings_grounding([]) == RulingsGrounding()


def test_newest_first_when_no_other_card_is_in_the_question(stored):
    stored[AMAZONESS_CALL["id"]] = [CALL_2017, CALL_NO_QUEEN, CALL_2026]

    grounding = build_rulings_grounding([AMAZONESS_CALL])

    assert _ids(grounding, AMAZONESS_CALL) == ["r-2026", "r-2025", "r-2017"]
    assert grounding.context.startswith(RULINGS_HEADER)
    assert "- ruling:r-2026 (Amazoness Call, 2026-01-01): Q: I activate the" in grounding.context


def test_rulings_that_mention_another_card_in_the_question_come_first(stored):
    stored[AMAZONESS_CALL["id"]] = [CALL_NO_QUEEN, CALL_2017, CALL_2026]

    grounding = build_rulings_grounding([AMAZONESS_CALL, AMAZONESS_QUEEN])

    # Both Queen-referencing rulings (newest first) beat the newer non-Queen one.
    assert _ids(grounding, AMAZONESS_CALL) == ["r-2026", "r-2017", "r-2025"]


def test_undated_rulings_sort_last(stored):
    undated = {**CALL_2026, "id": "r-undated", "ruling_text": "Q: undated\nA: yes", "ruling_date": None}
    stored[AMAZONESS_CALL["id"]] = [undated, CALL_2017]

    grounding = build_rulings_grounding([AMAZONESS_CALL])

    assert _ids(grounding, AMAZONESS_CALL) == ["r-2017", "r-undated"]
    assert "(Amazoness Call, undated)" in grounding.context


def test_budget_skips_a_ruling_that_does_not_fit_and_tries_the_next(stored):
    long_ruling = {**CALL_NO_QUEEN, "ruling_date": date(2026, 1, 1)}  # newest, so tried first
    stored[AMAZONESS_CALL["id"]] = [long_ruling, CALL_2017]
    short_line = rulings_context.render_ruling_line(AMAZONESS_CALL, CALL_2017)

    grounding = build_rulings_grounding([AMAZONESS_CALL], budget_chars=len(short_line) + 10)

    assert _ids(grounding, AMAZONESS_CALL) == ["r-2017"]
    assert "- Amazoness Call: 1 more ruling not shown (context budget)." in grounding.context
    assert long_ruling["ruling_text_resolved"][:60] not in grounding.context  # never truncated into the block


def test_unused_share_is_pooled_for_another_cards_skipped_ruling(stored):
    stored[AMAZONESS_CALL["id"]] = [CALL_2026, CALL_2017]
    stored[DIGITRON["id"]] = []
    line_2026 = rulings_context.render_ruling_line(AMAZONESS_CALL, CALL_2026)
    line_2017 = rulings_context.render_ruling_line(AMAZONESS_CALL, CALL_2017)
    # Each card's share fits only one Amazoness Call ruling; Digitron's unused
    # share must carry the second one.
    budget = 2 * max(len(line_2026), len(line_2017))

    grounding = build_rulings_grounding([AMAZONESS_CALL, DIGITRON], budget_chars=budget)

    assert _ids(grounding, AMAZONESS_CALL) == ["r-2026", "r-2017"]
    assert "not shown" not in grounding.context


def test_a_skipped_ruling_the_pooled_pass_cannot_fit_is_still_reported_not_shown(stored):
    stored[AMAZONESS_CALL["id"]] = [CALL_2026, CALL_2017]
    stored[DIGITRON["id"]] = [DIGITRON_2019]
    line_2026 = rulings_context.render_ruling_line(AMAZONESS_CALL, CALL_2026)
    line_2017 = rulings_context.render_ruling_line(AMAZONESS_CALL, CALL_2017)
    line_digitron = rulings_context.render_ruling_line(DIGITRON, DIGITRON_2019)
    # Each share fits exactly one ruling; what's left over pooled can't fit the 2017 one.
    share = max(len(line_2026), len(line_digitron))
    assert 2 * share - len(line_2026) - len(line_digitron) < len(line_2017)

    grounding = build_rulings_grounding([AMAZONESS_CALL, DIGITRON], budget_chars=2 * share)

    assert _ids(grounding, AMAZONESS_CALL) == ["r-2026"]
    assert _ids(grounding, DIGITRON) == ["r-dig"]
    assert "- Amazoness Call: 1 more ruling not shown (context budget)." in grounding.context


def test_a_card_listed_twice_keeps_its_rulings_and_renders_them_once(stored):
    stored[AMAZONESS_CALL["id"]] = [CALL_2017]

    grounding = build_rulings_grounding([AMAZONESS_CALL, dict(AMAZONESS_CALL)])

    assert _ids(grounding, AMAZONESS_CALL) == ["r-2017"]
    assert grounding.context.count("- ruling:r-2017 ") == 1
    assert "no official rulings on record" not in grounding.context


def test_a_qa_stored_under_two_grounded_cards_is_rendered_once(stored):
    stored[AMAZONESS_CALL["id"]] = [CALL_2017]
    stored[AMAZONESS_QUEEN["id"]] = [{**CALL_2017, "id": "r-2017-queen-copy"}]

    grounding = build_rulings_grounding([AMAZONESS_CALL, AMAZONESS_QUEEN])

    assert _ids(grounding, AMAZONESS_CALL) == ["r-2017"]
    assert _ids(grounding, AMAZONESS_QUEEN) == []
    assert "Amazoness Queen: no official rulings on record" not in grounding.context


def test_a_card_with_no_rulings_is_reported_as_having_none(stored):
    grounding = build_rulings_grounding([DIGITRON])
    assert "- Digitron: no official rulings on record." in grounding.context


def test_a_failed_fetch_is_reported_as_unretrievable(stored):
    grounding = build_rulings_grounding([{**DIGITRON, "rulings_status": "failed"}])
    assert "- Digitron: rulings could not be retrieved -- do not guess what they say." in grounding.context


def test_a_card_without_a_ygoresources_id_is_reported_as_unavailable(stored):
    grounding = build_rulings_grounding([{**DIGITRON, "ygoresources_id": None, "rulings_status": "no_konami_id"}])

    assert (
        "- Digitron: rulings unavailable for this card (no ygoresources id) -- do not guess what they say."
        in grounding.context
    )
    assert "no official rulings on record" not in grounding.context


def test_a_pre_backfill_card_renders_unknown_card_markers_without_crashing(stored):
    legacy_card = {**DIGITRON, "ygoresources_id": None, "rulings_status": None}
    stored[DIGITRON["id"]] = [DIGITRON_2019]

    grounding = build_rulings_grounding([legacy_card, AMAZONESS_CALL])

    assert "Q: I Link Summon a [card #13489], using a [card #13034] and [card #13192]" in grounding.context
    assert "<<" not in grounding.context
    [ruling] = grounding.rulings_by_card_id[DIGITRON["id"]]
    assert ruling["display_text"].startswith("Q: I Link Summon a [card #13489]")


def test_the_header_explains_unresolved_card_markers():
    assert "[card #N] marks a card whose name couldn't be resolved -- do not guess which card it is." in RULINGS_HEADER


def test_attach_rulings_adds_rulings_and_status_to_each_grounded_card(stored):
    stored[AMAZONESS_CALL["id"]] = [CALL_2017]
    grounding = build_rulings_grounding([AMAZONESS_CALL])
    grounded = [{"found": True, "id": AMAZONESS_CALL["id"], "name": "Amazoness Call", "confirmed_effects": []}]

    [attached] = attach_rulings(grounded, [AMAZONESS_CALL], grounding)

    assert [r["id"] for r in attached["rulings"]] == ["r-2017"]
    assert attached["rulings_status"] == "fetched"
    assert "rulings" not in grounded[0]  # the input isn't mutated


def test_join_context_skips_empty_parts():
    assert join_context("KNOWN FACTS", "", "RULINGS") == "KNOWN FACTS\n\nRULINGS"
    assert join_context("", "") == ""
