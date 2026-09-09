import json
import logging
from dataclasses import dataclass, field
from typing import Callable

from aijudge.llm.client import LLMClient
from aijudge.rules_engine.resolve import UnsupportedScenarioError

from .confidence import DEFAULT_CONFIDENCE_THRESHOLD, SignalState, compute_confidence, update_signals
from .protocol import FinalAnswer, ProtocolError, Refusal, ToolCall, build_system_prompt, parse_response
from .verify import VerificationResult, verify_structured_grounding

logger = logging.getLogger(__name__)

MAX_MALFORMED_RETRIES = 3
MAX_TOOL_CALLS = 10
MAX_VERIFICATION_RETRIES = 2
NOT_SUPPORTED_MESSAGE = "not supported yet, contact dev team"
ESCALATE_MESSAGE = "escalate to a human judge"


@dataclass
class LoopResult:
    kind: str
    text: str
    citations: list[dict] = field(default_factory=list)


def _describe_mismatch(mismatch: dict, state: SignalState) -> str:
    """Render one verification mismatch for the VERIFICATION_FAILED feedback
    message: the card's human-readable name (from `state.citation_index`,
    falling back to the raw id if it's somehow missing) followed by whatever
    of its stored activation_condition/cost/targeting/effect breakdown is
    present -- mirrors verify.py's own conditional-append rendering."""
    card_label = state.citation_index.get(mismatch["card_id"], {}).get("label") or mismatch["card_id"]
    parts = []
    if mismatch.get("activation_condition"):
        parts.append(f"activation condition: {mismatch['activation_condition']}")
    if mismatch.get("cost"):
        parts.append(f"cost: {mismatch['cost']}")
    if mismatch.get("targeting"):
        parts.append(f"targeting: {mismatch['targeting']}")
    if mismatch.get("effect_text"):
        parts.append(f"effect: {mismatch['effect_text']}")
    return f"- {card_label}: \"{'; '.join(parts)}\""


def run_loop(
    question: str,
    *,
    llm_client: LLMClient,
    tools: dict[str, Callable[[dict], dict]],
    clarification_context: str = "",
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    grounded_cards: list[dict] | None = None,
    system_prompt: str | None = None,
) -> LoopResult:
    system_prompt = system_prompt if system_prompt is not None else build_system_prompt()
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
    verification_retry_count = 0
    # Card ids flagged by the most recent verification failure, and the
    # mismatches that flagged them -- carried across loop turns so a redraft
    # that drops every one of these citations (instead of fixing the prose)
    # can be caught as a bypass attempt rather than silently passing.
    flagged_card_ids: set[str] = set()
    flagged_mismatches: list[dict] = []

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

        verification = verify_structured_grounding(parsed.text, parsed.cited_ids, state, llm_client)
        if verification.ok and flagged_card_ids and not (flagged_card_ids & parsed.cited_ids):
            # The prior turn's answer failed verification for these card(s);
            # this redraft cites none of them, so verify_structured_grounding
            # correctly found nothing to check -- but that's exactly the
            # bypass this gate exists to prevent (dropping the citation
            # instead of fixing the prose). Treat it as another verification
            # failure under the same budget, reusing the prior mismatch
            # details for the feedback message since there's nothing new to
            # report.
            logger.debug(
                "redraft dropped every previously-flagged citation %s -> treating as verification failure",
                flagged_card_ids,
            )
            verification = VerificationResult(ok=False, mismatches=flagged_mismatches)

        if not verification.ok:
            verification_retry_count += 1
            flagged_mismatches = verification.mismatches
            flagged_card_ids = {m["card_id"] for m in verification.mismatches}
            logger.debug(
                "structured grounding verification failed (retry_count=%d): %s",
                verification_retry_count, verification.mismatches,
            )
            if verification_retry_count > MAX_VERIFICATION_RETRIES:
                logger.debug("verification retry budget exceeded -> escalate")
                return LoopResult(kind="escalate", text=ESCALATE_MESSAGE)
            mismatch_lines = "\n".join(_describe_mismatch(m, state) for m in verification.mismatches)
            conversation += (
                "\n\nVERIFICATION_FAILED: your previous FINAL answer was: "
                f"\"{parsed.text}\"\nBut its description doesn't match the "
                "stored effect text below. Revise your FINAL answer to "
                f"accurately reflect it.\n{mismatch_lines}"
            )
            continue

        citations = [state.citation_index[cid] for cid in sorted(parsed.cited_ids)]
        return LoopResult(kind="answer", text=parsed.text, citations=citations)
