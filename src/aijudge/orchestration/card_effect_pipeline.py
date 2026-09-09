from dataclasses import dataclass, field
from typing import Callable

from aijudge.llm.client import LLMClient
from aijudge.orchestration.card_resolution import CardResolution, resolve_named_cards
from aijudge.orchestration.extraction import extract_card_names
from aijudge.orchestration.preflight import build_grounded_result, build_known_facts_context


@dataclass
class PipelineResolution:
    supported: bool
    context: str = ""
    grounded_cards: list[dict] = field(default_factory=list)


def build_pipeline_context(resolutions: list[CardResolution]) -> str:
    known_facts_blocks = []
    for resolution in resolutions:
        if resolution.status == "resolved":
            block = build_known_facts_context(resolution.card)
            if block:
                known_facts_blocks.append(block)

    failures = [r for r in resolutions if r.status != "resolved"]
    parts = list(known_facts_blocks)
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
    build_pipeline_context_fn: Callable[[list[CardResolution]], str] = build_pipeline_context,
    build_grounded_result_fn: Callable[[dict], dict] = build_grounded_result,
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
    return PipelineResolution(
        supported=True,
        context=build_pipeline_context_fn(resolutions),
        grounded_cards=[
            build_grounded_result_fn(r.card) for r in resolutions if r.status == "resolved"
        ],
    )
