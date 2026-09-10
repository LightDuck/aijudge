import os

import pytest
import requests


def _ollama_available() -> bool:
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    try:
        requests.get(f"{base_url}/api/tags", timeout=2)
        return True
    except requests.exceptions.RequestException:
        return False


pytestmark = pytest.mark.skipif(not _ollama_available(), reason="requires a running local Ollama server")


# Regression test for a real qwen3:8b behavior: given the original
# EXTRACTION_SYSTEM_PROMPT (no examples, no guidance that a bare proper noun
# counts as a card reference), the model deterministically responded NONE to
# every one of these "What does <Name> do?" questions -- the single most
# natural way to ask about a card's effect -- even though it correctly
# extracted the same name under other phrasings (e.g. "Explain <Name>",
# "What does the card <Name> do?"). This silently dropped any question in
# this shape for a card not already locally seeded, since
# card_effect_pipeline.resolve_card_effect_question short-circuits to
# "not supported" before online ingestion is ever attempted when extraction
# returns no names.
@pytest.mark.parametrize(
    "name",
    [
        "Effect Veiler",
        "Called by the Grave",
        "Infinite Impermanence",
        "Pot of Desires",
        "Solemn Strike",
        "Baronne de Fleur",
        "Borreload Dragon",
    ],
)
def test_extract_card_names_recognizes_bare_name_in_what_does_it_do_template(name):
    from aijudge.llm.client import OllamaLLMClient
    from aijudge.orchestration.extraction import extract_card_names

    client = OllamaLLMClient()

    names = extract_card_names(f"What does {name} do?", llm_client=client)

    assert names == [name]


def test_extract_card_names_still_returns_empty_for_a_genuinely_cardless_question():
    from aijudge.llm.client import OllamaLLMClient
    from aijudge.orchestration.extraction import extract_card_names

    client = OllamaLLMClient()

    names = extract_card_names("What is the SEGOC rule?", llm_client=client)

    assert names == []
