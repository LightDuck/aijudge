import json

from aijudge.call_log import CallLogger, LoggingLLMClient
from aijudge.llm.client import MockLLMClient
from aijudge.orchestration.extraction import (
    EXTRACTION_SYSTEM_PROMPT,
    build_extraction_prompt,
    extract_card_names,
    parse_extraction_response,
)


def test_extract_card_names_tags_its_llm_call_with_extraction_site(tmp_path):
    log_path = tmp_path / "aijudge.jsonl"
    call_logger = CallLogger(str(log_path))
    inner = MockLLMClient()
    inner.queue_response("Ash Blossom & Joyous Spring")
    wrapped = LoggingLLMClient(inner, call_logger)

    extract_card_names("What does Ash Blossom do?", llm_client=wrapped)

    with open(log_path, encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    assert records[0]["site"] == "extraction"


def test_build_extraction_prompt_includes_the_question():
    prompt = build_extraction_prompt("What does Tearlaments Scream do?")
    assert "What does Tearlaments Scream do?" in prompt


def test_parse_extraction_response_returns_empty_list_for_none():
    assert parse_extraction_response("NONE") == []


def test_parse_extraction_response_tolerates_trailing_punctuation_and_case():
    assert parse_extraction_response("none.") == []
    assert parse_extraction_response("None!") == []


def test_parse_extraction_response_returns_empty_list_for_blank_response():
    assert parse_extraction_response("") == []
    assert parse_extraction_response("   ") == []


def test_parse_extraction_response_returns_single_name():
    assert parse_extraction_response("Tearlaments Scream") == ["Tearlaments Scream"]


def test_parse_extraction_response_returns_multiple_names_one_per_line():
    assert parse_extraction_response("Tearlaments Scream\nTearlaments Sulliek") == [
        "Tearlaments Scream",
        "Tearlaments Sulliek",
    ]


def test_parse_extraction_response_strips_bullet_markers():
    assert parse_extraction_response("- Tearlaments Scream\n- Tearlaments Sulliek") == [
        "Tearlaments Scream",
        "Tearlaments Sulliek",
    ]


def test_parse_extraction_response_strips_numbered_list_markers():
    assert parse_extraction_response("1. Tearlaments Scream\n2) Tearlaments Sulliek") == [
        "Tearlaments Scream",
        "Tearlaments Sulliek",
    ]


def test_parse_extraction_response_strips_surrounding_quotes():
    assert parse_extraction_response('"Tearlaments Scream"') == ["Tearlaments Scream"]


def test_extract_card_names_calls_llm_with_extraction_system_prompt():
    llm = MockLLMClient()
    llm.queue_response("Tearlaments Scream")

    names = extract_card_names("What does Tearlaments Scream do?", llm_client=llm)

    assert names == ["Tearlaments Scream"]
    assert llm.system_prompts == [EXTRACTION_SYSTEM_PROMPT]


def test_extract_card_names_returns_empty_list_when_llm_says_none():
    llm = MockLLMClient()
    llm.queue_response("NONE")

    names = extract_card_names("What is the SEGOC rule?", llm_client=llm)

    assert names == []
