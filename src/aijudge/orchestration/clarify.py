from dataclasses import dataclass


@dataclass
class ClarificationItem:
    kind: str  # "clarify" | "continuous_check"
    text: str


def build_clarification_prompt(question: str) -> str:
    return (
        "A user asked a Yu-Gi-Oh! rules question. Before answering, decide "
        "whether you need more information:\n"
        "- If the question is ambiguous or missing details you need, "
        "respond with one or more lines: 'CLARIFY: <question to ask the user>'\n"
        "- If the question depends on a continuous or lingering effect card "
        "whose current on-board status you can't observe, respond with one "
        "or more lines: 'CONTINUOUS_CHECK: <card name>'\n"
        "- If neither applies, respond with exactly: 'PROCEED'\n\n"
        f"Question: {question}"
    )


def parse_clarification_response(response: str) -> list[ClarificationItem]:
    items = []
    for line in response.strip().splitlines():
        line = line.strip()
        if not line or line == "PROCEED":
            continue
        if line.startswith("CLARIFY:"):
            items.append(ClarificationItem(kind="clarify", text=line[len("CLARIFY:"):].strip()))
        elif line.startswith("CONTINUOUS_CHECK:"):
            items.append(ClarificationItem(kind="continuous_check", text=line[len("CONTINUOUS_CHECK:"):].strip()))
    return items


def clarification_prompt_text(item: ClarificationItem) -> str:
    if item.kind == "continuous_check":
        return f"Is {item.text}'s effect currently active?"
    return item.text


def format_clarification_context(items: list[ClarificationItem], answers: list[str]) -> str:
    lines = []
    for item, answer in zip(items, answers):
        label = "Clarification" if item.kind == "clarify" else "Continuous effect status"
        lines.append(f"{label} - {clarification_prompt_text(item)}: {answer}")
    return "\n".join(lines)
