import json
from dataclasses import dataclass

# search_rulebook and resolve_chain are temporarily disabled (pipeline instability).
# TOOL_NAMES excludes them, so parse_response() rejects a "TOOL: search_rulebook ..."/
# "TOOL: resolve_chain ..." line as an unrecognized tool name regardless of what the
# prompt text says -- but their descriptions stay in the prompt (see
# DISABLED_TOOL_DESCRIPTIONS below), marked "(DISABLED)", so the model knows they
# exist but must not attempt them, rather than the text silently going quiet on them.
TOOL_NAMES = {"lookup_card", "get_rulings"}

TOOL_DESCRIPTIONS = {
    "lookup_card": (
        'lookup_card {"name": "<query>", "field": "<optional>"} - fetch a card\'s text and structured '
        "effect data. Without \"field\", the query is tried in priority order as an exact name, then a "
        'fuzzy/partial name, then an archetype, then a passcode. Pass "field" as one of "name", "fname" '
        '(fuzzy/partial name), "archetype", or "id" (the card\'s passcode) to search only that one way -- '
        "e.g. use field=\"id\" when the user gives you a passcode directly. If the result has "
        '"ambiguous": true, more than one card matched -- do not guess which one; ask the user to narrow '
        "it down with the exact name or the passcode (the number in the lower left of the card)."
    ),
    "get_rulings": 'get_rulings {"card_id": "<id>"} - fetch official rulings for a card',
}

DISABLED_TOOL_DESCRIPTIONS = {
    "search_rulebook": (
        '(DISABLED) search_rulebook {"query": "<question>"} - semantic search over the Konami '
        "rulebook/PSCT guide or rulings via the ygoresources API"
    ),
    "resolve_chain": (
        '(DISABLED) resolve_chain {"turn_player": "...", "steps": [...]} - deterministically resolve a '
        "described chain scenario. An \"activate\" step may include an optional \"in_damage_step\": "
        "true/false (default false) to indicate the activation is being attempted during the Damage "
        'Step; that step\'s "effect" dict may include an optional "damage_step_category", per its enum '
        '("atk_def_alter", "negates_activation", "explicit_permission", "card_moved_trigger"), used only '
        "when checking Damage Step legality."
    ),
}


class ProtocolError(Exception):
    """Raised when an LLM response doesn't follow the TOOL:/FINAL: protocol."""


@dataclass
class ToolCall:
    name: str
    args: dict


@dataclass
class FinalAnswer:
    text: str
    cited_ids: set[str]


@dataclass
class Refusal:
    text: str


def build_system_prompt() -> str:
    tool_lines = "\n".join(
        f"- {desc}" for desc in {**TOOL_DESCRIPTIONS, **DISABLED_TOOL_DESCRIPTIONS}.values()
    )
    return (
        "You are a Yu-Gi-Oh! TCG rules-adjudication assistant. Answer only "
        "questions about Yu-Gi-Oh! rules (citing the rulebook or expert-provided "
        "rulings) and card effects and their interactions with rules or other "
        "cards, always citing your sources (the card effect or ruling found). "
        "For each response, use natural language as much as possible so the "
        "user can digest it easily. If the question is not about Yu-Gi-Oh! TCG "
        "and is out of scope of the role above, do not answer it -- respond "
        "with a line starting with 'REFUSE:' followed by a brief explanation "
        "that you only handle Yu-Gi-Oh! TCG rulings questions. You may call "
        "one tool per turn by responding with a line starting with 'TOOL:' "
        "followed by the tool name and a JSON object of arguments. When you "
        "have a final answer, respond with a line starting with 'FINAL:' "
        "followed by your answer text, then '||CITES: id1, id2||' listing "
        "every source id (card:<id>, ruling:<id>, chunk:<id>) your answer "
        "relies on -- use '||CITES: ||' if none apply. When speaking to the "
        "user about a card's 8-digit numeric identifier, always call it its "
        "'passcode' -- never 'id' or 'ygoprodeck_id', which are internal "
        "names only.\n\nAvailable tools:\n" + tool_lines
    )


def build_answering_system_prompt() -> str:
    return (
        "You are a Yu-Gi-Oh! TCG rules-adjudication assistant. You have "
        "already been given complete, verified information about every "
        "card this question could concern, below -- you have NO tools "
        "available in this turn. Do not attempt a 'TOOL:' line under any "
        "circumstances; it will not work. For any card listed under "
        "LOOKUP FAILURES, tell the user it was not found (a spelling "
        "check is a reasonable thing to suggest) and do NOT describe "
        "what that card might do from your own memory -- treat your own "
        "memory of what a specific card does as unreliable and never "
        "state it as fact. Respond with a line starting with 'FINAL:' "
        "followed by your answer text, then '||CITES: id1, id2||' "
        "listing every source id (card:<id>) your answer relies on -- "
        "use '||CITES: ||' if none apply. If the question is not about "
        "Yu-Gi-Oh! TCG rules or card interactions at all, respond with a "
        "line starting with 'REFUSE:' followed by a brief explanation "
        "instead. When speaking to the user about a card's 8-digit "
        "numeric identifier, always call it its 'passcode' -- never "
        "'id' or 'ygoprodeck_id', which are internal names only."
    )


def parse_response(response: str) -> ToolCall | FinalAnswer | Refusal:
    response = response.strip()

    if response.startswith("REFUSE:"):
        return Refusal(text=response[len("REFUSE:"):].strip())

    if response.startswith("TOOL:"):
        remainder = response[len("TOOL:"):].strip()
        try:
            name, json_part = remainder.split(" ", 1)
        except ValueError:
            raise ProtocolError(f"malformed TOOL line, expected 'TOOL: name {{json}}': {response!r}")
        if name not in TOOL_NAMES:
            raise ProtocolError(f"unrecognized tool name: {name!r}")
        try:
            # raw_decode (rather than json.loads) parses just the leading
            # JSON object and ignores anything after it -- some models
            # (e.g. Qwen3-8B via Ollama) append a stray 'FINAL: ...' line
            # to the same turn as a TOOL: call, which json.loads would
            # reject outright as "Extra data". The tool call's own JSON is
            # still well-formed, so honor it and drop the trailing noise.
            args, _ = json.JSONDecoder().raw_decode(json_part.strip())
        except json.JSONDecodeError as error:
            raise ProtocolError(f"invalid JSON arguments for tool {name!r}: {error}")
        return ToolCall(name=name, args=args)

    if response.startswith("FINAL:"):
        remainder = response[len("FINAL:"):].strip()
        if "||CITES:" not in remainder:
            raise ProtocolError(f"FINAL line missing '||CITES: ...||' trailer: {response!r}")
        text_part, _, cites_part = remainder.partition("||CITES:")
        cites_part = cites_part.strip()
        if not cites_part.endswith("||"):
            raise ProtocolError(f"FINAL line's CITES trailer must end with '||': {response!r}")
        cites_body = cites_part[:-2].strip()
        cited_ids = {c.strip() for c in cites_body.split(",") if c.strip()} if cites_body else set()
        return FinalAnswer(text=text_part.strip(), cited_ids=cited_ids)

    # Local models (e.g. Qwen3-8B via Ollama) sometimes drop the literal
    # 'FINAL:' prefix while still getting everything else right -- the
    # answer text and a well-formed '||CITES: ...||' trailer. That shape is
    # unambiguous (a TOOL: or REFUSE: response never ends in '||'), so treat
    # it as an implicit FINAL: instead of forcing a retry the model tends to
    # repeat verbatim rather than correct.
    if "||CITES:" in response and response.endswith("||"):
        text_part, _, cites_part = response.partition("||CITES:")
        cites_body = cites_part.strip()[:-2].strip()
        cited_ids = {c.strip() for c in cites_body.split(",") if c.strip()} if cites_body else set()
        return FinalAnswer(text=text_part.strip(), cited_ids=cited_ids)

    raise ProtocolError(f"response must start with 'TOOL:' or 'FINAL:': {response!r}")
