import re

from aijudge.llm.client import LLMClient

EXTRACTION_SYSTEM_PROMPT = (
    "You extract Yu-Gi-Oh! TCG card names from a user's question. List "
    "every card name the question references, complete or partial, one "
    "per line, and nothing else. If the question does not reference any "
    "card by name, respond with exactly NONE."
)

_BULLET_RE = re.compile(r"^[\s\-\*]*(?:\d+[.\)]\s*)?")


def build_extraction_prompt(question: str) -> str:
    return f"Question: {question}"


def parse_extraction_response(response: str) -> list[str]:
    lines = [line.strip() for line in response.strip().splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return []
    if len(lines) == 1 and lines[0].strip(".! \t").upper() == "NONE":
        return []
    names = []
    for line in lines:
        cleaned = _BULLET_RE.sub("", line).strip().strip("\"'")
        if cleaned and cleaned.upper() != "NONE":
            names.append(cleaned)
    return names


def extract_card_names(question: str, *, llm_client: LLMClient) -> list[str]:
    response = llm_client.complete(build_extraction_prompt(question), system=EXTRACTION_SYSTEM_PROMPT)
    return parse_extraction_response(response)
