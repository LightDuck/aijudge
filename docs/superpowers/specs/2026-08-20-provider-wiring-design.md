# AIJudge — Real-Provider Wiring

## Purpose

The `2026-08-20-openrouter-llm-client-design.md` doc explicitly left two
things out of scope: no entrypoint constructs a real `LLMClient` and
calls `cli.run_cli`, and no real `EmbeddingClient` exists at all
(`search_rulebook` was non-functional against real data). This
document closes both gaps. Classified as a **bounded** change
(brainstorming skill): `EmbeddingClient` already exists as an
interface with one implementation (`MockEmbeddingClient`); this adds a
second implementation behind the same `embed(text: str) -> list[float]`
contract, following the exact precedent `OpenRouterLLMClient` set for
`LLMClient`. `cli.run_cli` already exists and only needed a caller.

This is sub-project 1 of 4 identified while scoping "v1.0 with a
frontend": real-provider wiring (this doc), card coverage expansion,
an API/service layer, and the frontend itself. The other three are
separate, later brainstorming passes.

## What was built

- **`src/aijudge/embeddings/openai_client.py`** — `OpenAIEmbeddingClient`,
  implementing `EmbeddingClient` via OpenAI's embeddings endpoint
  (`POST https://api.openai.com/v1/embeddings`, model
  `text-embedding-3-small`). Follows `OpenRouterLLMClient`'s exact
  pattern: dependency-injected `http_post` defaulting to
  `requests.post`. Every request passes `"dimensions": EMBEDDING_DIM`
  (imported from `embeddings/client.py`, not redefined) — the schema's
  `rulings.embedding` and `rulebook_chunks.embedding` columns are
  hardcoded `VECTOR(384)` (`schema.sql:37,59`), while
  `text-embedding-3-small`'s native output is 1536-dim. OpenAI's
  `dimensions` parameter natively truncates via Matryoshka
  representation learning, so this matches the existing schema without
  a migration.
- **`src/aijudge/entrypoint.py`** — `build_llm_client()` /
  `build_embedding_client()` each read one required env var
  (`OPENROUTER_API_KEY`, `OPENAI_API_KEY`) via a `_require_env` helper
  that raises `RuntimeError` with a readable message (not a raw
  `KeyError`) when missing. `main()` calls `load_dotenv()` explicitly
  (entrypoint doesn't otherwise import anything that triggers it),
  builds both real clients, and calls `run_cli`.
- **`src/aijudge/__main__.py`** — thin `main()` call so
  `python -m aijudge` works.
- **`.env.example`** gained `OPENAI_API_KEY=`.

Tests: `tests/embeddings/test_openai_client.py` (mirrors
`tests/llm/test_openrouter_client.py` — request shape including
`dimensions`, model override, HTTP error propagation) and
`tests/test_entrypoint.py` (env var → correct client type and key;
missing env var → clear `RuntimeError`; `main()` smoke test with
`run_cli` monkeypatched, matching the existing "thin wiring, not
exhaustive" treatment `cli.py` itself got). `python -m aijudge` was
also manually smoke-tested end-to-end with fake keys, confirming the
CLI prompt appears and `quit` exits cleanly.

## Decisions

**Why OpenAI embeddings instead of Voyage AI or Ollama.** Brainstormed
directly with the user. Initial recommendation was Voyage AI
(retrieval-tuned, free tier, pairs with the project's
Anthropic-adjacent direction), but the user pushed back on whether
that specialization actually matters at this project's scale — a
fair challenge. At the current ~100-card corpus (a few hundred
rulebook/ruling chunks), a retrieval-tuned model's edge over a
general-purpose one is not something this project would likely
notice; a distance-threshold cutoff already does most of the
filtering work, and there's no domain-tuned "voyage-tcg" model to
exploit. The user then raised the real long-term case: Yu-Gi-Oh! has
~15k printed cards, and if this project ever ingests the full pool,
the corpus grows into the tens-of-thousands-of-chunks range, where
retrieval-quality differences (particularly disambiguating
near-duplicate rulings across textually-similar cards) become more
plausible to actually observe. That's a legitimate scaling argument
for Voyage — but full-pool ingestion is explicitly out of scope for
now (the user chose "~100 random cards from 2012–2025 as future test
subjects," not automated ingestion at scale, when this was scoped).
Given that, the user chose OpenAI: cheap, reliable, well-documented,
sufficient for the current and near-term scale. `EmbeddingClient` is a
`Protocol`, so this is not a one-way door — swapping providers later
if retrieval quality becomes a real problem at scale is possible
without touching any other module, at the cost of a one-time
re-embedding pass over whatever's already ingested by then.

**Why `dimensions=384` instead of a schema migration.** The schema's
vector columns were sized for `MockEmbeddingClient`'s 384-dim SHA256
vectors. Re-sizing them to OpenAI's native 1536 would touch
`schema.sql`, any existing embedded rows, and `rulebook_repo.py`'s
distance-threshold tuning (already calibrated against
`MockEmbeddingClient`'s scale in tests). OpenAI's `dimensions`
parameter avoids all of that — verified as a genuine native
truncation (Matryoshka representation learning), not client-side
slicing, so relevance ordering is preserved rather than degraded.

**Why `entrypoint.py` is a separate module from `cli.py` and
`__main__.py`.** `cli.py`'s `run_cli` already takes clients as
parameters and is fully unit-tested against mocks — it shouldn't need
to know how a real client gets constructed. `__main__.py` stays a
one-line shim so `python -m aijudge` works without adding any logic
that isn't already tested elsewhere. `entrypoint.py` in between owns
exactly one job — turn environment variables into real client
instances, fail readably if they're missing — and is unit-testable
without invoking the REPL loop at all.

## Explicitly out of scope (not done)

- No console-script entry point (`pyproject.toml`'s `[project.scripts]`)
  — `python -m aijudge` was judged sufficient; adding a named command
  is a trivial follow-up if wanted later, not bundled in here to keep
  this bounded.
- No card coverage expansion (~100-card ingestion), API/service layer,
  or frontend — each is a separate sub-project per the "v1.0 with a
  frontend" decomposition, to be brainstormed individually.
- No retry/backoff or rate-limit handling for either real client
  (`OpenRouterLLMClient` didn't have this either) — not addressed here
  to stay consistent with the existing precedent; would be its own
  follow-up if production usage needs it.

## Work log

- Branch: `worktree-provider-wiring` (off `dev`).
- Full test suite run green after implementation (see commit for
  count).
