from datetime import date, datetime, timezone
from typing import Callable

from aijudge.db.cards_repo import insert_card
from aijudge.db.effects_repo import confirm_effect, insert_pending_effect
from aijudge.db.rulings_repo import insert_ruling
from aijudge.effect_parser.clause_splitter import resolve_effect_clauses
from aijudge.effect_parser.parser import classify_damage_step_category, classify_effect_type, parse_psct
from aijudge.effect_parser.review_agent import review_parsed_effect
from aijudge.effect_parser.sentence_splitter import extract_card_material
from aijudge.effect_parser.usage_limit import resolve_ambiguous_scope
from aijudge.ingestion.printing_eligibility import fetch_sets_index, is_deterministic_parse_eligible
from aijudge.ingestion.ygoprodeck_client import fetch_card
from aijudge.ingestion.ygoresources_client import fetch_rulings
from aijudge.llm.client import LLMClient
from aijudge.rules_engine.models import EffectType

# One random card per major card category (7 monster summoning mechanics,
# Quick-Play Spell, Continuous Trap, Counter Trap), each first printed
# between 2015-01-01 and 2025-12-31 (YGOPRODeck cardinfo.php's
# startdate/enddate/dateregion=tcg_date filter, then a random offset within
# the matching total) -- chosen for maximum structural scope (every
# summoning mechanic, both non-Normal-Trap subtypes, and a real Counter Trap
# for spell_speed_for's race=="Counter" case) rather than hand-picked for
# narrative familiarity like the previous list.
HAND_PICKED_CARDS: list[str] = [
    "Digitron",
    "Shafu, the Wheeled Mayakashi",
    "Cyber Angel Benten",
    "Masked HERO Anki",
    "Crystron Quariongandrax",
    "Super Quantal Mech Beast Magnaliger",
    "Powercode Talker",
    "Amazoness Call",
    "The Prime Monarch",
    "Cynet Conflict",
]


def seed_card(
    name: str,
    *,
    llm_client: LLMClient,
    fetch_card_fn: Callable[..., dict] = fetch_card,
    fetch_rulings_fn: Callable[..., list[dict]] = fetch_rulings,
    fetch_sets_index_fn: Callable[..., dict] = fetch_sets_index,
    field: str | None = None,
) -> str:
    card_data = fetch_card_fn(name, field=field) if field is not None else fetch_card_fn(name)
    card_type = card_data["type"]
    race = card_data.get("race")
    card_text = card_data["desc"]
    card_sets = card_data.get("card_sets") or []

    sets_index = fetch_sets_index_fn()
    eligible = is_deterministic_parse_eligible(card_sets, sets_index)

    card_id = insert_card(
        name=card_data["name"],
        card_text=card_text,
        card_type=card_type,
        race=race,
        source="ygoprodeck",
        fetched_at=datetime.now(timezone.utc).date(),
        ygoprodeck_id=str(card_data["id"]),
        deterministic_parse_eligible=eligible,
    )

    misc_info = card_data.get("misc_info") or [{}]
    konami_id = misc_info[0].get("konami_id")

    try:
        rulings = fetch_rulings_fn(konami_id)
    except Exception:
        rulings = []

    for ruling in rulings:
        raw_date = ruling.get("date")
        insert_ruling(
            card_id=card_id,
            ruling_text=ruling["text"],
            source="db.ygoresources",
            ruling_date=date.fromisoformat(raw_date) if raw_date else None,
        )

    if not eligible:
        _insert_unclassified(card_id, card_text)
        return card_id

    material_text, remainder = extract_card_material(card_text, card_type=card_type)
    if material_text is not None:
        material_id = insert_pending_effect(
            card_id=card_id,
            effect_type=EffectType.CARD_MATERIAL.value,
            effect=material_text,
            confidence_score=1.0,
        )
        # Materials are extracted by a fully deterministic rule with no LLM
        # judgment involved (unlike every other effect row, which goes
        # through review_parsed_effect first) -- confidence_score=1.0
        # already reflects that certainty, so confirm immediately rather
        # than leaving it pending with nothing to gate on.
        confirm_effect(material_id)
        if not remainder:
            return card_id
    else:
        remainder = card_text

    clauses, scopes = resolve_effect_clauses(llm_client, remainder)

    usage_limit_by_clause: dict[int, str] = {}
    for scope in scopes:
        indices = (
            resolve_ambiguous_scope(llm_client, usage_limit_text=scope.text, clauses=clauses)
            if scope.ambiguous
            else scope.applies_to
        )
        for index in indices:
            usage_limit_by_clause[index] = scope.text

    for index, effect_text in enumerate(clauses):
        usage_limit_text = usage_limit_by_clause.get(index)
        other_effects = None
        if usage_limit_text is not None:
            other_effects = [
                text
                for i, text in enumerate(clauses)
                if i != index and usage_limit_by_clause.get(i) == usage_limit_text
            ]

        _insert_parsed_clause(
            llm_client,
            card_id=card_id,
            card_type=card_type,
            race=race,
            effect_text=effect_text,
            usage_limit_text=usage_limit_text,
            other_effects=other_effects,
        )

    return card_id


def _insert_unclassified(card_id: str, card_text: str) -> None:
    insert_pending_effect(
        card_id=card_id,
        effect_type=EffectType.UNCLASSIFIED.value,
        effect=card_text,
        confidence_score=0.0,
    )


def _insert_parsed_clause(
    llm_client: LLMClient,
    *,
    card_id: str,
    card_type: str,
    race: str | None,
    effect_text: str,
    usage_limit_text: str | None,
    other_effects: list[str] | None,
) -> None:
    effect_type = classify_effect_type(effect_text, card_type=card_type, race=race)
    parsed = parse_psct(effect_text)
    damage_step_category = classify_damage_step_category(
        parsed.effect,
        activation_condition=parsed.activation_condition,
        effect_type=effect_type,
    )

    review = review_parsed_effect(
        llm_client,
        raw_text=effect_text,
        activation_condition=parsed.activation_condition,
        cost=parsed.cost,
        targeting=parsed.targeting,
        effect=parsed.effect,
        damage_step_category=damage_step_category,
        other_effects=other_effects,
    )

    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type=effect_type.value,
        effect=parsed.effect,
        activation_condition=parsed.activation_condition,
        cost=parsed.cost,
        targeting=parsed.targeting,
        has_target=(parsed.targeting is not None),
        confidence_score=review.confidence,
        damage_step_category=damage_step_category,
        usage_limit_text=usage_limit_text,
    )

    if review.auto_confirmed:
        confirm_effect(effect_id)


def run_seed(llm_client: LLMClient) -> list[str]:
    # fetch_sets_index is meant to be called once per ingestion run (not
    # once per card) and reused, since it's a large, slowly-changing
    # catalog -- build it once here rather than letting each seed_card call
    # fall back to its own default (which would re-fetch per card).
    sets_index = fetch_sets_index()
    return [
        seed_card(name, llm_client=llm_client, fetch_sets_index_fn=lambda: sets_index)
        for name in HAND_PICKED_CARDS
    ]
