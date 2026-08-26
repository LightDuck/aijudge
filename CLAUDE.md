# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

AIJudge is a Yu-Gi-Oh! TCG rules-adjudication assistant. Given a user's rules question, it answers with cited
sources or explicitly escalates to a human judge rather than hallucinate. Guiding principle: **the LLM
orchestrates and explains; the rules engine and database decide.** Anywhere LLM reasoning can be replaced with a
deterministic lookup or algorithm, it is — that's where accuracy-critical bugs live.

The project has completed its first "thin slice": the rules engine, DB layer, effect parser, ingestion/seed
script, LLM orchestration (the agentic tool-use loop), and a REPL CLI all exist and are tested, and
`python -m aijudge` runs end-to-end. `src/aijudge/__main__.py` wires the default, $0-cost path — a real
`OllamaLLMClient` (local Qwen3-8B via Ollama) and `MockEmbeddingClient` — since `search_rulebook` still has no
real embedding provider. `src/aijudge/entrypoint.py` is an alternate wiring using `OpenRouterLLMClient` and
`OpenAIEmbeddingClient`, reading `OPENROUTER_API_KEY` and `OPENAI_API_KEY` from the environment (`.env` via
`python-dotenv`), for when a hosted LLM is preferred over local Ollama. See
`docs/superpowers/specs/2026-08-18-thin-slice-design.md` for the full design spec and
`docs/superpowers/plans/2026-08-18-foundations.md` for the implementation plan this codebase was built from
(both are useful for *why*, but the actual code is ground truth for *what exists now* — the plan doc is a
historical scaffold and has already drifted in places, e.g. `has_target`, `ygoprodeck_id NOT NULL`, and the
`SpellSpeed.COUNTER` / `prevents_response` additions below post-date it). Provider-wiring decisions (OpenAI over
Voyage/Ollama for embeddings, the `dimensions=384` truncation to match the pgvector schema) are logged in
`docs/superpowers/specs/2026-08-20-provider-wiring-design.md`.

Still missing for a public v1.0: broader card coverage (currently 5 hand-picked cards), an HTTP/API service layer
in front of the orchestration loop (the CLI is a blocking stdin/stdout REPL, not something a web frontend can
call), and the frontend itself — each is its own separate sub-project, not yet designed.

## Commands

Install (editable, with dev deps):
```
pip install -e ".[dev]"
```

Start the DB (Postgres 16 + pgvector via Docker Compose; host port **5433**, not 5432 — check `.env`/`.env.example`
before assuming the default):
```
docker compose up -d db
cp .env.example .env   # first time only; .env is gitignored
```

Run the full test suite:
```
pytest
```

Run a single test file / test:
```
pytest tests/rules_engine/test_segoc.py -v
pytest tests/rules_engine/test_segoc.py::test_turn_player_effects_are_chained_first_and_so_resolve_last -v
```

Run migrations manually (repos call `run_migrations`-adjacent setup themselves in tests, but for a fresh DB):
```
python -c "from aijudge.db.migrate import run_migrations; run_migrations()"
```

**DB-dependent tests auto-skip when `DATABASE_URL` isn't set** (`pytestmark = pytest.mark.skipif("DATABASE_URL" not
in os.environ, ...)` at the top of each `tests/db/*` file). This means `pytest` runs green with zero setup — the
rules engine, embeddings, LLM, and effect-parser suites are pure-Python — but silently skips DB coverage if you
forget to bring Docker up. Before running anything that touches Postgres, check `DATABASE_URL` and `docker ps`
first rather than discovering the DB is down after the fact. Each DB-test module truncates its own tables in
`setup_function`, so tests assume a running instance, not a pristine one per run.

There is no lint/format command configured yet (no ruff/black/mypy config in `pyproject.toml`).

## Architecture

`src/aijudge/` is organized into independent-by-design modules, mirroring the sub-project decomposition in the
spec:

- **`rules_engine/`** — pure Python, zero DB/LLM dependency. This is the deterministic core the spec is protecting:
  - `models.py` — `EffectType`, `SpellSpeed` (NORMAL=1, QUICK=2, COUNTER=3), `Effect`, `ChainLink`.
    `spell_speed_for()` special-cases Counter Traps (Spell Speed 3) via a `card_type` check, not effect type alone.
  - `chain.py` — `Chain`: LIFO resolution order (`resolution_order()` reverses insertion order; `resolve_next()`
    pops the top).
  - `segoc.py` — `apply_segoc()`: the module the spec calls out as the most common source of wrong answers. **The
    turn player's simultaneous triggers are chained first, which — because resolution is LIFO — means they
    resolve LAST**, not first. Non-turn-player effects go on the chain second and resolve first.
  - `priority.py` — `can_activate_now()`: Spell Speed 1 can only activate into an empty chain (never responds, not
    even to another Speed-1 effect). Speed 2/3 can respond if its speed is **at or above** the top chain link's
    speed (empty chain counts as speed 0), unless the top link's effect sets `prevents_response=True`, which
    blocks all response regardless of speed.
  - `timing.py` — `check_missing_timing()`: a "when"-conditioned effect's activation window is the moment right
    after the event its condition names. At the trigger step itself, whether the window is open depends on the
    checking effect's own spell speed: Spell Speed 1 needs the last event to be a chain link fully `RESOLVED` or a
    non-chain `GAME_ACTION`; Spell Speed 2/3 needs the last event to be the matching link's `ACTIVATED` (quick
    effects can respond to an activation before it resolves). Any other last-event, or any step past trigger_step,
    means timing is missed. Only covers Quick Effects — optional-trigger missing timing is explicitly deferred.

- **`db/`** — psycopg3 + pgvector repos over `schema.sql`, one repo module per table family
  (`cards_repo`, `rulings_repo`, `effects_repo`, `rulebook_repo`). No ORM — raw SQL throughout, intentionally.
  `connection.get_connection()` loads `.env` via `python-dotenv` and calls `register_vector`, tolerating a
  `ProgrammingError` on a brand-new DB where the `vector` extension doesn't exist yet (created by
  `migrate.run_migrations()`, which just executes `schema.sql`).
  - `card_effects_structured` rows are `pending` by default; only `effects_repo.confirm_effect()` (called after
    the review agent passes threshold, or manually) makes a row visible to `get_confirmed_effect()`. **A `pending`
    effect must never be treated as ground truth** — this distinction exists at the repo level specifically so the
    future orchestration layer can't accidentally skip it.
  - Errata is never overwritten: `insert_errata_version()` adds a new `card_errata_versions` row and flips
    `cards.has_errata`; the original `card_text` stays as originally ingested.
  - `cards.ygoprodeck_id` is `NOT NULL` (always available from the source API); `ygoresources_id` is nullable
    since that API's shape is still unverified. `get_card_by_ygoprodeck_id` / `get_card_by_ygoresources_id` exist
    to reconcile the two id spaces once `ygoresources_id` starts being populated.

- **`effect_parser/`** — code-based PSCT grammar parser plus an LLM-scored confidence review step:
  - `parser.py` — `parse_psct()` splits `Condition : Cost/Target ; Effect` on the first `:` and first `;`.
    Cost/targeting splitting is two-tier: first look for a PSCT connector (`and if you do` > `then` > `also` >
    `and`, checked longest-first) and decide which side is the targeting clause by whether it contains "target";
    if no connector matches, fall back to locating the bare word "target" and checking for a cost keyword
    (banish/discard/pay/send/tribute/remove/reveal/shuffle) before it. A bare "and" is genuinely ambiguous in PSCT
    (it can separate cost from target, or join two things in one targeting clause) — the parser doesn't try to
    fully resolve this; that's what the review agent exists to catch.
    `classify_effect_type()` takes the real `card_type` string (not just an `is_monster` bool) and checks, in
    order: `(Quick Effect)` substring → QUICK/QUICK_LIKE; no `:` and no `;` anywhere → CONDITION (if "you can
    only") or CONTINUOUS; starts with "if "/"when " → TRIGGER/TRIGGER_LIKE; otherwise IGNITION for monsters, or
    for spells/traps QUICK_LIKE if `card_type` contains "Quick-Play" or "Trap" (both inherently Spell Speed 2 by
    game rule) else EFFECT.
  - `review_agent.py` — `review_parsed_effect()` sends the raw text + parsed fields to an `LLMClient`, expects a
    bare `0.0`–`1.0` confidence string back, and returns `auto_confirmed = confidence >= threshold` (default
    `DEFAULT_CONFIDENCE_THRESHOLD = 0.9`).

- **`embeddings/` and `llm/`** — thin `Protocol` interfaces (`EmbeddingClient.embed`, `LLMClient.complete`).
  `embeddings/` has `MockEmbeddingClient` (deterministic SHA256-derived 384-dim vectors) and
  `OpenAIEmbeddingClient` (real provider, `dimensions=384` truncation to match the pgvector schema — see
  `docs/superpowers/specs/2026-08-20-provider-wiring-design.md`), constructed by `entrypoint.py` only.
  `llm/` has `MockLLMClient` (FIFO `queue_response()`/`complete()`, raises `AssertionError` on an empty queue),
  `OpenRouterLLMClient` (hosted, pinned to a specific free model — see
  `docs/superpowers/specs/2026-08-20-openrouter-llm-client-design.md`), and `OllamaLLMClient` — a local Qwen3-8B
  client via Ollama's HTTP API, $0 cost, no API key. `OllamaLLMClient` is the one `python -m aijudge` /
  `aijudge.__main__.main()` constructs by default (`OLLAMA_BASE_URL` / `OLLAMA_MODEL` env vars, default
  `http://localhost:11434` / `qwen3:8b`); it disables Qwen's thinking mode and strips any `<think>...</think>`
  block defensively, since `run_loop`'s protocol parses an exact `TOOL:`/`FINAL:` text format that a reasoning
  preamble would break. Claude remains the eventual production target per the original spec, not yet wired in.

- **`orchestration/`** — the agentic tool-use loop that turns a user question into an answer, escalation, or
  "not supported":
  - `protocol.py` — `build_system_prompt()` describes the `TOOL: <name> {json}` / `FINAL: <text>||CITES:
    id1, id2||` response format the LLM must follow; `parse_response()` parses one into a `ToolCall` or
    `FinalAnswer`, raising `ProtocolError` on anything else (missing prefix, bad JSON, unknown tool, malformed or
    missing `||CITES: ...||` trailer).
  - `tools.py` — `build_tool_dispatch()` wires the DB/embedding-backed tool implementations
    (`lookup_card`, `get_rulings`, `search_rulebook`, `resolve_chain`) into the `{name: callable}` dict the loop
    dispatches against. `resolve_chain` delegates to `rules_engine.resolve.resolve_chain`, which raises
    `UnsupportedScenarioError` for step kinds it doesn't recognize.
  - `confidence.py` — `compute_confidence()`: starts at `1.0`, returns `0.0` outright if the answer cites an id
    no tool result actually surfaced (`known_ids`), otherwise subtracts `RETRIEVAL_GAP_PENALTY` (0.3) if any
    `get_rulings`/`search_rulebook` call came back empty and `MISSING_STRUCTURED_EFFECT_PENALTY` (0.2) if a
    looked-up card had no `confirmed_effect`. `update_signals()` accumulates these signals per tool call.
  - `loop.py` — `run_loop()`: repeatedly calls the LLM, dispatches `ToolCall`s and folds results back into the
    conversation, and on a `FinalAnswer` scores it via `compute_confidence()` against `threshold` (default
    `DEFAULT_CONFIDENCE_THRESHOLD = 0.9`) — below threshold escalates instead of answering. Malformed
    LLM responses or tool-arg errors (`KeyError`/`ValueError`/`TypeError`) get fed back as `ERROR:` context, capped
    at `MAX_MALFORMED_RETRIES = 3`; total tool calls are capped at `MAX_TOOL_CALLS = 10`. Either cap, or an
    `UnsupportedScenarioError` from `resolve_chain`, ends the loop with `kind="not_supported"` rather than looping
    forever or guessing.
  - `clarify.py` — a pre-loop pass: `build_clarification_prompt()` asks the LLM whether the question is
    ambiguous or hinges on an unobservable continuous/lingering effect; `parse_clarification_response()` turns
    `CLARIFY:`/`CONTINUOUS_CHECK:` lines into `ClarificationItem`s (or an empty list on `PROCEED`);
    `format_clarification_context()` folds the user's answers back into context passed to `run_loop`.

- **`cli.py`** — `run_cli()`: a REPL (`input_fn`/`print_fn` are injectable for testing) that, per question, runs
  the clarification pass, prompts for answers to any `CLARIFY`/`CONTINUOUS_CHECK` items, then calls `run_loop`
  and prints the result. Wired to a real entrypoint by both `__main__.py` (Ollama, default) and `entrypoint.py`
  (OpenRouter/OpenAI, alternate).

- **`ingestion/`** — `ygoprodeck_client.fetch_card()` and `ygoresources_client.fetch_rulings()` pull only the
  fields this project uses (not a full API mirror). `seed.py` ties it together: `seed_card()` fetches card +
  rulings, runs them through the effect parser and review agent, inserts everything, and auto-confirms if the
  review score clears threshold. `run_seed()` iterates the hand-picked `HAND_PICKED_CARDS` list (Ash Blossom &
  Joyous Spring, Called by the Grave, Infinite Impermanence, Effect Veiler, Solemn Strike) — this is a one-off
  seed script, not a scheduled ingestion pipeline (out of scope for this slice).

## Not yet built

Per the spec's non-goals / deferred list: no missing-timing check for optional trigger effects, no automated
ingestion pipeline beyond the hand-picked seed list, no structured-output protocol for the orchestration loop, no
formal eval harness (an informal `qa_test_cases` table exists in the schema for this, unused so far). The default
`python -m aijudge` path (`__main__.py`) still uses `MockEmbeddingClient`, so `search_rulebook` returns nothing
useful there — a real embedding provider (`OpenAIEmbeddingClient`) exists but is only wired through the alternate
`entrypoint.py` path, not the default one. Don't assume these exist when reading code — check before referencing
a tool/module that spec sections 4–7 describe but that isn't under `src/`.

## Development process

TDD: a failing test precedes implementation code for every change, most importantly in the rules engine and
effect parser, where a wrong-but-confident result is the exact failure mode this project exists to avoid.
