import pytest

from aijudge.orchestration.protocol import (
    FinalAnswer,
    ProtocolError,
    Refusal,
    ToolCall,
    build_system_prompt,
    parse_response,
)


def test_parses_tool_call_line():
    parsed = parse_response('TOOL: lookup_card {"name": "Ash Blossom & Joyous Spring"}')
    assert parsed == ToolCall(name="lookup_card", args={"name": "Ash Blossom & Joyous Spring"})


def test_parses_final_answer_with_citations():
    parsed = parse_response("FINAL: This card negates the effect. ||CITES: card:1, ruling:2||")
    assert parsed == FinalAnswer(text="This card negates the effect.", cited_ids={"card:1", "ruling:2"})


def test_parses_final_answer_with_empty_citations():
    parsed = parse_response("FINAL: Out of scope for this assistant. ||CITES: ||")
    assert parsed == FinalAnswer(text="Out of scope for this assistant.", cited_ids=set())


def test_rejects_unrecognized_tool_name():
    with pytest.raises(ProtocolError):
        parse_response("TOOL: delete_database {}")


def test_rejects_malformed_json_arguments():
    with pytest.raises(ProtocolError):
        parse_response("TOOL: lookup_card {not json}")


def test_salvages_tool_call_with_trailing_final_line_appended_in_same_turn():
    parsed = parse_response(
        'TOOL: lookup_card {"name": "Tearlaments Sulliek"}\n'
        'FINAL: Tearlaments Sulliek does X. ||CITES: card:14614688||'
    )
    assert parsed == ToolCall(name="lookup_card", args={"name": "Tearlaments Sulliek"})


def test_rejects_final_answer_missing_cites_trailer():
    with pytest.raises(ProtocolError):
        parse_response("FINAL: This card negates the effect.")


def test_rejects_tool_line_with_no_json_part():
    with pytest.raises(ProtocolError):
        parse_response("TOOL: lookup_card")


def test_rejects_final_answer_whose_cites_trailer_is_not_closed():
    with pytest.raises(ProtocolError):
        parse_response("FINAL: This card negates the effect. ||CITES: card:1")


def test_rejects_response_with_no_recognized_prefix():
    with pytest.raises(ProtocolError):
        parse_response("I think the answer is yes.")


def test_salvages_final_answer_missing_final_prefix_but_with_valid_cites_trailer():
    parsed = parse_response("This card negates the effect. ||CITES: card:1, ruling:2||")
    assert parsed == FinalAnswer(text="This card negates the effect.", cited_ids={"card:1", "ruling:2"})


def test_rejects_missing_prefix_response_with_unclosed_cites_trailer():
    with pytest.raises(ProtocolError):
        parse_response("This card negates the effect. ||CITES: card:1")


def test_build_system_prompt_lists_all_four_tools():
    prompt = build_system_prompt()
    for tool_name in ("lookup_card", "get_rulings", "search_rulebook", "resolve_chain"):
        assert tool_name in prompt


def test_build_system_prompt_documents_damage_step_fields_for_resolve_chain():
    prompt = build_system_prompt()
    assert "in_damage_step" in prompt
    assert "damage_step_category" in prompt


def test_build_system_prompt_instructs_refusal_for_off_topic_questions():
    prompt = build_system_prompt()
    assert "REFUSE:" in prompt


def test_parses_refusal_line():
    parsed = parse_response("REFUSE: This assistant only answers Yu-Gi-Oh! TCG rules questions.")
    assert parsed == Refusal(text="This assistant only answers Yu-Gi-Oh! TCG rules questions.")


def test_build_system_prompt_documents_lookup_card_field_param():
    prompt = build_system_prompt()
    assert '"field"' in prompt
    for field_name in ("name", "fname", "archetype", "id"):
        assert field_name in prompt


def test_build_system_prompt_instructs_passcode_terminology_for_the_id_field():
    prompt = build_system_prompt()
    assert "passcode" in prompt.lower()


def test_build_system_prompt_instructs_ambiguous_result_handling():
    prompt = build_system_prompt()
    assert "ambiguous" in prompt.lower()
