# AIJudge — Thin Slice (v0) Design

## Purpose

AIJudge is a Yu-Gi-Oh! TCG rules-adjudication assistant. A user asks a
question — card text lookup ("what does [card] do?"), an interaction
check ("can Z be activated given X and Y?"), or a chain-resolution
question ("we're on chain link 5, how does chain link 2 resolve?") —
and the system answers with cited sources, or explicitly tells the
user to escalate to a human judge rather than hallucinate.

The project's guiding principle: **the LLM orchestrates and explains;
the rules engine and database decide.** Anywhere LLM reasoning can be
replaced with a deterministic lookup or algorithm, it is — that's
where the accuracy-critical bugs live.

Eventually this is meant to be shared/public, but this document scopes
only the first, thin, end-to-end slice built to validate the core
trust mechanism cheaply.

## Scope decomposition

The full system decomposes into independent sub-projects:

1. Data layer & ingestion (this doc covers a minimal hand-picked slice
   of it)
2. Retrieval layer (this doc covers a minimal slice)
3. Rules engine (this doc covers chain/SEGOC/timing/priority; missing
   timing for *optional trigger* effects deferred)
4. LLM orchestration (this doc covers it, LLM calls mocked initially)
5. Frontend — **out of scope for this slice** (CLI only)
6. Full automated ingestion pipeline / eval harness at scale — **out
   of scope for this slice** (informal, manually-fed test set instead)

This document specs sub-project 1 as a thin, hand-picked-card vertical
slice through 1–4, enough to prove the retrieval + rules engine +
citation + escalation mechanism actually works before investing in
full ingestion automation, the rules engine's remaining edge cases, or
a frontend.

## Non-goals for this slice

- No frontend — CLI only.
- No automated/scheduled ingestion pipeline — a one-off seed script
  for a hand-picked card set.
- No production LLM wiring — LLM calls sit behind a mockable
  interface; a real provider is plugged in later.
- No missing-timing check for *optional trigger* effects (only quick
  effects, per current scope).
- No multi-user/auth concerns, despite the eventual public goal.

## Components

- **Data layer**: Postgres + pgvector, run via Docker Compose.
- **Seed script**: one-off ingestion for the hand-picked card set —
  card text from the YGOPRODeck API, rulings from db.ygoresources, and
  Konami's official rulebook / PSCT guide chunked for embedding.
- **Effect parser**: code-based parser that splits `card_text` into
  structured fields using PSCT's formal grammar (`Condition : Cost /
  Target ; Effect`).
- **Effect-parse review agent**: an LLM call that scores the parser's
  output against the raw text; above threshold auto-confirms, below
  threshold queues for manual human review.
- **Rules engine**: pure Python module, no LLM or DB dependency —
  chain building, LIFO + SEGOC resolution order, effect-type
  awareness, priority/spell-speed windows, missing-timing checks for
  quick effects.
- **Retrieval layer**: exact lookups (`get_card`, `get_rulings`) with
  live API fallback-and-cache on a local-DB miss, plus vector search
  over rulebook/PSCT chunks for conceptual questions.
- **LLM orchestration**: an agentic tool-use loop behind a swappable
  `LLMClient` interface (mock implementation now; Claude is the target
  production provider; Ollama with a local open-weight model noted as
  a genuinely $0-cost fallback if a non-mock model is wanted during
  dev). Tools: `lookup_card`, `get_rulings`, `search_rulebook`,
  `resolve_chain`, `ask_continuous_effect_status`.
- **CLI**: a REPL loop — question in, clarification/continuous-effect
  back-and-forth as needed, cited answer or escalation message out.

## Data flow

1. User types a free-text question into the CLI.
2. Orchestrator checks whether the question is specific enough (right
   card names, unambiguous scenario); if not, it asks the user for
   clarification before proceeding.
3. Orchestrator sends the clarified question to the LLM with the tool
   set available.
4. LLM gathers information as needed:
   - `lookup_card` / `get_rulings` — local DB first, live API
     fetch-and-cache on a miss.
   - `search_rulebook` — vector search for conceptual/procedural
     questions.
   - `ask_continuous_effect_status` — asks the user whether a
     continuous/lingering effect is currently active, since the app
     cannot observe board state.
5. If the question involves chain links, timing, or "can X be
   activated," this is detected before the LLM may finalize an
   answer, and the LLM is code-enforced to parse the described game
   state into structured chain input and call `resolve_chain`. The
   rules engine's deterministic result is authoritative; the LLM
   cannot substitute its own reasoning here.
6. LLM synthesizes a final answer, citing the specific card/ruling/
   rulebook-chunk ID behind every claim.
7. Orchestrator gates the response:
   - Rules engine hit a case it doesn't implement yet → **"not
     supported yet, contact dev team"** (checked first — this is a
     missing-capability problem, not a confidence problem).
   - Answer assembled but confidence is low → **"escalate to a human
     judge"**.
   - Otherwise → return the cited answer.

## Data schema

### `cards`
- `id`, `name`, `card_text` (raw PSCT as printed)
- `card_type` (open string, not an enum — e.g. "Effect Monster",
  "Fusion Monster", "Quick-Play Spell", "Continuous Trap")
- `attribute` (monsters: DARK/LIGHT/etc.; spells/traps: subtype —
  normal/continuous/quick-play/equip/field/counter for spells,
  normal/continuous/counter for traps)
- `type` (monster-only: Dragon/Spellcaster/Warrior/etc.)
- `level`, `rank`, `link`, `archetype`, `atk`, `def` (monster-only
  fields)
- external ids from both YGOPRODeck and db.ygoresources, to reconcile
  cases where the two sources disagree on identity
- `source` (ygoprodeck), `fetched_at` (date only, DD/MM/YYYY)
- `has_errata` flag + relation to `card_errata_versions`
- `card_materials` (fusion/synchro/xyz/link material requirements
  text)

### `card_errata_versions`
- relation to card, errata date, errata text (never overwrite the
  original — new row per errata). This versioned-relation pattern is
  reusable for other future needs.

### `rulings`
- `id`, `card_id`, `ruling_text`, `source` (db.ygoresources), `date`,
  embedding (pgvector) for semantic search.

### `card_effects_structured`
- relation to the specific `card_text` it was parsed from
- `effect_type`:
  - monster → trigger / ignition / quick / continuous / unclassified
    / condition
  - spell-trap → effect / trigger-like / continuous / quick-like /
    condition
- `activation_condition` (text before the colon; null if none —
  mainly relevant for ignition/trigger/quick/trigger-like/quick-like)
- `cost` (between colon and semicolon; e.g. "banish 10 cards from the
  top of your deck")
- `targeting` (between colon and semicolon; null if the effect has no
  targeting)
- `effect` (everything after the semicolon)
- `status` (`pending` / `confirmed`), set by the effect-parse review
  agent's confidence score against a configurable threshold (default
  ~90–95%)
- more fields to be added later in dev

Known parsing trap to build test cases against: PSCT's structural
"and" (separating listed conditions/costs) versus a natural-language
"and" that a naive parser could misread — this must be covered by
both the code parser's test suite and the review agent's scoring
cases.

### `rulebook_chunks`
- `chunk_text`, `source` (Konami rulebook/PSCT guide), section
  reference, embedding (pgvector).

### `qa_test_cases`
- Informal, growing set of question/expected-answer/citation/notes
  entries fed in manually over time — not a blocking gate for this
  slice.

Continuous/lingering-effect board state is never stored — it's asked
interactively via `ask_continuous_effect_status` each session.

## Orchestration confidence & escalation logic

The final answer synthesis step produces an LLM confidence score based
on concrete signals, not vibes:

- citation coverage — every claim traced to a specific source
- whether any structured effect used was still `pending` rather than
  `confirmed`
- whether retrieval returned gaps or ambiguity
- for chain questions, whether `resolve_chain` completed cleanly

Below the confidence threshold → escalate to a human judge. A
rules-engine case with no handling at all is checked *before* the
confidence score is even computed and produces the distinct "not
supported yet, contact dev team" message, since it's not a confidence
problem — the capability doesn't exist yet.

The effect-parse review agent uses the same confidence-score pattern:
code parses `card_text` deterministically off PSCT's grammar, then an
LLM call scores that parse against the raw text; ≥ threshold
auto-confirms, below threshold queues for human review.

## Testing

- **Rules engine**: unit tests independent of LLM/DB. SEGOC ordering
  gets its own dedicated suite (the "turn player chains first =
  resolves last" rule is unintuitive and a common source of wrong
  answers). Also: PSCT-"and" parsing edge cases, missing-timing checks
  for quick effects.
- **Effect parser + review agent**: test cases built from the
  hand-picked cards, including at least one deliberately ambiguous
  "and" case, to verify it lands in human review rather than
  false-auto-confirming.
- **End-to-end**: the informal, growing Q&A set run against the mock
  `LLMClient` for repeatable regression checking, and manually against
  a real model once one is plugged in.

## Tech stack

| Layer | Choice |
|---|---|
| Backend | Python |
| Structured + vector DB | Postgres + pgvector (Docker Compose) |
| Rules engine | Custom Python module, no external dependencies |
| LLM | Behind a mockable `LLMClient` interface; Claude is the target production provider; Ollama (local open-weight model) noted as a $0-cost fallback for non-mock dev testing |
| Interface | CLI (REPL) |
| Card data source | YGOPRODeck API |
| Ruling data source | db.ygoresources |
| Rulebook / PSCT reference | Konami official documents |

## Deferred to later sub-project specs

- Frontend (chat UI)
- Automated/scheduled ingestion pipeline with versioning and
  diff-against-official verification
- Full competitive card pool structuring (beyond the hand-picked set)
- Missing-timing checks for optional trigger effects
- Formal regression-blocking eval harness at scale
- Production LLM wiring (real Claude API key, cost/latency tuning)
