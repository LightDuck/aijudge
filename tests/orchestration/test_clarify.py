from aijudge.orchestration.clarify import (
    ClarificationItem,
    build_clarification_prompt,
    clarification_prompt_text,
    format_clarification_context,
    parse_clarification_response,
)


def test_parse_clarification_response_returns_empty_list_on_proceed():
    assert parse_clarification_response("PROCEED") == []


def test_parse_clarification_response_parses_clarify_lines():
    response = "CLARIFY: Which monster do you mean, the Level 4 or Level 8?"
    items = parse_clarification_response(response)
    assert items == [ClarificationItem(kind="clarify", text="Which monster do you mean, the Level 4 or Level 8?")]


def test_parse_clarification_response_parses_continuous_check_lines():
    response = "CONTINUOUS_CHECK: Skill Drain\nCONTINUOUS_CHECK: Rivalry of Warlords"
    items = parse_clarification_response(response)
    assert items == [
        ClarificationItem(kind="continuous_check", text="Skill Drain"),
        ClarificationItem(kind="continuous_check", text="Rivalry of Warlords"),
    ]


def test_parse_clarification_response_dedupes_identical_clarify_lines():
    response = "CLARIFY: Which monster do you mean?\nCLARIFY: Which monster do you mean?"
    items = parse_clarification_response(response)
    assert items == [ClarificationItem(kind="clarify", text="Which monster do you mean?")]


def test_parse_clarification_response_keeps_distinct_lines_of_the_same_kind():
    response = "CLARIFY: Which monster do you mean?\nCLARIFY: Are you the turn player?"
    items = parse_clarification_response(response)
    assert items == [
        ClarificationItem(kind="clarify", text="Which monster do you mean?"),
        ClarificationItem(kind="clarify", text="Are you the turn player?"),
    ]


def test_build_clarification_prompt_includes_the_question():
    prompt = build_clarification_prompt("Can I activate Solemn Strike here?")
    assert "Can I activate Solemn Strike here?" in prompt


def test_clarification_prompt_text_for_clarify_item_is_the_question_itself():
    item = ClarificationItem(kind="clarify", text="Which monster do you control?")
    assert clarification_prompt_text(item) == "Which monster do you control?"


def test_clarification_prompt_text_for_continuous_check_asks_about_activity():
    item = ClarificationItem(kind="continuous_check", text="Skill Drain")
    assert clarification_prompt_text(item) == "Is Skill Drain's effect currently active?"


def test_format_clarification_context_joins_items_and_answers():
    items = [
        ClarificationItem(kind="clarify", text="Which monster do you control?"),
        ClarificationItem(kind="continuous_check", text="Skill Drain"),
    ]
    answers = ["Blue-Eyes White Dragon", "yes"]

    context = format_clarification_context(items, answers)

    assert "Which monster do you control?: Blue-Eyes White Dragon" in context
    assert "Is Skill Drain's effect currently active?: yes" in context


def test_format_clarification_context_labels_disambiguate_card_items():
    items = [ClarificationItem(kind="disambiguate_card", text="Multiple cards match: Effect Veiler, Effector. Which one?")]
    answers = ["Effect Veiler"]

    context = format_clarification_context(items, answers)

    assert "Card disambiguation - Multiple cards match: Effect Veiler, Effector. Which one?: Effect Veiler" in context
