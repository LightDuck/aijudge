import pytest

from aijudge.llm.client import MockLLMClient
from aijudge.orchestration.card_effect_pipeline import (
    PipelineResolution,
    build_pipeline_context,
    resolve_card_effect_question,
)
from aijudge.orchestration.card_resolution import CardResolution


@pytest.fixture(autouse=True)
def no_rulings_grounding(monkeypatch):
    from aijudge.orchestration import rulings_context

    monkeypatch.setattr(rulings_context, "build_rulings_grounding", lambda cards, **kwargs: rulings_context.RulingsGrounding())


@pytest.fixture(autouse=True)
def mock_db_for_test_cards(monkeypatch):
    """Mock get_confirmed_effects for fake test card IDs.

    This fixture is scoped locally to this test file only. It patches
    preflight.get_confirmed_effects to return fake effect data for
    non-UUID card IDs (e.g., "abc"), allowing build_known_facts_context
    tests to run without a live database. Real UUID lookups pass through
    to the actual implementation.
    """
    from aijudge.orchestration import preflight

    original_get_confirmed_effects = preflight.get_confirmed_effects

    def mock_get_confirmed_effects(card_id):
        # If card_id looks like a fake test ID (e.g., "abc"), return fake effect data
        if not _looks_like_real_uuid(card_id):
            return [
                {
                    "id": card_id,
                    "effect_type": "ignition",
                    "activation_condition": None,
                    "cost": None,
                    "targeting": None,
                    "has_target": False,
                    "effect": f"Test effect for {card_id}",
                    "damage_step_category": None,
                    "usage_limit_text": None,
                }
            ]
        # Otherwise, call the real function
        return original_get_confirmed_effects(card_id)

    monkeypatch.setattr(preflight, "get_confirmed_effects", mock_get_confirmed_effects)
    # These fake cards have no card_bulleted row; never reach the DB for it.
    monkeypatch.setattr(preflight, "get_card_bulleted", lambda passcode: None)


def _looks_like_real_uuid(value):
    """Check if a value looks like a real UUID."""
    try:
        import uuid

        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError):
        return False


def test_build_pipeline_context_renders_known_facts_for_resolved_cards():
    resolutions = [
        CardResolution(
            name="Tearlaments Scream",
            status="resolved",
            card={
                "id": "abc",
                "name": "Tearlaments Scream",
                "race": None,
                "card_type": "Fusion Monster",
                "card_text": "...",
            },
        )
    ]

    context = build_pipeline_context(resolutions)

    assert "Tearlaments Scream" in context
    assert "LOOKUP FAILURES" not in context


def test_build_pipeline_context_renders_failures_block_for_unresolved_names():
    resolutions = [
        CardResolution(name="Tearlaments Scrimm", status="not_found"),
        CardResolution(name="Tearlaments", status="ambiguous"),
    ]

    context = build_pipeline_context(resolutions)

    assert (
        "LOOKUP FAILURES (deterministic -- report these to the user, do not guess their effects):"
        in context
    )
    assert '- "Tearlaments Scrimm": not_found' in context
    assert '- "Tearlaments": ambiguous' in context


def test_build_pipeline_context_omits_failures_block_when_everything_resolved():
    resolutions = [
        CardResolution(
            name="Tearlaments Scream",
            status="resolved",
            card={
                "id": "abc",
                "name": "Tearlaments Scream",
                "race": None,
                "card_type": "Fusion Monster",
                "card_text": "...",
            },
        )
    ]

    assert "LOOKUP FAILURES" not in build_pipeline_context(resolutions)


def test_build_pipeline_context_returns_empty_string_for_no_resolutions():
    assert build_pipeline_context([]) == ""


def test_resolve_card_effect_question_returns_unsupported_when_no_names_extracted():
    llm = MockLLMClient()
    llm.queue_response("NONE")

    resolution = resolve_card_effect_question("What is the SEGOC rule?", llm_client=llm)

    assert resolution == PipelineResolution(supported=False)


def test_resolve_card_effect_question_resolves_extracted_card_and_builds_context():
    llm = MockLLMClient()
    llm.queue_response("Tearlaments Scream")

    def fake_resolve_named_cards(names, *, llm_client, online_ingest_enabled, on_ingest_start):
        assert names == ["Tearlaments Scream"]
        return [CardResolution(name="Tearlaments Scream", status="resolved", card={"id": "abc"})]

    resolution = resolve_card_effect_question(
        "What does Tearlaments Scream do?",
        llm_client=llm,
        resolve_named_cards_fn=fake_resolve_named_cards,
        build_pipeline_context_fn=lambda resolutions, **kwargs: "KNOWN FACTS: Tearlaments Scream",
        build_grounded_result_fn=lambda card: {"found": True, "id": card["id"], "confirmed_effects": []},
    )

    assert resolution == PipelineResolution(
        supported=True,
        context="KNOWN FACTS: Tearlaments Scream",
        grounded_cards=[
            {"found": True, "id": "abc", "confirmed_effects": [], "rulings": [], "rulings_status": None}
        ],
    )


def test_resolve_card_effect_question_only_grounds_resolved_names():
    llm = MockLLMClient()
    llm.queue_response("Tearlaments Scream\nTearlaments Scrimm")

    def fake_resolve_named_cards(names, *, llm_client, online_ingest_enabled, on_ingest_start):
        return [
            CardResolution(name="Tearlaments Scream", status="resolved", card={"id": "abc"}),
            CardResolution(name="Tearlaments Scrimm", status="not_found"),
        ]

    resolution = resolve_card_effect_question(
        "Do Tearlaments Scream and Tearlaments Scrimm interact?",
        llm_client=llm,
        resolve_named_cards_fn=fake_resolve_named_cards,
        build_pipeline_context_fn=lambda resolutions, **kwargs: "context",
        build_grounded_result_fn=lambda card: {"found": True, "id": card["id"], "confirmed_effects": []},
    )

    assert resolution.grounded_cards == [
        {"found": True, "id": "abc", "confirmed_effects": [], "rulings": [], "rulings_status": None}
    ]


def test_resolve_card_effect_question_threads_online_ingest_enabled_and_on_ingest_start():
    captured = {}

    def fake_resolve_named_cards(names, *, llm_client, online_ingest_enabled, on_ingest_start):
        captured["online_ingest_enabled"] = online_ingest_enabled
        captured["on_ingest_start"] = on_ingest_start
        return []

    def on_ingest_start(name):
        return None

    llm = MockLLMClient()
    llm.queue_response("Some Card")

    resolve_card_effect_question(
        "What does Some Card do?",
        llm_client=llm,
        online_ingest_enabled=False,
        on_ingest_start=on_ingest_start,
        resolve_named_cards_fn=fake_resolve_named_cards,
        build_pipeline_context_fn=lambda resolutions, **kwargs: "",
    )

    assert captured["online_ingest_enabled"] is False
    assert captured["on_ingest_start"] is on_ingest_start


from datetime import date

from aijudge.orchestration.rulings_context import RulingsGrounding

_RULING = {
    "id": "6f1c2a7e-0000-4000-8000-000000000001",
    "ruling_date": date(2017, 7, 22),
    "display_text": "Q: I activate the second effect of Amazoness Call, targeting an Amazoness Queen ...",
}


def test_build_pipeline_context_places_rulings_before_lookup_failures():
    resolutions = [
        CardResolution(name="Amazoness Call", status="resolved",
                       card={"id": "abc", "name": "Amazoness Call", "card_type": "Spell Card",
                             "card_text": "Take 1 \"Amazoness\" card ...", "race": "Quick-Play", "ygoprodeck_id": None}),
        CardResolution(name="Amazoness Qeen", status="not_found"),
    ]

    context = build_pipeline_context(resolutions, rulings_context="RULINGS (official Q&A ...")

    assert context.index("KNOWN FACTS") < context.index("RULINGS") < context.index("LOOKUP FAILURES")


def test_resolve_card_effect_question_grounds_resolved_cards_with_their_rulings():
    card = {"id": "abc", "name": "Amazoness Call", "rulings_status": "fetched"}
    seen_cards = []

    def fake_grounding(cards):
        seen_cards.extend(cards)
        return RulingsGrounding(context="RULINGS block", rulings_by_card_id={"abc": [_RULING]})

    resolution = resolve_card_effect_question(
        "Can Amazoness Call target Amazoness Queen?",
        llm_client=MockLLMClient(),
        extract_card_names_fn=lambda question, **kw: ["Amazoness Call", "Amazoness Qeen"],
        resolve_named_cards_fn=lambda names, **kw: [
            CardResolution(name="Amazoness Call", status="resolved", card=card),
            CardResolution(name="Amazoness Qeen", status="not_found"),
        ],
        build_pipeline_context_fn=lambda resolutions, rulings_context="": f"FACTS|{rulings_context}|FAILURES",
        build_grounded_result_fn=lambda c: {"found": True, "id": c["id"], "name": c["name"], "confirmed_effects": []},
        build_rulings_grounding_fn=fake_grounding,
    )

    assert seen_cards == [card]
    assert resolution.context == "FACTS|RULINGS block|FAILURES"
    assert resolution.grounded_cards[0]["rulings"] == [_RULING]
    assert resolution.grounded_cards[0]["rulings_status"] == "fetched"
