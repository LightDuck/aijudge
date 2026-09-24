# Card Bullet Categories (`card_bulleted`) — Design

**Date:** 2026-09-24
**Status:** proposed

## Problem

Many cards list part of their effect as `●` bullets, and the bullets mean different things depending on the card:
pick exactly 1 at activation, apply every bullet the card's criteria select, a bundle of effects granted all
together, independent effects that are only formatted as a list, and so on. `bullet_category` (13 rows, `A1`–`Z`)
already defines these readings. Nothing yet says **which** reading applies to **which** card, so the LLM infers it
from the wording every time. That's guessing on a rules question, which is exactly what this project is built to
replace with a deterministic lookup.

The categorization already exists: the "Bulleted Effects Review" artifact
(`https://claude.ai/artifact/YDX8ux6UVwJ1cK3ZjchskV`) holds 984 YGOPRODeck cards printed since 2012-01-01 that
have a `●` list. A first automated sort placed every card, and the user then reviewed all 984 by hand: 871 kept
the automated category and 113 were moved. That work currently lives only in the artifact's database
(`review/state_v2`). This design moves it into Postgres and uses it to ground answers.

## Scope

In scope:

1. A new `card_bulleted` table linking a card's passcode to its `bullet_category`, with a per-card reason and note.
2. A one-off export of the artifact's 984 reviewed placements into a committed JSON fixture, with passcodes
   resolved.
3. A seed function that loads the fixture into `card_bulleted`, idempotently.
4. A repo module to read a card's bullet category by passcode.
5. Adding the card's bullet category to `preflight.build_known_facts_context`'s KNOWN FACTS block.

Out of scope: categorizing cards outside the 984 (printed before 2012, or released after the survey), any
automated bullet classifier, and changes to `bullet_category`'s definitions.

## Data model

```sql
CREATE TABLE IF NOT EXISTS card_bulleted (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bullet_category_id UUID NOT NULL REFERENCES bullet_category (id),
    ygoprodeck_id TEXT NOT NULL UNIQUE,
    reason TEXT,
    note TEXT
);
```

- **`ygoprodeck_id`** is the card's printed 8-digit passcode, the same value and column name as
  `card.ygoprodeck_id`, but **deliberately not a foreign key to `card`**. Only 10 cards are in `card` today, and
  974 of the 984 reviewed cards aren't among them. Keying on the passcode also means a card ingested later (seed,
  or the on-demand online lookup) is covered automatically, with no backfill step: the join is simply
  `card.ygoprodeck_id = card_bulleted.ygoprodeck_id`. It's `UNIQUE` so one card can't carry two categories, and
  every write goes through `cards_repo.normalize_passcode` so the leading-zero bug fixed in PR #31 can't come back
  here.
- **`bullet_category_id`** references `bullet_category (id)`. This is why that table gained a UUID `id` in PR #30.
  The ids stay stable across `run_migrations()` because its upsert keys on `code`.
- **`reason`** (nullable) is **this card's evidence**: the phrase or fact in its text that puts it in its category,
  e.g. `activate exactly 1 bullet (activation): "activate 1 of these"`. It is *not* a restatement of how to read
  the category; that rule lives once, in `bullet_category.description`, so editing a definition never leaves 984
  copies out of date.
- **`note`** (nullable) holds the user's one-off decisions about a specific card, e.g. X-Saber Souza staying in D1
  as a deliberate exception. It's empty on import.

The table is created in `schema.sql` like every other table. Its rows are **data, not schema**, so unlike
`bullet_category` they are *not* seeded in `schema.sql` (see Seeding).

## Components

### 1. One-off export: artifact → fixture

Run once while implementing this design, not part of the app. It reads the two artifact sources:

- **Final placements:** artifact database document `review/state_v2`, whose `entries` map each card name to
  `{bucket, status}`, where `status` is `confirmed` (kept the automated category) or `changed` (moved by the user).
  `bucket` strings are `<code>_<slug>` (e.g. `B1_choice_activation`), so the category code is the part before the
  first `_`.
- **Card data and first-sort reasons:** the `<script id="dataset">` JSON embedded in the page (name, type, race,
  date, text, the automated `bucket`, and its `why`).

The two sources share exactly the same 984 names (verified 2026-09-24). Output: one fixture file,
`src/aijudge/ingestion/data/card_bulleted.json`, a list of `{ygoprodeck_id, name, category_code, reason}` sorted by
name. `name` is kept in the fixture for human review only and isn't written to the table.

**Passcodes.** The artifact stores names only. The export resolves each name to its passcode with one bulk
YGOPRODeck `cardinfo.php` call, pads it to 8 digits, and **fails loudly** on any name that doesn't resolve to exactly
one card, rather than skipping it. Resolving at export time means the committed fixture is complete and seeding
needs no network access.

**Reasons: import only what's still true.**
- For the 871 `confirmed` cards, the final category equals the automated one (verified: 871/871), so the automated
  `why` is still accurate. It's imported with one clean-up: 15 of them end in `— differs from your earlier label`,
  which compares against an even older labelling round, not the final category, so that suffix is stripped.
- For the 113 `changed` cards, the `why` argues for the category the user moved the card *away* from. Storing it
  would record a wrong reason, the one thing this project exists to avoid, so `reason` is `NULL` for these.
  Filling them in is later, manual work (see Deferred).

### 2. `ingestion/card_bulleted_seed.py` (new module)

`seed_card_bulleted(path=DEFAULT_FIXTURE_PATH) -> int` loads the fixture, maps each `category_code` to its
`bullet_category.id`, and upserts one row per card with
`INSERT ... ON CONFLICT (ygoprodeck_id) DO UPDATE SET bullet_category_id, reason`. It **never overwrites `note`**:
notes are the user's hand-written decisions, and re-seeding must not wipe them. It returns the number of rows
written. An unknown `category_code` raises before anything is written, so a fixture/legend mismatch can't produce a
partial load. Rows in the table but absent from the fixture are left alone. Re-running is safe and is how fixture
corrections get applied.

### 3. `db/card_bulleted_repo.py` (new module)

Raw SQL, like the other repos:

- `upsert_card_bulleted(*, ygoprodeck_id, bullet_category_id, reason=None) -> str` passes `ygoprodeck_id` through
  `normalize_passcode` and returns the row id. The seed module uses it.
- `get_card_bulleted(ygoprodeck_id) -> dict | None` normalizes the passcode, joins `bullet_category`, and returns
  `{ygoprodeck_id, code, name, description, category_note, reason, note}`, where `category_note` is the category's
  own `note` and `note` is the per-card one. Returns `None` when the card has no row.
- `update_card_bulleted_note(ygoprodeck_id, note) -> None` sets the per-card note, the one field a human edits
  directly.

### 4. `orchestration/preflight.py`: KNOWN FACTS line

`build_known_facts_context(card)` gains one line, after the per-effect lines, when `get_card_bulleted(
card["ygoprodeck_id"])` finds a row:

```
- <name>: bullet list category <code> (<category name>): <category description>[ Note: <category note>.]
  On this card: <reason>.[ Card note: <note>.]
```

Absent parts (no category note, `NULL` reason, no card note) are omitted, not guessed at. **No row means no line**,
so every other card behaves exactly as today. The existing "return `""` when the card has no confirmed effects"
behaviour is unchanged: the line only extends an existing block (see Deferred).

`get_card_bulleted` is imported at module level in `preflight.py`, the same way `get_confirmed_effects` already is,
so unit tests stub it with `monkeypatch.setattr(preflight, "get_card_bulleted", ...)`. Every existing non-DB test
that stubs `get_confirmed_effects` so `build_known_facts_context` returns a block (e.g.
`tests/orchestration/test_card_effect_pipeline.py`) must now stub `get_card_bulleted` too. Otherwise it would reach
the unreachable placeholder `DATABASE_URL` that `tests/conftest.py` sets, and fail.

`build_answering_system_prompt()` needs no change. It already tells the model that KNOWN FACTS are deterministic
and must not be contradicted.

## Testing approach

TDD throughout, with DB tests against `TEST_DATABASE_URL` only (they skip when it's unset):

- **Schema / migration:** `card_bulleted` exists; `ygoprodeck_id` is unique; the foreign key rejects an unknown
  `bullet_category_id`; `bullet_category` rows keep their ids across `run_migrations()`, so existing
  `card_bulleted` rows stay valid.
- **Repo:** upsert pads a short passcode; lookup matches with or without the leading zero; the join returns the
  category's fields; an unknown passcode returns `None`; an upsert updates the category and reason but keeps
  `note`.
- **Seed:** loads a small test fixture; re-running doesn't duplicate rows; a hand-set `note` survives a re-seed; an
  unknown category code raises and writes nothing.
- **Fixture integrity** (no DB): 984 entries; every passcode is 8 digits and unique; every `category_code` exists in
  the 13-row legend; `reason` is `null` for exactly the 113 changed cards; no reason contains
  `differs from your earlier label`.
- **Preflight:** the line appears with its parts when a row exists; absent parts are omitted; no row means the
  block is unchanged; a card with no confirmed effects still returns `""`.

## Open questions / explicitly deferred

- **Reasons for the 113 moved cards** stay `NULL` until written by hand or regenerated and checked. The line then
  simply shows the category rule without card-specific evidence.
- **Cards with a bullet category but no confirmed effects** get no KNOWN FACTS block at all, so their category isn't
  shown either. Emitting a category-only block is a separate decision about what an effect-less block should say.
- **Purrely cards (H)** have several bullet lists fitting different categories. `UNIQUE (ygoprodeck_id)` means one
  row per card; labelling each list separately would need a `list_index` column and a `(ygoprodeck_id,
  list_index)` key.
- **Card text changes:** a category is tied to one version of the card's wording, and errata could change it. A
  `card_text` snapshot or `reviewed_at` column would let stale rows be detected. Not added now.
- **Artifact → DB is one-way and one-off.** Later category changes are made in the DB (or the fixture, then
  re-seeded), not in the artifact.
