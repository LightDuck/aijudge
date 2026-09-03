from datetime import date

PSCT_CUTOFF_DATE = date(2011, 7, 8)


def is_deterministic_parse_eligible(card_sets: list[dict], sets_index: dict[str, date]) -> bool:
    """Whether any printing of this card is dated on/after PSCT_CUTOFF_DATE.

    Checks every entry in `card_sets` (as returned by YGOPRODeck's
    cardinfo.php), not just the first -- a card's original printing can
    predate PSCT while a later reprint brings its text current (see
    Elemental HERO Mudballman in the design spec's worked examples).
    """
    for card_set in card_sets:
        set_name = card_set.get("set_name")
        if set_name is None:
            continue
        printed_date = sets_index.get(set_name)
        if printed_date is not None and printed_date >= PSCT_CUTOFF_DATE:
            return True
    return False
