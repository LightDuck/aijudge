import pytest

from aijudge.orchestration.protocol import FinalAnswer, ProtocolError, ToolCall, build_system_prompt, parse_response


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


def test_build_system_prompt_lists_all_four_tools():
    prompt = build_system_prompt()
    for tool_name in ("lookup_card", "get_rulings", "search_rulebook", "resolve_chain"):
        assert tool_name in prompt
