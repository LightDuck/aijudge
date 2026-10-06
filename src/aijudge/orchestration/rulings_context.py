"""Deterministic selection and rendering of a question's stored rulings.

Given every card grounded for a question, picks which of their stored
ygoresources Q&As fit in the prompt -- rulings that mention another card in
the same question first, then newest first -- and renders them as one RULINGS
block. Rulings are included whole or not at all: a cut could drop the "A:"
half. Nothing here calls an LLM or the network.
"""

from dataclasses import dataclass, field

from aijudge.db.rulings_repo import get_rulings_for_card
from aijudge.ingestion.ygoresources_client import unresolved_display_text

DEFAULT_RULINGS_BUDGET_CHARS = 6000

RULINGS_HEADER = (
    "RULINGS (official Q&A from db.ygoresources -- do not contradict. A ruling applies only when the "
    "question's situation matches it. [card #N] marks a card whose name couldn't be resolved -- do not guess "
    "which card it is. Cite each ruling you rely on as ruling:<id>.):"
)


@dataclass
class RulingsGrounding:
    context: str = ""
    rulings_by_card_id: dict[str, list[dict]] = field(default_factory=dict)


def join_context(*parts: str) -> str:
    return "\n\n".join(part for part in parts if part)


def dedupe_cards_by_id(cards: list[dict]) -> list[dict]:
    """`cards` with repeats of an already-seen id dropped, first occurrence order kept."""
    seen: set[str] = set()
    unique = []
    for card in cards:
        if card["id"] not in seen:
            seen.add(card["id"])
            unique.append(card)
    return unique


def _display_text(ruling: dict) -> str:
    return ruling["ruling_text_resolved"] or unresolved_display_text(ruling["ruling_text"])


def render_ruling_line(card: dict, ruling: dict) -> str:
    date_text = ruling["ruling_date"].isoformat() if ruling["ruling_date"] else "undated"
    return f"- ruling:{ruling['id']} ({card['name']}, {date_text}): {_display_text(ruling)}"


def _konami_id(card: dict) -> int | None:
    value = card.get("ygoresources_id")
    return int(value) if value else None


def _rank_key(ruling: dict, other_konami_ids: set[int]) -> tuple:
    mentions_other_card = bool(set(ruling["referenced_konami_ids"]) & other_konami_ids)
    ruling_date = ruling["ruling_date"]
    return (
        not mentions_other_card,
        ruling_date is None,
        -ruling_date.toordinal() if ruling_date else 0,
        ruling["id"],
    )


def build_rulings_grounding(
    cards: list[dict], *, budget_chars: int = DEFAULT_RULINGS_BUDGET_CHARS
) -> RulingsGrounding:
    # A card listed twice would otherwise have its rulings deduped away under its own first copy.
    cards = dedupe_cards_by_id(cards)
    if not cards:
        return RulingsGrounding()

    konami_ids = {card["id"]: _konami_id(card) for card in cards}
    seen_texts: set[str] = set()
    stored_counts: dict[str, int] = {}
    candidates: dict[str, list[tuple[dict, str]]] = {}
    for card in cards:
        other_ids = {kid for cid, kid in konami_ids.items() if cid != card["id"] and kid is not None}
        stored = get_rulings_for_card(card["id"])
        stored_counts[card["id"]] = len(stored)
        ranked = []
        for ruling in sorted(stored, key=lambda r: _rank_key(r, other_ids)):
            if ruling["ruling_text"] in seen_texts:
                continue
            seen_texts.add(ruling["ruling_text"])
            ranked.append((ruling, render_ruling_line(card, ruling)))
        candidates[card["id"]] = ranked

    share = budget_chars // len(cards)
    chosen_ids: dict[str, set[str]] = {card["id"]: set() for card in cards}
    skipped: dict[str, list[tuple[dict, str]]] = {card["id"]: [] for card in cards}
    leftover = 0
    for card in cards:
        remaining = share
        for ruling, line in candidates[card["id"]]:
            if len(line) <= remaining:
                chosen_ids[card["id"]].add(ruling["id"])
                remaining -= len(line)
            else:
                skipped[card["id"]].append((ruling, line))
        leftover += remaining
    for card in cards:
        still_skipped = []
        for ruling, line in skipped[card["id"]]:
            if len(line) <= leftover:
                chosen_ids[card["id"]].add(ruling["id"])
                leftover -= len(line)
            else:
                still_skipped.append((ruling, line))
        skipped[card["id"]] = still_skipped

    lines = [RULINGS_HEADER]
    rulings_by_card_id: dict[str, list[dict]] = {}
    for card in cards:
        chosen = [(r, line) for r, line in candidates[card["id"]] if r["id"] in chosen_ids[card["id"]]]
        rulings_by_card_id[card["id"]] = [{**r, "display_text": _display_text(r)} for r, _ in chosen]
        lines.extend(line for _, line in chosen)
        not_shown = len(skipped[card["id"]])
        if not_shown:
            plural = "s" if not_shown != 1 else ""
            lines.append(f"- {card['name']}: {not_shown} more ruling{plural} not shown (context budget).")
        if stored_counts[card["id"]] == 0:
            if card.get("rulings_status") == "failed":
                lines.append(f"- {card['name']}: rulings could not be retrieved -- do not guess what they say.")
            else:
                lines.append(f"- {card['name']}: no official rulings on record.")
    return RulingsGrounding(context="\n".join(lines), rulings_by_card_id=rulings_by_card_id)


def attach_rulings(grounded_cards: list[dict], cards: list[dict], grounding: RulingsGrounding) -> list[dict]:
    """Copies of `grounded_cards` (built from `cards`, same order) carrying the
    rulings shown for each card and its rulings_status, so run_loop's
    update_signals can register them as citable."""
    return [
        {
            **grounded,
            "rulings": grounding.rulings_by_card_id.get(card["id"], []),
            "rulings_status": card.get("rulings_status"),
        }
        for grounded, card in zip(grounded_cards, cards)
    ]
