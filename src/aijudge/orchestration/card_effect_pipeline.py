from dataclasses import dataclass, field
from typing import Callable

from aijudge.llm.client import LLMClient
from aijudge.orchestration.card_resolution import CardResolution, resolve_named_cards
from aijudge.orchestration.extraction import extract_card_names
from aijudge.orchestration.preflight import build_grounded_result, build_known_facts_context
from aijudge.orchestration import rulings_context
from aijudge.orchestration.rulings_context import RulingsGrounding, attach_rulings


@dataclass
class PipelineResolution:
    supported: bool
    context: str = ""
    grounded_cards: list[dict] = field(default_factory=list)


def build_pipeline_context(resolutions: list[CardResolution], *, rulings_context: str = "") -> str:
    known_facts_blocks = []
    for resolution in resolutions:
        if resolution.status == "resolved":
            block = build_known_facts_context(resolution.card)
            if block:
                known_facts_blocks.append(block)

    failures = [r for r in resolutions if r.status != "resolved"]
    parts = list(known_facts_blocks)
    if rulings_context:
        parts.append(rulings_context)
    if failures:
        failure_lines = [
            "LOOKUP FAILURES (deterministic -- report these to the user, do not guess their effects):"
        ]
        for r in failures:
            failure_lines.append(f'- "{r.name}": {r.status}')
        parts.append("\n".join(failure_lines))
    return "\n\n".join(parts)


def resolve_card_effect_question(
    question: str,
    *,
    llm_client: LLMClient,
    online_ingest_enabled: bool = True,
    on_ingest_start: Callable[[str], None] | None = None,
    extract_card_names_fn: Callable[..., list[str]] = extract_card_names,
    resolve_named_cards_fn: Callable[..., list[CardResolution]] = resolve_named_cards,
    build_pipeline_context_fn: Callable[..., str] = build_pipeline_context,
    build_grounded_result_fn: Callable[[dict], dict] = build_grounded_result,
    build_rulings_grounding_fn: Callable[[list[dict]], RulingsGrounding] | None = None,
) -> PipelineResolution:
    names = extract_card_names_fn(question, llm_client=llm_client)
    if not names:
        return PipelineResolution(supported=False)

    resolutions = resolve_named_cards_fn(
        names,
        llm_client=llm_client,
        online_ingest_enabled=online_ingest_enabled,
        on_ingest_start=on_ingest_start,
    )
    build_rulings_grounding_fn = build_rulings_grounding_fn or rulings_context.build_rulings_grounding
    resolved_cards = [r.card for r in resolutions if r.status == "resolved"]
    grounding = build_rulings_grounding_fn(resolved_cards)
    return PipelineResolution(
        supported=True,
        context=build_pipeline_context_fn(resolutions, rulings_context=grounding.context),
        grounded_cards=attach_rulings(
            [build_grounded_result_fn(card) for card in resolved_cards], resolved_cards, grounding
        ),
    )
