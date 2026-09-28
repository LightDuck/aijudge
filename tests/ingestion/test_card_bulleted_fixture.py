import json

import pytest

from aijudge.ingestion.card_bulleted_seed import DEFAULT_FIXTURE_PATH

_LEGEND_CODES = {"A1", "A2", "B1", "B2", "C", "D1", "D2", "E1", "E2", "F", "G", "H", "Z"}


@pytest.fixture(scope="module")
def entries():
    return json.loads(DEFAULT_FIXTURE_PATH.read_text(encoding="utf-8"))


def test_fixture_has_every_reviewed_card_except_skill_cards(entries):
    # 984 reviewed cards minus the 4 Speed Duel Skill Cards (see below).
    assert len(entries) == 980


def test_speed_duel_skill_cards_are_excluded(entries):
    # Skill Cards have no printed passcode (YGOPRODeck gives them 9-digit ids)
    # and belong to Speed Duel, not the TCG format AIJudge rules on.
    skill_cards = {"Behold, Gate Guardian!", "Forged Steel", "Vampiric Aristocracy", "Zombie Master (Skill Card)"}
    assert not skill_cards & {e["name"] for e in entries}


def test_every_entry_has_exactly_the_fixture_fields(entries):
    assert all(set(e) == {"ygoprodeck_id", "name", "category_code", "reason"} for e in entries)


def test_passcodes_are_unique_eight_digit_strings(entries):
    passcodes = [e["ygoprodeck_id"] for e in entries]
    assert all(isinstance(p, str) and len(p) == 8 and p.isdigit() for p in passcodes)
    assert len(set(passcodes)) == len(passcodes)


def test_names_are_unique(entries):
    assert len({e["name"] for e in entries}) == len(entries)


def test_every_category_code_is_in_the_legend(entries):
    assert {e["category_code"] for e in entries} <= _LEGEND_CODES


def test_moved_cards_have_no_reason(entries):
    # The 113 cards the user moved during review carry a first-sort reason that
    # argues for the category they were moved away from, so it isn't imported.
    assert sum(e["reason"] is None for e in entries) == 113


def test_no_reason_keeps_the_stale_earlier_label_suffix(entries):
    assert not any("differs from your earlier label" in (e["reason"] or "") for e in entries)


def test_entries_are_sorted_by_name(entries):
    names = [e["name"] for e in entries]
    assert names == sorted(names)
