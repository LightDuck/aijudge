from dataclasses import dataclass


@dataclass
class ClarificationItem:
    kind: str  # "clarify" | "continuous_check"
    text: str


def build_clarification_prompt(question: str, *, known_facts_context: str = "") -> str:
    known_facts_section = (
        f"\n\n{known_facts_context}\n\nDo not ask the user for clarification about anything already "
        "covered above -- only raise CLARIFY/CONTINUOUS_CHECK for what the facts above don't resolve."
        if known_facts_context
        else ""
    )
    return (
        "A user asked a Yu-Gi-Oh! rules question. Before answering, decide "
        "whether you need more information:\n"
        "- If the question is ambiguous or missing details you need, "
        "respond with one or more lines: 'CLARIFY: <question to ask the user>'\n"
        "- If the question depends on a continuous or lingering effect card "
        "whose current on-board status you can't observe, respond with one "
        "or more lines: 'CONTINUOUS_CHECK: <card name>'\n"
        "- If neither applies, respond with exactly: 'PROCEED'"
        f"{known_facts_section}\n\n"
        f"Question: {question}"
    )


def parse_clarification_response(response: str) -> list[ClarificationItem]:
    items = []
    seen = set()
    for line in response.strip().splitlines():
        line = line.strip()
        if not line or line == "PROCEED":
            continue
        if line.startswith("CLARIFY:"):
            item = ClarificationItem(kind="clarify", text=line[len("CLARIFY:"):].strip())
        elif line.startswith("CONTINUOUS_CHECK:"):
            item = ClarificationItem(kind="continuous_check", text=line[len("CONTINUOUS_CHECK:"):].strip())
        else:
            continue
        key = (item.kind, item.text)
        if key in seen:
            continue
        seen.add(key)
        items.append(item)
    return items


def clarification_prompt_text(item: ClarificationItem) -> str:
    if item.kind == "continuous_check":
        return f"Is {item.text}'s effect currently active?"
    return item.text


_LABELS = {
    "clarify": "Clarification",
    "continuous_check": "Continuous effect status",
    "disambiguate_card": "Card disambiguation",
}


def format_clarification_context(items: list[ClarificationItem], answers: list[str]) -> str:
    lines = []
    for item, answer in zip(items, answers):
        label = _LABELS.get(item.kind, "Clarification")
        lines.append(f"{label} - {clarification_prompt_text(item)}: {answer}")
    return "\n".join(lines)
