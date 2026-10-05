# Rulings Grounding (Step A) — Design

**Date:** 2026-10-05
**Status:** proposed

## Problem

The answering turn runs `run_loop` with `tools={}` and `protocol.build_answering_system_prompt()`. That fixed
ungrounded, memory-based answers, but it also means the official rulings already in the database never reach an
answer: the only thing that ever read them was the `get_rulings` tool, which the final turn no longer has.

The data is there. Every card that `seed_card()` ingests (the seed script and the on-demand `lookup_card` path
alike) also stores its ygoresources Q&As in `rulings`: 65 rows today across the 10 seeded cards (The Prime Monarch
14, Digitron 1). They're stored and unused.

This is the first of three planned steps that move more deterministic facts into the pre-loop KNOWN FACTS context
instead of giving the LLM tools: **A — rulings** (this spec), B — rulebook excerpts, C — a deterministic chain
resolution. B and C get their own specs.

Four facts about the current data shape this design:

1. **Stored ruling texts are unreadable to the LLM as-is.** ygoresources writes card references as Konami-id
   placeholders: `Q: I activate the second effect of <<13174>>, targeting an <<8963>> on my field. If my opponent
   chains <<5505>> ...`. Injected verbatim, the model can't tell which cards a ruling is about.
2. **Those placeholders are also exact structured data.** A ruling that contains `<<id>>` for *another card in the
   same question* is almost certainly the relevant one. That gives a deterministic relevance signal with no
   embeddings.
3. **Rulings are long:** 182–3,243 characters, 806 on average; The Prime Monarch's 14 total about 11,000.
   `OllamaLLMClient` sends no `num_ctx`, so Ollama uses its default context window and silently drops the start of
   an overlong prompt. A size budget is mandatory.
4. **A failed rulings fetch is indistinguishable from "this card has no rulings".** `seed.py` wraps
   `fetch_rulings_fn` in `except Exception: rulings = []`, and the Konami id is never stored
   (`card.ygoresources_id` is `NULL` for all 10 cards), so nothing can retry it later.

## Goals and success criteria

- For every card grounded in KNOWN FACTS (seeded or ingested on demand), its most relevant stored rulings are
  rendered into the answering context, with card names in place of the `<<id>>` placeholders.
- The model can cite a ruling as `ruling:<id>`, and `compute_confidence` treats that id as known (not fabricated).
- Nothing is fetched over the network at answer time.
- The prompt stays inside an explicit character budget and an explicit Ollama `num_ctx`.
- A card with no rulings is not penalized; a card whose rulings fetch actually **failed** is.

## Decisions (agreed with the user)

| Question | Decision |
|---|---|
| Card has zero stored rulings | **No confidence penalty.** Zero Q&As on ygoresources is complete data, not a retrieval miss; the answer still rests on the card's KNOWN FACTS. |
| Rulings fetch failed at ingestion | **Recorded** (`card.rulings_status = 'failed'`) and counted as a retrieval gap (−0.3 → below the 0.75 threshold → escalate). The Konami id is stored so a later run can refetch. |
| Where `<<id>>` placeholders are resolved | **At ingestion, keeping both**: the raw `ruling_text` is never modified (same principle as errata); a new `ruling_text_resolved` column holds the readable form, and `referenced_konami_ids` holds the parsed ids. One backfill covers existing rows. |
| How rulings are selected | **Deterministic rank + character budget**: rulings that reference another card in the question first, then newest first; included whole until the budget is spent. |

## Scope

In scope:

1. Schema: `card.rulings_status`, `rulings.ruling_text_resolved`, `rulings.referenced_konami_ids`; populate the
   existing `card.ygoresources_id`.
2. Ingestion: a ygoresources name index, a placeholder resolver, and fetch-status recording in `seed_card()`.
3. A re-runnable backfill for cards and rulings ingested before this change.
4. A new `orchestration/rulings_context.py` that selects and renders rulings for a question's grounded cards.
5. Wiring at the three places that assemble answering context (`cli.py`, `api/app.py`,
   `card_effect_pipeline.py`), citation registration in `confidence.update_signals`, and a prompt update.
6. An explicit Ollama `num_ctx`.

Out of scope: `verify.py` checking the answer against rulings (it still checks structured effects only); rulebook
excerpts (Step B); embedding-based ruling relevance; the chain engine (Step C); re-enabling the `get_rulings` tool.

## Data model

All changes go in `schema.sql`, idempotent, following the existing `ADD COLUMN IF NOT EXISTS` pattern and the
`DO $$ ... $$` guard used for `card_race_check`:

```sql
ALTER TABLE card ADD COLUMN IF NOT EXISTS rulings_status TEXT;
-- guarded like card_race_check:
ALTER TABLE card ADD CONSTRAINT card_rulings_status_check
    CHECK (rulings_status IN ('fetched', 'failed', 'no_konami_id') OR rulings_status IS NULL);

ALTER TABLE rulings ADD COLUMN IF NOT EXISTS ruling_text_resolved TEXT;
ALTER TABLE rulings ADD COLUMN IF NOT EXISTS referenced_konami_ids INTEGER[] NOT NULL DEFAULT '{}';
```

- **`card.rulings_status`**: `fetched` (the ygoresources call succeeded, whether or not it returned any Q&As),
  `failed` (the call raised), `no_konami_id` (YGOPRODeck gave no Konami id, so there was nothing to fetch). `NULL`
  means a row created before this change that the backfill hasn't reached yet; it is treated like `fetched` (no
  penalty) so existing data doesn't start escalating the moment the migration runs.
- **`card.ygoresources_id`** (already exists, `TEXT`, nullable, unused) now stores the Konami id that
  `seed_card()` already reads from `misc_info[0].konami_id`. That's the id ygoresources uses, so the existing
  `get_card_by_ygoresources_id` lookup finally has data behind it.
- **`rulings.ruling_text_resolved`**: `ruling_text` with every `<<id>>` replaced by that card's English name.
  `NULL` when resolution hasn't run or the name index was unavailable; renderers then fall back to the raw text
  (see Component 4).
- **`rulings.referenced_konami_ids`**: every distinct id parsed from the placeholders, in first-appearance order.
  Filled even when name resolution fails, since parsing needs no network.

## Components

### 1. `ingestion/ygoresources_client.py`: name index and placeholder resolver

- **`fetch_card_name_index(*, http_get=requests.get) -> dict[int, list[str]]`**: GETs
  `https://db.ygoresources.com/data/idx/card/name/en` (one ~520 KB JSON object of `{name: [konami_id, ...]}`,
  17,187 entries when checked on 2026-10-05) and inverts it to `{konami_id: [name, ...]}`. Checked examples:
  13174 → `Amazoness Call`, 8963 → `Amazoness Queen`, 5505 → `Enemy Controller`.
- **Renamed cards map to several names** (6845 → `Cyber Angel - Benten`, `Cyber Angel Benten`). For such an id the
  resolver asks `/data/card/{id}` for its current `cardData.en.name`, the authoritative single name. This is the
  rare case, so it stays a per-id call rather than a bulk one.
- **`resolve_ruling_text(text, name_index, *, http_get=requests.get) -> tuple[str, list[int]]`**: replaces each
  `<<digits>>` with the resolved name and returns the new text plus the ordered distinct ids. An id missing from
  the index (or whose `/data/card` call fails) becomes `[card #13174]`, never a guessed name, so the LLM sees that a
  card is unknown rather than a wrong one.
- **`parse_referenced_ids(text) -> list[int]`**: the network-free half of the above, used on its own when the index
  can't be fetched.
- A module-level `functools.lru_cache(maxsize=1)` wrapper, mirroring `tools._cached_fetch_sets_index`, keeps the
  index to one download per process for the on-demand ingestion path.

### 2. `ingestion/seed.py`: record the fetch outcome

`seed_card()` gains `fetch_card_name_index_fn` (defaulting to the cached wrapper) and changes its rulings section to:

- `konami_id is None` → `rulings_status = 'no_konami_id'`, no fetch.
- `fetch_rulings_fn` raises → `rulings_status = 'failed'`, nothing inserted. The exception is logged with
  `logger.exception` rather than silently swallowed as it is today.
- Otherwise `rulings_status = 'fetched'`, and each ruling is inserted with its `ruling_text_resolved` and
  `referenced_konami_ids` filled. If the name index itself can't be fetched, rulings are still inserted with
  `ruling_text_resolved = NULL` and ids from `parse_referenced_ids`, and the status stays `fetched`: the Q&As were
  retrieved, only their display form is pending, and the backfill can complete it later.
- `insert_card` receives `ygoresources_id=str(konami_id)` when known and the resulting `rulings_status`.

### 3. `ingestion/rulings_backfill.py` (new module)

`backfill_rulings(*, fetch_card_fn=..., fetch_rulings_fn=..., fetch_card_name_index_fn=...) -> BackfillReport`,
re-runnable and safe to run any number of times:

1. For each card whose `ygoresources_id` is `NULL`: fetch it from YGOPRODeck by passcode (`fetch_card`, field
   `id`), store the Konami id, or set `rulings_status = 'no_konami_id'` if there is none.
2. For each card whose `rulings_status` is `NULL` or `'failed'`:
   - if it has **zero** stored rulings, re-fetch and insert them (the old zero may have been a swallowed failure),
     setting `fetched` or `failed` from the outcome;
   - if it already has rulings, set `fetched` without re-fetching. Re-inserting would duplicate rows, and the
     existing rows prove the original fetch worked.
3. For every ruling whose `ruling_text_resolved` is `NULL`: resolve it and update both new columns.

It never deletes or rewrites `ruling_text`. `BackfillReport` counts cards updated, rulings refetched, rulings
resolved, and failures, for the operator to read. Run it once after `run_migrations()`; like the other seed scripts
it is a manual operation, not a startup step.

### 4. `db/` repo changes

- `cards_repo`: `insert_card` gains `rulings_status`; the shared column list gains `rulings_status` so every card
  dict carries it (`card_resolution` re-fetches via `get_card_by_id`, and `preflight` reads cards via
  `get_card_by_name`, so both get it for free); new `set_card_rulings_source(card_id, *, ygoresources_id=None,
  rulings_status)` for the seed/backfill updates.
- `rulings_repo`: `insert_ruling` gains `ruling_text_resolved=None, referenced_konami_ids=()`;
  `get_rulings_for_card` also returns both new columns; new `update_ruling_resolution(ruling_id, *,
  ruling_text_resolved, referenced_konami_ids)` and `list_unresolved_rulings()` for the backfill.

### 5. `orchestration/rulings_context.py` (new module): select and render

```python
DEFAULT_RULINGS_BUDGET_CHARS = 6000

@dataclass
class RulingsGrounding:
    context: str                                   # "" when there is nothing to say
    rulings_by_card_id: dict[str, list[dict]]      # the rulings actually rendered, per card

def build_rulings_grounding(cards: list[dict], *, budget_chars: int = DEFAULT_RULINGS_BUDGET_CHARS) -> RulingsGrounding
```

It takes **all** of a question's grounded cards at once, because ranking depends on which other cards are present.
Selection is fully deterministic:

1. **Load** each card's rulings via `get_rulings_for_card` (imported at module level so tests stub it with
   `monkeypatch`, as `preflight` does with `get_confirmed_effects`).
2. **Rank** each card's rulings by, in order:
   1. references another grounded card: `referenced_konami_ids` intersects the other cards' `ygoresources_id`s;
   2. `ruling_date` descending, with `NULL` dates last;
   3. `id`, for a stable tie-break.
3. **Dedupe**: a Q&A stored under two of the grounded cards (identical `ruling_text`) is rendered once, under the
   first card in the given order.
4. **Budget**: each card gets `budget_chars // len(cards)`. Rulings are taken whole, in rank order, while they fit
   the card's share; **a ruling is never truncated**, because a cut could drop its `A:` half. A ruling that doesn't
   fit is skipped and the next one is tried. Unused share from all cards is then pooled and offered, in card order,
   to the rulings each card skipped. The size counted is the rendered line's length.
5. **Render** one block, placed after all KNOWN FACTS blocks:

```
RULINGS (official Q&A from db.ygoresources -- do not contradict. A ruling applies only when the question's
situation matches it. Cite each ruling you rely on as ruling:<id>.):
- ruling:<uuid> (Amazoness Call, 2025-07-13): Q: ... A: ...
- Amazoness Call: 1 more ruling not shown (context budget).
- Digitron: no official rulings on record.
- Pot of Desires: rulings could not be retrieved -- do not guess what they say.
```

   Text comes from `ruling_text_resolved`, or, when that is `NULL`, from `ruling_text` with each `<<id>>` rewritten
   to `[card #id]` (never a bare `<<id>>`). The "no official rulings on record" line exists so the model doesn't
   invent one; the "could not be retrieved" line mirrors `card_effect_pipeline`'s LOOKUP FAILURES wording.
   `context` is `""` only when `cards` is empty.

### 6. Citation registration and the retrieval gap (`preflight`, `confidence`)

- `preflight.build_grounded_result(card, *, rulings=())` adds `"rulings": list(rulings)` and
  `"rulings_status": card.get("rulings_status")` to the dict it returns.
- `confidence.update_signals`, in its existing `lookup_card` branch, then:
  - registers each `ruling:<id>` in `known_ids` and `citation_index` with label
    `"Official Q&A — <card name> (<date or 'undated'>)"` and the rendered text, so API responses show a readable
    citation;
  - sets `retrieval_gap = True` only when `rulings_status == "failed"`.

  The real `lookup_card` tool result (`tools._card_result`) carries neither key, so tool-path behavior is unchanged.
  `run_loop` already feeds every `grounded_cards` entry through this branch, so **it needs no new parameters**.
- The `get_rulings` branch (empty → gap) is left as is. It's only reachable through the tool, which the answering
  turn doesn't offer.

### 7. Wiring at the three context-assembly points

`cli.py`, `api/app.py` (both `post_questions` and `post_answer`) and `card_effect_pipeline.resolve_card_effect_question`
each, once the grounded cards are known:

```python
grounding = build_rulings_grounding_fn(cards)
context = "\n\n".join([*known_facts_blocks, grounding.context])  # empty parts skipped
grounded_cards = [build_grounded_result_fn(c, rulings=grounding.rulings_by_card_id.get(c["id"], [])) for c in cards]
```

`build_rulings_grounding_fn` is injectable in `run_cli` and `create_app`, defaulting to
`rulings_context.build_rulings_grounding`, like the existing `build_known_facts_context_fn`. In
`card_effect_pipeline`, the LOOKUP FAILURES block stays last, after the rulings block, and only `"resolved"`
resolutions contribute cards. A card whose KNOWN FACTS block is `""` (no confirmed effects) still gets its rulings:
rulings don't depend on the effect parser.

### 8. Prompt (`protocol.build_answering_system_prompt`)

Add: the RULINGS block is official Konami Q&A; prefer it over your own reasoning when its situation matches the
question; don't apply a ruling whose situation differs; cite each one used as `ruling:<id>`. The `||CITES: ...||`
instruction changes from "(card:<id>)" to "(card:<id> or ruling:<id>)". `parse_response` already accepts any id
string, so no parser change is needed.

### 9. `llm/client.py`: explicit context window

`OllamaLLMClient` gains `num_ctx: int`, read from `OLLAMA_NUM_CTX` (default `8192`) where it's constructed
(`__main__.py`, `api/__main__.py`), and sends it as `"options": {"num_ctx": ...}` on both its `/api/chat` and
`/api/generate` requests. 6,000 characters of rulings is roughly 1,500–2,000 tokens; with the system prompt and
several KNOWN FACTS blocks this fits in 8,192 with room for the answer.

## Testing approach

Test-first, per this repo's TDD rule. Fixtures use **real** cards, passcodes, Konami ids and ruling texts (copied
from the stored rows above or fetched from ygoresources), never invented ones.

- **`ygoresources_client`**: index inversion on a real slice of `/data/idx/card/name/en`; `resolve_ruling_text` on
  a real Amazoness Call Q&A (13174, 8963, 5505); a renamed id (6845) resolved through a stubbed `/data/card/6845`;
  an unknown id rendered as `[card #id]`; `parse_referenced_ids` order and dedupe.
- **`seed_card`**: each status (`fetched` with rulings, `fetched` with zero, `failed`, `no_konami_id`); Konami id
  stored in `ygoresources_id`; index outage → `ruling_text_resolved` `NULL` and ids still filled.
- **`rulings_backfill`** (DB test): a pre-change card with zero rulings is re-fetched; one with rulings is marked
  `fetched` without duplicates; unresolved rulings get resolved; a second run changes nothing.
- **`rulings_context`** (pure, repo stubbed): cross-reference ranking beats recency; `NULL` dates last; budget split,
  pooled leftover, no truncation, skip-and-continue; dedupe across cards; the "no rulings", "not shown" and
  "could not be retrieved" lines; fallback to `[card #id]` when unresolved.
- **`confidence.update_signals`**: grounded rulings become known, citable ids with readable labels; gap only on
  `failed`; zero rulings and `NULL` status leave the score at 1.0.
- **Wiring**: `cli.py` and `api/app.py` tests assert the rulings block reaches `run_loop`'s
  `clarification_context` and the ruling ids reach `grounded_cards`, via the injected
  `build_rulings_grounding_fn`; `card_effect_pipeline` likewise, with LOOKUP FAILURES still last.
- **DB tests** for the new columns, the CHECK constraint and the repo functions, under `TEST_DATABASE_URL` with the
  usual skip marker.
- **`OllamaLLMClient`**: `num_ctx` present in both request payloads.

## Rollout

1. Merge; `run_migrations()` runs automatically at startup and adds the columns. Until the backfill runs, existing
   rulings render with `[card #id]` placeholders and every existing card is `NULL` status (no penalty).
2. Run the backfill once against the app database:
   `python -c "from aijudge.ingestion.rulings_backfill import backfill_rulings; print(backfill_rulings())"`.
3. Update CLAUDE.md's `db/`, `ingestion/` and `orchestration/` sections, and correct its stated confidence threshold
   (the code's `DEFAULT_CONFIDENCE_THRESHOLD` is `0.75`, not `0.9`).

## Explicitly deferred

- **Verifying answers against rulings.** `verify.py` still checks only structured effects. An answer that
  misapplies an injected ruling isn't caught yet.
- **Relevance beyond cross-references.** A question naming one card gets its newest rulings, not necessarily the
  ones about the situation asked. Embedding or LLM-based ranking would address that and belongs with Step B's
  embedding decision.
- **Refreshing rulings over time.** New Q&As published after a card was ingested aren't picked up; there's no
  scheduled re-fetch, consistent with the project's "no automated ingestion pipeline" non-goal.
- **Rulings for cards that failed to resolve** (LOOKUP FAILURES): there's no card row, so there are no rulings.
