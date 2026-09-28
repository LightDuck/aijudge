import pytest

from aijudge.db.cards_repo import normalize_passcode

# Cynet Conflict's printed passcode is 07403341; YGOPRODeck's API returns it as
# the int 7403341, dropping the leading zero.


@pytest.mark.parametrize("passcode", ["07403341", "7403341", 7403341])
def test_restores_the_printed_eight_digit_passcode(passcode):
    assert normalize_passcode(passcode) == "07403341"


def test_leaves_a_full_eight_digit_passcode_unchanged():
    # Effect Veiler
    assert normalize_passcode(97268402) == "97268402"


def test_returns_a_non_digit_query_unchanged():
    assert normalize_passcode("Cynet Conflict") == "Cynet Conflict"
