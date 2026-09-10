import json

import pytest

from aijudge.call_log import CallLogger, LoggingLLMClient, call_site, log_event
from aijudge.llm.client import MockLLMClient


def _read_records(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_call_logger_writes_one_json_line_per_record(tmp_path):
    log_path = tmp_path / "aijudge.jsonl"
    logger = CallLogger(str(log_path))

    logger.log({"type": "llm_call", "site": "loop"})
    logger.log({"type": "llm_call", "site": "verify"})

    records = _read_records(log_path)
    assert [r["site"] for r in records] == ["loop", "verify"]


def test_call_logger_stamps_each_record_with_a_timestamp(tmp_path):
    log_path = tmp_path / "aijudge.jsonl"
    logger = CallLogger(str(log_path))

    logger.log({"type": "llm_call"})

    record = _read_records(log_path)[0]
    assert "timestamp" in record and record["timestamp"]


def test_call_logger_creates_missing_parent_directory(tmp_path):
    log_path = tmp_path / "nested" / "dir" / "aijudge.jsonl"
    logger = CallLogger(str(log_path))

    logger.log({"type": "llm_call"})

    assert log_path.exists()


def test_logging_llm_client_logs_successful_call_with_site_and_content(tmp_path):
    log_path = tmp_path / "aijudge.jsonl"
    call_logger = CallLogger(str(log_path))
    inner = MockLLMClient()
    inner.queue_response("the answer")
    wrapped = LoggingLLMClient(inner, call_logger)

    with call_site("loop"):
        result = wrapped.complete("Question: what does Ash do?", system="You are an assistant.")

    assert result == "the answer"
    record = _read_records(log_path)[0]
    assert record["type"] == "llm_call"
    assert record["site"] == "loop"
    assert record["status"] == "ok"
    assert record["prompt"] == "Question: what does Ash do?"
    assert record["system"] == "You are an assistant."
    assert record["response"] == "the answer"
    assert "duration_ms" in record


def test_logging_llm_client_tags_unknown_site_when_no_call_site_active(tmp_path):
    log_path = tmp_path / "aijudge.jsonl"
    call_logger = CallLogger(str(log_path))
    inner = MockLLMClient()
    inner.queue_response("answer")
    wrapped = LoggingLLMClient(inner, call_logger)

    wrapped.complete("prompt")

    record = _read_records(log_path)[0]
    assert record["site"] is None


def test_logging_llm_client_logs_and_reraises_on_exception(tmp_path):
    log_path = tmp_path / "aijudge.jsonl"
    call_logger = CallLogger(str(log_path))

    class BoomClient:
        def complete(self, prompt, *, system=None):
            raise ConnectionError("backend unreachable")

    wrapped = LoggingLLMClient(BoomClient(), call_logger)

    with call_site("extraction"), pytest.raises(ConnectionError):
        wrapped.complete("prompt")

    record = _read_records(log_path)[0]
    assert record["status"] == "error"
    assert record["site"] == "extraction"
    assert record["error_type"] == "ConnectionError"
    assert record["error"] == "backend unreachable"
    assert "response" not in record


def test_call_site_scopes_to_its_with_block_only(tmp_path):
    log_path = tmp_path / "aijudge.jsonl"
    call_logger = CallLogger(str(log_path))
    inner = MockLLMClient()
    inner.queue_response("a")
    inner.queue_response("b")
    wrapped = LoggingLLMClient(inner, call_logger)

    with call_site("verify"):
        wrapped.complete("first")
    wrapped.complete("second")

    records = _read_records(log_path)
    assert records[0]["site"] == "verify"
    assert records[1]["site"] is None


def test_log_event_writes_structured_event(tmp_path):
    log_path = tmp_path / "aijudge.jsonl"
    call_logger = CallLogger(str(log_path))

    log_event(call_logger, site="loop", event="escalate", reason="score below threshold", score=0.5, threshold=0.9)

    record = _read_records(log_path)[0]
    assert record["type"] == "loop_event"
    assert record["site"] == "loop"
    assert record["event"] == "escalate"
    assert record["reason"] == "score below threshold"
    assert record["score"] == 0.5
    assert record["threshold"] == 0.9


def test_log_event_is_a_noop_when_call_logger_is_none(tmp_path):
    # Should not raise -- callers pass call_logger=None by default.
    log_event(None, site="loop", event="answered")
