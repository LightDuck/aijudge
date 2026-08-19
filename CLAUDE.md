# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

AIJudge is a Yu-Gi-Oh! TCG rules-adjudication assistant. Given a user's rules question, it answers with cited
sources or explicitly escalates to a human judge rather than hallucinate. Guiding principle: **the LLM
orchestrates and explains; the rules engine and database decide.** Anywhere LLM reasoning can be replaced with a
deterministic lookup or algorithm, it is — that's where accuracy-critical bugs live.

The project is currently mid-way through its first "thin slice": the rules engine, DB layer, effect parser, and
ingestion/seed script exist; LLM orchestration (the agentic tool-use loop) and the CLI are not wired up yet. See
`docs/superpowers/specs/2026-08-18-thin-slice-design.md` for the full design spec and
`docs/superpowers/plans/2026-08-18-foundations.md` for the implementation plan this codebase was built from
(both are useful for *why*, but the actual code is ground truth for *what exists now* — the plan doc is a
historical scaffold and has already drifted in places, e.g. `has_target`, `ygoprodeck_id NOT NULL`, and the
`SpellSpeed.COUNTER` / `prevents_response` additions below post-date it).

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

- **`embeddings/` and `llm/`** — thin `Protocol` interfaces (`EmbeddingClient.embed`, `LLMClient.complete`) with
  mock implementations (`MockEmbeddingClient` — deterministic SHA256-derived 384-dim vectors;
  `MockLLMClient` — FIFO `queue_response()`/`complete()`, raises `AssertionError` on an empty queue). No real
  provider is wired in yet; production target is Claude, with Ollama noted as a $0-cost local fallback for
  non-mock dev testing.

- **`ingestion/`** — `ygoprodeck_client.fetch_card()` and `ygoresources_client.fetch_rulings()` pull only the
  fields this project uses (not a full API mirror). `seed.py` ties it together: `seed_card()` fetches card +
  rulings, runs them through the effect parser and review agent, inserts everything, and auto-confirms if the
  review score clears threshold. `run_seed()` iterates the hand-picked `HAND_PICKED_CARDS` list (Ash Blossom &
  Joyous Spring, Called by the Grave, Infinite Impermanence, Effect Veiler, Solemn Strike) — this is a one-off
  seed script, not a scheduled ingestion pipeline (out of scope for this slice).

## Not yet built

Per the spec's non-goals / deferred list: no LLM orchestration loop (`lookup_card`/`get_rulings`/
`search_rulebook`/`resolve_chain` tool wiring), no CLI/REPL, no real LLM provider, no missing-timing check for
optional trigger effects, no automated ingestion pipeline beyond the hand-picked seed list, no formal eval harness
(an informal `qa_test_cases` table exists in the schema for this, unused so far). Don't assume these exist when
reading code — check before referencing a tool/module that spec sections 4–7 describe but that isn't under `src/`.

## Development process

TDD: a failing test precedes implementation code for every change, most importantly in the rules engine and
effect parser, where a wrong-but-confident result is the exact failure mode this project exists to avoid.
