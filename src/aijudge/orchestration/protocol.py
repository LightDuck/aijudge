import json
from dataclasses import dataclass

TOOL_NAMES = {"lookup_card", "get_rulings", "search_rulebook", "resolve_chain"}

TOOL_DESCRIPTIONS = {
    "lookup_card": (
        'lookup_card {"name": "<query>", "field": "<optional>"} - fetch a card\'s text and structured '
        "effect data. Without \"field\", the query is tried in priority order as an exact name, then a "
        'fuzzy/partial name, then an archetype, then a passcode. Pass "field" as one of "name", "fname" '
        '(fuzzy/partial name), "archetype", or "id" (the card\'s passcode) to search only that one way -- '
        "e.g. use field=\"id\" when the user gives you a passcode directly. If the result has "
        '"ambiguous": true, more than one card matched -- do not guess which one; ask the user to narrow '
        "it down with the exact name, a more specific partial name, or the passcode."
    ),
    "get_rulings": 'get_rulings {"card_id": "<id>"} - fetch official rulings for a card',
    "search_rulebook": 'search_rulebook {"query": "<question>"} - semantic search over the Konami rulebook/PSCT guide',
    "resolve_chain": (
        'resolve_chain {"turn_player": "...", "steps": [...]} - deterministically resolve a described chain '
        "scenario. An \"activate\" step may include an optional \"in_damage_step\": true/false (default false) "
        "to indicate the activation is being attempted during the Damage Step; that step's \"effect\" dict may "
        'include an optional "damage_step_category", one of "atk_def_alter" or "negates_activation" (omit if '
        "neither applies), used only when checking Damage Step legality."
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


def build_system_prompt(available_tools: set[str] | None = None) -> str:
    names = available_tools if available_tools is not None else TOOL_DESCRIPTIONS.keys()
    tool_lines = "\n".join(f"- {TOOL_DESCRIPTIONS[name]}" for name in TOOL_DESCRIPTIONS if name in names)
    return (
        "You are a Yu-Gi-Oh! TCG rules-adjudication assistant. Answer only "
        "questions about Yu-Gi-Oh! rules and card interactions, citing your "
        "sources. If the question is not about Yu-Gi-Oh! TCG rules or card "
        "interactions, do not answer it -- respond with a line starting "
        "with 'REFUSE:' followed by a brief explanation that you only "
        "handle Yu-Gi-Oh! TCG rules questions. You may call one tool per "
        "turn by responding with a line starting with 'TOOL:' followed by "
        "the tool name and a JSON object of arguments. When you have a "
        "final answer, respond with a line starting with 'FINAL:' followed "
        "by your answer text, then '||CITES: id1, id2||' listing every "
        "source id (card:<id>, ruling:<id>, chunk:<id>) your answer relies "
        "on -- use '||CITES: ||' if none apply. When speaking to the user "
        "about a card's 8-digit numeric identifier, always call it its "
        "'passcode' -- never 'id' or 'ygoprodeck_id', which are internal "
        "names only.\n\nAvailable tools:\n" + tool_lines
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
            args = json.loads(json_part)
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

    raise ProtocolError(f"response must start with 'TOOL:' or 'FINAL:': {response!r}")
