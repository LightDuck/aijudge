import json
from dataclasses import dataclass
from typing import Callable

from aijudge.llm.client import LLMClient
from aijudge.rules_engine.resolve import UnsupportedScenarioError

from .confidence import DEFAULT_CONFIDENCE_THRESHOLD, SignalState, compute_confidence, update_signals
from .protocol import FinalAnswer, ProtocolError, ToolCall, build_system_prompt, parse_response

MAX_MALFORMED_RETRIES = 3
NOT_SUPPORTED_MESSAGE = "not supported yet, contact dev team"
ESCALATE_MESSAGE = "escalate to a human judge"


@dataclass
class LoopResult:
    kind: str
    text: str


def run_loop(
    question: str,
    *,
    llm_client: LLMClient,
    tools: dict[str, Callable[[dict], dict]],
    clarification_context: str = "",
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> LoopResult:
    conversation = build_system_prompt() + "\n\nQuestion: " + question
    if clarification_context:
        conversation += "\n\n" + clarification_context

    state = SignalState()
    malformed_count = 0

    while True:
        response = llm_client.complete(conversation)

        try:
            parsed = parse_response(response)
        except ProtocolError as error:
            malformed_count += 1
            if malformed_count > MAX_MALFORMED_RETRIES:
                return LoopResult(kind="not_supported", text=NOT_SUPPORTED_MESSAGE)
            conversation += f"\n\nERROR: {error}"
            continue

        if isinstance(parsed, ToolCall):
            tool = tools[parsed.name]
            try:
                result = tool(parsed.args)
            except UnsupportedScenarioError:
                return LoopResult(kind="not_supported", text=NOT_SUPPORTED_MESSAGE)
            update_signals(state, parsed.name, result)
            conversation += f"\n\nTOOL RESULT ({parsed.name}): {json.dumps(result)}"
            continue

        assert isinstance(parsed, FinalAnswer)
        score = compute_confidence(parsed.cited_ids, state)
        if score < threshold:
            return LoopResult(kind="escalate", text=ESCALATE_MESSAGE)
        return LoopResult(kind="answer", text=parsed.text)
