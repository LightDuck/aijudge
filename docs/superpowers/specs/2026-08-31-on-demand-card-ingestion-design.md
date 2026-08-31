# AIJudge — On-Demand Card Ingestion Design

## Purpose

Today, a question about a card that isn't in `HAND_PICKED_CARDS` (or otherwise
already seeded) hits a dead end: `lookup_card` (`orchestration/tools.py`)
returns `{"found": False}`, and `seed_card()` (`ingestion/seed.py`) is only
ever invoked manually via `run_seed()` — nothing in the query path calls into
`ingestion/` at all. Per CLAUDE.md's "Not yet built" list, this was a
deliberate scope decision ("no automated ingestion pipeline beyond the
hand-picked seed list"), not an oversight.

This spec changes that: a `lookup_card` miss triggers a live fetch-and-ingest
of the unknown card via the existing `seed_card()` pipeline, so a first-ever
question about a real card has a chance of being answered instead of always
escalating.

Classified as **architectural** (brainstorming skill): this couples
`orchestration/` and `ingestion/`, two modules that don't talk to each other
today, and adds a network/LLM round-trip inside the live query path.

## Trigger point: automatic, deterministic

The ingest attempt is not a tool the LLM chooses to invoke. It happens
automatically inside `lookup_card` whenever the DB lookup misses, with no LLM
judgment involved in the decision. This matches the project's stated
philosophy (CLAUDE.md: "Anywhere LLM reasoning can be replaced with a
deterministic lookup or algorithm, it is") — a prompt-following failure can't
skip ingestion, because the LLM never decides whether to attempt it.

## Blocking model: synchronous, single round-trip

The request blocks until `seed_card()` finishes (network fetch + LLM calls
for clause-splitting and per-effect review), then answers using the freshly
ingested card in the same call. This was chosen over a background-job/polling
design because:

- It requires no new infrastructure — no job store, no background worker,
  nothing that doesn't already exist in this codebase.
- It matches the API layer's existing explicitly-stateless, no-session-store
  design (`docs/superpowers/specs/2026-08-27-api-layer-design.md`); a
  job-polling flow would cut directly against that.
- The added latency (network fetch + a handful of LLM calls) is a one-time
  cost per card, not per question — every subsequent question about the same
  card hits the DB normally.

A lighter middle ground — surfacing a progress message to the user while
still blocking on one call — is in scope (see "CLI progress message" below).
A true async job-with-polling flow is explicitly out of scope; see "Out of
scope."

## CLI progress message

Before the (potentially slow) `seed_card()` call, `lookup_card` invokes an
optional `on_ingest_start: Callable[[str], None] | None` callback with the
card name. `cli.py` wires this to `print_fn` (e.g. "Looking up Card X, this
may take a moment..."), giving the REPL user feedback before the blocking
call starts. `api/app.py` passes no callback — the HTTP request just blocks
silently, same contract as today, only slower on a cache miss.

Pushing an equivalent progress event over the HTTP API (e.g. via
Server-Sent-Events) is deferred — see "Out of scope."

## Feature toggle: `AIJUDGE_ENABLE_ONLINE_INGEST`

Read once at startup wherever other provider env vars already are
(`entrypoint.py` for the CLI, `api/__main__.py` for the API), defaulting to
`true`. This is a safety valve specifically for `entrypoint.py`'s
`OpenRouterLLMClient` wiring: that model is pinned to a free-tier listing
(`meta-llama/llama-3.3-70b-instruct:free`), which is rate-limited per
key/IP. Without a way to disable ingestion, one user repeatedly querying
nonexistent/misspelled card names (or several concurrent users doing so) can
burn through that shared rate-limit budget on ingest attempts, degrading the
LLM calls every other concurrent question on that deployment depends on. The
default `OllamaLLMClient`/`OllamaEmbeddingClient` wiring has no external rate
limit to protect (it's a local process), so the toggle carries no cost there
beyond a no-op check.

This is a restart-to-change setting, not a runtime/hot-reload toggle —
consistent with every other env var in this codebase (`OLLAMA_BASE_URL`,
`AIJUDGE_API_PORT`, etc.).

## Component design

No changes to `ingestion/seed.py` — `seed_card()` already does exactly what's
needed. All new logic lives in `orchestration/tools.py`.

### `lookup_card` signature

```python
def lookup_card(
    args: dict,
    *,
    llm_client: LLMClient | None = None,
    online_ingest_enabled: bool = False,
    fetch_card_fn: Callable[..., dict] = fetch_card,
    fetch_rulings_fn: Callable[..., list[dict]] = fetch_rulings,
    on_ingest_start: Callable[[str], None] | None = None,
) -> dict:
```

`online_ingest_enabled` defaults to `False` **on the function itself** —
deliberately, so every existing direct call to `lookup_card({"name": ...})`
(in `tests/orchestration/test_tools_db.py`) keeps passing unchanged with zero
test edits. It's `build_tool_dispatch` that defaults it *on* for real usage:

```python
def build_tool_dispatch(
    llm_client: LLMClient,
    embedding_client: EmbeddingClient,
    *,
    online_ingest_enabled: bool = True,
    on_ingest_start: Callable[[str], None] | None = None,
) -> dict[str, Callable[[dict], dict]]:
```

`build_tool_dispatch` gains a required `llm_client` parameter (previously
only `embedding_client`). `cli.py` and `api/app.py` both already construct
`llm_client` for `run_loop`, so threading it through to `build_tool_dispatch`
is a one-line change at each call site — no new wiring required.

### Data flow on a miss

```
get_card_by_name(name) -> None
  -> on_ingest_start(name)   # fires the CLI progress message; no-op for API
  -> seed_card(name, llm_client=llm_client, fetch_card_fn=..., fetch_rulings_fn=...)
       |
       +-- success -> re-fetch: get_card_by_name(name) + get_confirmed_effects(card_id)
       |              -> return {"found": True, ...}  (identical shape to the existing hit path)
       |
       +-- CardNotFoundError (ygoprodeck has no such card)
       |              -> return {"found": False}
       |
       +-- unique-violation on insert_card (a concurrent request won the race —
       |   cards.name has a UNIQUE constraint)
       |              -> re-fetch by name, use that row -> {"found": True, ...}
       |
       +-- any other exception (network timeout, ygoresources failure, etc.)
       |              -> log server-side, return {"found": False}
```

Every failure branch converges on the same `{"found": False}` shape the tool
already returns today. `loop.py` and `confidence.py` need **zero changes** —
the confidence pipeline can't distinguish "never seeded" from "we just tried
to seed it and failed," which is intentional: both look like an ordinary
miss to the existing `retrieval_gap`/`missing_structured_effect` signals.

One consequence worth stating explicitly: a newly-ingested card whose effects
don't clear the review agent's confidence threshold stays `pending` (same as
`seed_card`'s existing behavior for the hand-picked list) — `get_confirmed_effects`
returns `[]`, which trips the existing `missing_structured_effect` penalty and
likely still escalates. "Ingested" does not always mean "answerable this
turn" — sometimes it means "answerable and grounded starting next time." No
special-casing is needed for this; it falls out of existing confidence logic.

## Name resolution

The card name passed to `fetch_card_fn` is whatever the LLM extracted into
`args["name"]`, used verbatim — same as `seed_card()`'s existing usage for
the hand-picked list. No fuzzy-matching or "did you mean" layer is added for
the online fetch. A badly mismatched name will most likely surface as
`CardNotFoundError` from ygoprodeck's exact-match `name` param, which is
already handled by the "swallow and return found:false" branch above. This
is a known, accepted limitation, not a gap this feature needs to close.

## Testing

Following this codebase's existing pattern (`tests/ingestion/test_seed.py`,
`tests/orchestration/test_tools_db.py`): DB-gated tests
(`skipif DATABASE_URL not in os.environ`), fake `fetch_card_fn`/
`fetch_rulings_fn`, `MockLLMClient` with queued responses. TDD per project
convention — a failing test precedes each new behavior.

New tests in `test_tools_db.py`:
- `lookup_card` with `online_ingest_enabled=True` and a DB miss, fake
  ygoprodeck/ygoresources responses that succeed → asserts the card is
  inserted and the tool returns `{"found": True, ...}` in the same call.
- `CardNotFoundError` from `fetch_card_fn` → asserts `{"found": False}`, no
  row inserted.
- A pre-existing row with the same name (simulating the race) → asserts the
  unique-violation path re-fetches and returns the existing row rather than
  raising.
- `online_ingest_enabled=False` (the default) → asserts today's plain
  `{"found": False}`, confirming no regression.
- `on_ingest_start` callback → asserts it's called once with the card name
  before the fake fetch on a miss, and not called at all on a cache hit.

`test_tools.py` (no DB):
- Update `test_build_tool_dispatch_has_all_four_tools` for the new
  `llm_client` parameter.
- New test: with `online_ingest_enabled=False` at the dispatch-builder level,
  the resulting `lookup_card` closure never calls `seed_card` on a miss (a
  call-count assertion against a fake).

No changes needed to `tests/ingestion/test_seed.py` — `seed_card()` itself is
untouched.

CLI: a `cli.py` test asserting `print_fn` receives the progress message when
`on_ingest_start` fires. No new API test is needed for progress messaging,
since `api/app.py` passes no callback (silent, per the deferred-SSE
decision below).

Existing `test_lookup_card_returns_card_text_and_not_found_flag` stays green
untouched: it calls `lookup_card({"name": ...})` with no kwargs, and the
function-level default (`online_ingest_enabled=False`) preserves today's
behavior exactly.

## Out of scope

- **True async job-with-polling ingestion.** Would require a job store and
  background worker — infrastructure that doesn't exist anywhere in this
  codebase — and cuts against the API's current stateless, no-session-store
  design. Bigger scope than this feature; revisit only if synchronous
  latency proves unacceptable in practice.
- **Server-Sent-Events progress push for the HTTP API.** The CLI gets an
  immediate progress message via a plain callback; the API's `POST
  /questions` continues to block silently and return the final result, same
  contract as today. Adding SSE would touch the API's response contract
  (`schemas.py`, a streaming FastAPI response) — a separate, later design
  once this core ingestion path is proven.
- **Fuzzy/best-effort name matching against ygoprodeck for the online
  fetch.** Only exact-match (as `seed_card` already does) is used; a
  mismatch surfaces as an ordinary miss.
- **Rate limiting beyond the on/off toggle** (e.g. per-user or per-IP
  request throttling). `AIJUDGE_ENABLE_ONLINE_INGEST` is a blunt global
  on/off switch, not a quota system. Finer-grained throttling is a separate
  concern that would need its own design if the blunt toggle proves
  insufficient.
- **Automatically ingesting rulebook content** for a newly-fetched card.
  `seed_card()` never touched `rulebook_chunks`/embeddings, and this feature
  doesn't change that.
