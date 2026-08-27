# AIJudge — HTTP API Layer Design

## Purpose

CLAUDE.md lists three things still missing for a public v1.0: broader
card coverage, an HTTP/API service layer in front of the orchestration
loop, and a frontend. This document specs the API layer — sub-project
1 of 2 identified while scoping "build a React frontend that simulates
an assistant AI": the frontend cannot exist without something a
browser can call, and today `run_cli` (`src/aijudge/cli.py`) is a
blocking stdin/stdout REPL, not callable over HTTP. The React frontend
itself is a separate, later spec that will consume the contract
defined here.

Classified as **architectural** (brainstorming skill): this is a new
subsystem with no existing flow to modify.

## Scope and deployment target

Local single-user, matching the project's current $0-cost local-first
posture (`OllamaLLMClient` / `OllamaEmbeddingClient` via
`python -m aijudge`). No auth, no multi-tenancy, no concurrency
hardening beyond what FastAPI/uvicorn give for free. A hosted/shared
deployment is out of scope and would need its own design pass
(auth, per-user rate limiting, etc.) if it ever comes up.

## Existing flow this replaces

`run_cli` today, per question:
1. Calls `build_clarification_prompt` → LLM → `parse_clarification_response`,
   getting zero or more `ClarificationItem`s (`kind: "clarify" |
   "continuous_check"`).
2. Blocks on `input_fn` once per item to collect an answer.
3. Builds `clarification_context` via `format_clarification_context`
   and calls `run_loop(question, ..., clarification_context=...)`.
4. Prints `result.text`.

The API layer re-exposes exactly this flow over HTTP, without
`input_fn`'s synchronous blocking — the clarify step becomes a
round-trip the client (frontend) drives instead of a blocking
terminal prompt.

## Architecture

New `src/aijudge/api/` package, following the codebase's
per-concern module convention:

- **`schemas.py`** — Pydantic request/response models (see Endpoints
  below).
- **`app.py`** — `create_app(llm_client: LLMClient, embedding_client:
  EmbeddingClient) -> FastAPI`. A factory, not a module-level `app`
  object, so tests can inject `MockLLMClient`/`MockEmbeddingClient`
  the same way existing orchestration tests do. Builds the tool
  dispatch once via `build_tool_dispatch(embedding_client)` and closes
  over it in the route handlers.
- **`__main__.py`** — mirrors `src/aijudge/__main__.py`: constructs
  real `OllamaLLMClient()` / `OllamaEmbeddingClient()`, calls
  `create_app`, runs it with `uvicorn.run`. `OLLAMA_*` env vars keep
  working unchanged since the same client classes are reused.

Stack: **FastAPI + uvicorn**. Chosen over Flask/plain WSGI because
Pydantic validation matches the codebase's existing typed-dataclass
style, and `fastapi.testclient.TestClient` is synchronous — API tests
don't need async test infrastructure, just an injected mock loop
dependency, consistent with how `tests/orchestration` already avoids
real LLM/DB calls.

## State model: stateless

The clarify → answer flow is **stateless** — the server keeps no
session store between the two requests. The first response returns
the clarification items verbatim to the client; the second request
carries the original question plus those same items plus the user's
answers back to the server, which reconstructs
`ClarificationItem`s and calls `format_clarification_context` itself.

Rejected alternative: a server-side session dict keyed by a generated
`session_id`, returned from step 1 and referenced in step 2. This
would shrink the step-2 payload slightly but adds session lifecycle
concerns (expiry, cleanup, state lost on restart) that buy nothing at
single-user local scale. Stateless was chosen for simplicity and
restart-safety.

## Endpoints

### `POST /questions`

Request: `{"question": str}`

Runs the clarification pass (`build_clarification_prompt` → LLM call →
`parse_clarification_response`).

- If no clarification items come back: proceeds straight into
  `run_loop(question, ..., clarification_context="")` and returns a
  **Result** object (see below) directly.
- If items come back: returns
  ```json
  {
    "status": "needs_clarification",
    "question": "<original question>",
    "items": [{"kind": "clarify" | "continuous_check", "text": "..."}]
  }
  ```

Empty/whitespace `question` → `400`.

### `POST /questions/answer`

Request:
```json
{
  "question": "<original question>",
  "items": [{"kind": "...", "text": "..."}],
  "answers": ["...", "..."]
}
```
(`items` and `answers` are the exact arrays the client received from
and then filled in against the `/questions` response — this is the
stateless round-trip.)

Rebuilds `ClarificationItem`s from `items`, calls
`format_clarification_context(items, answers)`, then
`run_loop(question, ..., clarification_context=context)`. Returns a
**Result** object.

`len(items) != len(answers)` → `400`.

### Result object (returned by both endpoints on completion)

```json
{
  "status": "answer" | "escalate" | "not_supported",
  "text": "<answer or escalation/not-supported message>",
  "citations": [{"label": "...", "text": "..."}] | null
}
```

`citations` is populated only when `status == "answer"`, and is a list
of human-readable `{label, text}` pairs covering every citable source
the answer drew on — cards, rulings, and rulebook chunks alike — never
the raw internal ids (`card:<uuid>`, `ruling:<uuid>`, `chunk:<uuid>`).
Those ids stay server-side (see below); the public API contract never
emits them.

## Orchestration change required: citation text

`LoopResult` (`orchestration/loop.py`) currently only carries `kind`
and `text` — `cited_ids` is used to compute the confidence score and
then discarded. Returning citation *content* (not ids) requires:

- `SignalState` (`orchestration/confidence.py`) gains an id → `{label,
  text}` index, populated in `update_signals` alongside the existing
  `known_ids` set, covering all three citable id kinds: a card's
  `name`/`card_text` (`card:<id>`), a ruling's `source`/`ruling_text`
  (`ruling:<id>`), and a rulebook chunk's `source`/`chunk_text`
  (`chunk:<id>`).
- `LoopResult` gains a `citations: list[dict]` field. `run_loop`
  populates it by resolving `parsed.cited_ids` against that index
  right before returning the `"answer"` result.

This is a contained change to two existing orchestration files — no
schema or ingestion changes. The internal ids remain in
`SignalState`/`LoopResult` for server-side use (logging, potential
future debugging) but the API's Pydantic response models simply don't
include an id field, so they can never leak into a JSON response by
accident.

## Error handling

Every error response is a small, generic JSON body:
```json
{"detail": "<short generic message>"}
```
No stack traces, no raw exception text, no internal ids or DB
connection details in the response — the same "hidden-ish" treatment
citations get. The real exception (with traceback) is logged
server-side via `logging`, never returned to the client.

- Empty/whitespace `question`, or mismatched `items`/`answers` length
  → `400`.
- Malformed request body → FastAPI's automatic `422`.
- Connection errors from the LLM or DB clients (Ollama or Postgres
  unreachable) → caught at the route level, `503` with a fixed message
  like `"backend unavailable"`. This is the realistic local-dev
  failure mode ("did you start Docker/Ollama") and deserves a clearer
  signal than a bare 500.
- Any other unexpected exception → generic `500`, logged server-side.
- `UnsupportedScenarioError` from `resolve_chain` is already handled
  inside `run_loop` (returns `kind="not_supported"`) — no new handling
  needed at the API layer for that case.

## CORS

Enabled permissively for localhost origins (the future React dev
server runs on a different port than the API). Configurable via an
env var (e.g. `AIJUDGE_API_CORS_ORIGINS`), defaulting to common local
dev ports, since this is a local single-user tool and not
internet-facing.

## Testing

New `tests/api/`, using `fastapi.testclient.TestClient` against
`create_app(MockLLMClient(...), MockEmbeddingClient())` — no real
Ollama/DB required, matching how `tests/orchestration` already tests
`run_loop` against mocks. TDD per project convention: a failing test
precedes each endpoint and precedes the `LoopResult.citations` change.

Coverage to include:
- `POST /questions` with a mocked "no clarification needed" LLM
  response → returns a Result object with the expected `status`/`text`.
- `POST /questions` with a mocked clarification response → returns
  `needs_clarification` with the parsed items.
- `POST /questions/answer` round-trip → returns a Result object;
  confirms `format_clarification_context` output reaches the loop
  correctly.
- Citation content (not ids) appears in `citations` on an `"answer"`
  result; ids never appear anywhere in the JSON response body.
- Error cases: empty question (`400`), mismatched items/answers
  length (`400`), malformed JSON (`422`), simulated backend connection
  error (`503`) — response bodies contain only the generic `detail`
  message, never exception internals.
- `orchestration/confidence.py` / `loop.py`: unit tests for the new
  citation-text index and `LoopResult.citations` population, following
  existing test patterns in `tests/orchestration`.

## Out of scope

- Auth, multi-tenancy, rate limiting (see "Scope and deployment
  target").
- Clickable source URLs back to ygoprodeck/ygoresources — the schema
  doesn't store real source URLs today (`rulings.source` /
  `rulebook_chunks.source` are free-text labels, not links), and
  `lookup_card` doesn't expose `ygoprodeck_id`/`ygoresources_id`. This
  would be a separate future sub-project touching ingestion and
  schema.
- Streaming/WebSocket delivery of intermediate tool-call progress
  (a "watch the assistant think" UX) — rejected in favor of simple
  two-step REST; can be revisited later behind the same Result
  contract if the frontend design calls for it.
- The React frontend itself — separate, later spec.
