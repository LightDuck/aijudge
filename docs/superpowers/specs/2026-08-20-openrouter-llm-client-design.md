# AIJudge — OpenRouter LLM Client

## Purpose

The `2026-08-19-orchestration-and-cli-design.md` spec deliberately left
`LLMClient` mocked end-to-end, noting "production Claude wiring is a
later, separate swap behind the same interface." This document logs
that swap — except the provider ended up being OpenRouter, not Claude
directly, per an explicit choice made during brainstorming (see
"Decisions" below). Classified as a **bounded** change (brainstorming
skill): `LLMClient` already exists as an interface with one
implementation (`MockLLMClient`); this adds a second implementation
behind the same `complete(prompt: str) -> str` contract. No interface
changes, no design doc was required by process, but the decisions are
recorded here since they're non-obvious.

## What was built

`src/aijudge/llm/openrouter_client.py` — `OpenRouterLLMClient`,
implementing `LLMClient` via OpenRouter's OpenAI-compatible chat
completions endpoint (`POST
https://openrouter.ai/api/v1/chat/completions`). Follows the existing
ingestion-client pattern (`ygoprodeck_client.py`): a
dependency-injected `http_post` callable defaulting to `requests.post`,
so tests fake the HTTP layer without mocking `requests` globally.
`complete()` sends the whole accumulated prompt as a single `user`
message (no separate `system` role — `build_system_prompt()` already
folds everything into one string per `run_loop` turn), `timeout=30`,
`raise_for_status()`, returns
`response.json()["choices"][0]["message"]["content"]`. No new
dependency — `requests` was already in `pyproject.toml`.

Tests: `tests/llm/test_openrouter_client.py` — request shape, custom
model override, HTTP error propagation. All passing; full suite
verified green (115 passed, 29 DB-skipped) after the change.

`.env.example` gained `OPENROUTER_API_KEY=`.

## Decisions

**Why OpenRouter instead of Claude.** CLAUDE.md names Claude as the
production target and Ollama as a $0 local fallback. When brainstormed,
the user redirected to OpenRouter specifically to find a free model —
a deliberate deviation from that doc, not an oversight. This
supersedes CLAUDE.md's stated production target for now.

**Why a pinned model instead of OpenRouter's `openrouter/free` router.**
OpenRouter offers `openrouter/free`, which randomly selects each call
from its free-model pool (~23 models as of this writing) and filters
by requested features. That randomness is a bad fit here specifically:
`run_loop`'s protocol (`orchestration/protocol.py`) depends on the
model reliably emitting an exact `TOOL: name {json}` / `FINAL:
text||CITES: ...||` text format across multiple turns of one
conversation, and per-call model quality/instruction-following varies
a lot across that pool — a weak pick mid－conversation is more likely
to burn a `MAX_MALFORMED_RETRIES` retry or answer worse, and results
aren't reproducible run-to-run. `DEFAULT_MODEL` is instead pinned to
`meta-llama/llama-3.3-70b-instruct:free` — confirmed live and free via
OpenRouter's own listing at design time — chosen as a plain instruct
model (no chain-of-thought preamble that could break the
`response.startswith("TOOL:"/"FINAL:")` parsing), with solid
instruction-following and a stable listing history. `model` stays a
constructor parameter, overridable per instance.

**Why the response-structure question stayed out of scope.** A
follow-up question was whether to also force structured JSON output
(OpenRouter `response_format` / JSON schema) and rewrite
`orchestration/protocol.py`'s parser to consume it instead of the
`TOOL:`/`FINAL:` text lines. Explicitly declined to keep this bounded:
that change touches `protocol.py`, its tests, and only works with
models that support structured outputs — an architectural change, not
this one. The existing text protocol and its retry-on-malformed logic
in `run_loop` are unchanged and considered sufficient given the pinned
model choice above.

## Explicitly out of scope (not done)

- **No entrypoint wiring.** Nothing outside tests constructs an
  `OpenRouterLLMClient` — there's still no `__main__.py` / console
  script that reads `OPENROUTER_API_KEY` from the environment and
  calls `run_cli` with real clients. `python -m aijudge` doesn't work
  yet.
- **No real `EmbeddingClient`.** `search_rulebook` still returns
  nothing useful — `MockEmbeddingClient`'s SHA256-derived vectors are
  the only implementation. A real embedding provider (Voyage AI,
  Ollama-local, or otherwise) is a separate task.
- **No structured-output protocol.** See "Decisions" above.

## Work log

- Branch: `task/11-openrouter-llm-client` (off `dev` at `c41d202`,
  before the `dev` branch's later doc-tracking commits).
- Implementation committed at `9477f60`
  (`feat(llm): add OpenRouterLLMClient`).
