import json
import logging
from dataclasses import dataclass, field
from typing import Callable

from aijudge.llm.client import LLMClient
from aijudge.rules_engine.resolve import UnsupportedScenarioError

from .confidence import DEFAULT_CONFIDENCE_THRESHOLD, SignalState, compute_confidence, update_signals
from .protocol import FinalAnswer, ProtocolError, Refusal, ToolCall, build_system_prompt, parse_response

logger = logging.getLogger(__name__)

MAX_MALFORMED_RETRIES = 3
MAX_TOOL_CALLS = 10
NOT_SUPPORTED_MESSAGE = "not supported yet, contact dev team"
ESCALATE_MESSAGE = "escalate to a human judge"


@dataclass
class LoopResult:
    kind: str
    text: str
    citations: list[dict] = field(default_factory=list)


def run_loop(
    question: str,
    *,
    llm_client: LLMClient,
    tools: dict[str, Callable[[dict], dict]],
    clarification_context: str = "",
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    grounded_cards: list[dict] | None = None,
) -> LoopResult:
    system_prompt = build_system_prompt()
    conversation = "Question: " + question
    if clarification_context:
        conversation += "\n\n" + clarification_context

    state = SignalState()
    for card in grounded_cards or ():
        # Pre-register a preflight-matched card's id exactly as if
        # lookup_card had returned it, so an LLM that answers directly from
        # already-injected KNOWN FACTS (skipping the tool call since the
        # facts already answer the question) has a legitimate id to cite
        # instead of fabricating one and getting escalated.
        update_signals(state, "lookup_card", card)
    malformed_count = 0
    tool_call_count = 0

    while True:
        response = llm_client.complete(conversation, system=system_prompt)
        logger.debug("LLM raw response (turn tool_calls=%d malformed=%d): %r", tool_call_count, malformed_count, response)

        try:
            parsed = parse_response(response)
        except ProtocolError as error:
            malformed_count += 1
            logger.debug("ProtocolError parsing LLM response (malformed_count=%d): %s", malformed_count, error)
            if malformed_count > MAX_MALFORMED_RETRIES:
                logger.debug("malformed retry budget exceeded -> not_supported")
                return LoopResult(kind="not_supported", text=NOT_SUPPORTED_MESSAGE)
            conversation += f"\n\nERROR: {error}"
            continue

        if isinstance(parsed, Refusal):
            logger.debug("LLM refused (off_topic): %s", parsed.text)
            return LoopResult(kind="off_topic", text=parsed.text)

        if isinstance(parsed, ToolCall):
            tool_call_count += 1
            logger.debug("ToolCall #%d: %s(%r)", tool_call_count, parsed.name, parsed.args)
            if tool_call_count > MAX_TOOL_CALLS:
                logger.debug("tool call budget exceeded -> not_supported")
                return LoopResult(kind="not_supported", text=NOT_SUPPORTED_MESSAGE)
            tool = tools[parsed.name]
            try:
                result = tool(parsed.args)
            except UnsupportedScenarioError:
                logger.debug("UnsupportedScenarioError from tool %s -> not_supported", parsed.name)
                return LoopResult(kind="not_supported", text=NOT_SUPPORTED_MESSAGE)
            except (KeyError, ValueError, TypeError) as error:
                malformed_count += 1
                logger.debug("tool %s raised %s: %s (malformed_count=%d)", parsed.name, type(error).__name__, error, malformed_count)
                if malformed_count > MAX_MALFORMED_RETRIES:
                    logger.debug("malformed retry budget exceeded -> not_supported")
                    return LoopResult(kind="not_supported", text=NOT_SUPPORTED_MESSAGE)
                conversation += f"\n\nERROR: {error}"
                continue
            logger.debug("Tool result for %s: %s", parsed.name, json.dumps(result))
            update_signals(state, parsed.name, result)
            conversation += f"\n\nTOOL RESULT ({parsed.name}): {json.dumps(result)}"
            continue

        assert isinstance(parsed, FinalAnswer)
        score = compute_confidence(parsed.cited_ids, state)
        logger.debug(
            "FinalAnswer cited_ids=%s known_ids=%s retrieval_gap=%s missing_structured_effect=%s score=%.2f threshold=%.2f",
            parsed.cited_ids, state.known_ids, state.retrieval_gap, state.missing_structured_effect, score, threshold,
        )
        if score < threshold:
            return LoopResult(kind="escalate", text=ESCALATE_MESSAGE)
        citations = [state.citation_index[cid] for cid in sorted(parsed.cited_ids)]
        return LoopResult(kind="answer", text=parsed.text, citations=citations)
