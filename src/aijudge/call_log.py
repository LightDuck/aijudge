import contextvars
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .llm.client import LLMClient

DEFAULT_LOG_FILE = "logs/aijudge.jsonl"

_current_site: contextvars.ContextVar[str | None] = contextvars.ContextVar("aijudge_call_site", default=None)


@contextmanager
def call_site(name: str):
    """Tags every LLM call made inside this block (via `LoggingLLMClient`) with
    `name`, without changing the `LLMClient` protocol or any call signature --
    `LoggingLLMClient.complete` reads the active site off this contextvar."""
    token = _current_site.set(name)
    try:
        yield
    finally:
        _current_site.reset(token)


class CallLogger:
    """Appends one JSON object per line to a log file, stamping each record
    with a UTC timestamp. The file (and any missing parent directories) is
    created on first write."""

    def __init__(self, path: str | None = None) -> None:
        self.path = path or os.environ.get("AIJUDGE_LOG_FILE") or DEFAULT_LOG_FILE

    def log(self, record: dict) -> None:
        full_record = {"timestamp": datetime.now(timezone.utc).isoformat(), **record}
        path = Path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(full_record) + "\n")


def log_event(call_logger: CallLogger | None, *, site: str, event: str, reason: str | None = None, **context) -> None:
    """Structured, non-LLM-call record for an orchestration-level outcome
    (e.g. escalate, not_supported, verification_failed) -- the *why* behind a
    question failing, as opposed to a raw LLM call. No-ops when `call_logger`
    is None, so callers can make it optional without a null-check at every
    call site."""
    if call_logger is None:
        return
    call_logger.log({"type": "loop_event", "site": site, "event": event, "reason": reason, **context})


class LoggingLLMClient:
    """LLMClient wrapper that logs every call -- prompt, system prompt,
    response or exception, and duration -- to a CallLogger, then returns (or
    re-raises) exactly what the wrapped client did. Site tagging comes from
    the `call_site` contextvar rather than a parameter, so this stays a
    drop-in `LLMClient` and no caller needs to change how it invokes
    `complete`."""

    def __init__(self, inner: LLMClient, call_logger: CallLogger) -> None:
        self.inner = inner
        self.call_logger = call_logger

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        site = _current_site.get()
        start = time.monotonic()
        try:
            response = self.inner.complete(prompt, system=system)
        except Exception as error:
            duration_ms = (time.monotonic() - start) * 1000
            self.call_logger.log(
                {
                    "type": "llm_call",
                    "site": site,
                    "status": "error",
                    "duration_ms": duration_ms,
                    "prompt": prompt,
                    "system": system,
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
            )
            raise
        duration_ms = (time.monotonic() - start) * 1000
        self.call_logger.log(
            {
                "type": "llm_call",
                "site": site,
                "status": "ok",
                "duration_ms": duration_ms,
                "prompt": prompt,
                "system": system,
                "response": response,
            }
        )
        return response
