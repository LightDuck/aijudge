# Card Bullet Categories (`card_bulleted`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store the 984 hand-reviewed card → bullet-category placements in a new `card_bulleted` table and surface
each card's category in preflight's KNOWN FACTS block.

**Architecture:** A `card_bulleted` table keyed on the 8-digit passcode (no FK to `card`) references
`bullet_category(id)`. A committed JSON fixture, exported once from the "Bulleted Effects Review" artifact, is
loaded by an idempotent seed function. `preflight.build_known_facts_context` looks the card up by passcode and adds
one deterministic line.

**Tech Stack:** Python 3, psycopg3 (raw SQL, no ORM), Postgres 16 + pgvector (Docker), pytest.

**Spec:** `docs/superpowers/specs/2026-09-24-card-bulleted-design.md`

## Global Constraints

- Branch: `card-bulleted`, created off `dev`. Don't commit implementation to `dev` directly.
- TDD: every change starts with a failing test that is run and seen to fail.
- DB tests run only against `TEST_DATABASE_URL` and use this exact marker at module top:
  `pytestmark = pytest.mark.skipif("TEST_DATABASE_URL" not in os.environ, reason="requires TEST_DATABASE_URL (a dedicated test Postgres database)")`.
  Before running them, check `docker ps` shows `aijudge-db-1` up.
- Every passcode written to or looked up in `card_bulleted` goes through `aijudge.db.cards_repo.normalize_passcode`.
- `card_bulleted.ygoprodeck_id` is `NOT NULL UNIQUE` and has **no** foreign key to `card`.
- `reason` and `note` are nullable. Seeding never overwrites `note`.
- Raw SQL only, one repo module per table family, same style as `src/aijudge/db/bullet_categories_repo.py`.
- Full suite command: `python -m pytest -q`. Expected at the start: 560 passed.

## File Structure

- Modify `src/aijudge/db/schema.sql`: add the `card_bulleted` table.
- Create `src/aijudge/db/card_bulleted_repo.py`: upsert (single and bulk), lookup with category join, set note.
- Create `src/aijudge/ingestion/card_bulleted_seed.py`: load the fixture and upsert it.
- Create `src/aijudge/ingestion/data/card_bulleted.json`: the exported fixture, 984 entries.
- Modify `pyproject.toml`: ship `data/*.json` as package data.
- Modify `src/aijudge/orchestration/preflight.py`: the KNOWN FACTS bullet line.
- Tests: `tests/db/test_card_bulleted_repo.py`, `tests/ingestion/test_card_bulleted_seed.py`,
  `tests/ingestion/test_card_bulleted_fixture.py`, `tests/orchestration/test_preflight.py` (extend),
  `tests/orchestration/test_card_effect_pipeline.py` (stub), `tests/db/test_migrate.py` (extend).
- Modify `CLAUDE.md`: document each piece in the task that adds it.

---

### Task 1: `card_bulleted` table and repo

**Files:**
- Modify: `src/aijudge/db/schema.sql` (append after the `bullet_category` upsert, end of file)
- Create: `src/aijudge/db/card_bulleted_repo.py`
- Test: `tests/db/test_card_bulleted_repo.py`, `tests/db/test_migrate.py`
- Modify: `CLAUDE.md` (the `db/` bullet list, right after the `bullet_category` bullet)

**Interfaces:**
- Consumes: `normalize_passcode(passcode: str) -> str` from `aijudge.db.cards_repo`;
  `get_bullet_category(code: str) -> dict | None` from `aijudge.db.bullet_categories_repo` (dict has `id: uuid.UUID`).
- Produces:
  - `upsert_card_bulleted(*, ygoprodeck_id: str, bullet_category_id, reason: str | None = None) -> str` (row id)
  - `upsert_card_bulleted_rows(rows: list[dict]) -> int`, where each row is `{"ygoprodeck_id", "bullet_category_id",
    "reason"}`; one transaction, returns the row count
  - `get_card_bulleted(ygoprodeck_id: str) -> dict | None` returning
    `{"ygoprodeck_id", "code", "name", "description", "category_note", "reason", "note"}`
  - `update_card_bulleted_note(ygoprodeck_id: str, note: str | None) -> None`; raises `LookupError` if no row

- [ ] **Step 1: Write the failing tests**

`tests/db/test_card_bulleted_repo.py`:

```python
import os

import psycopg
import pytest

pytestmark = pytest.mark.skipif("TEST_DATABASE_URL" not in os.environ, reason="requires TEST_DATABASE_URL (a dedicated test Postgres database)")


def setup_function():
    from aijudge.db.connection import get_connection
    from aijudge.db.migrate import run_migrations

    run_migrations()
    with get_connection() as conn:
        conn.execute("TRUNCATE card_bulleted")
        conn.commit()


def _category_id(code):
    from aijudge.db.bullet_categories_repo import get_bullet_category

    return get_bullet_category(code)["id"]


def test_upsert_then_get_joins_the_category():
    from aijudge.db.card_bulleted_repo import get_card_bulleted, upsert_card_bulleted

    upsert_card_bulleted(ygoprodeck_id="32295838", bullet_category_id=_category_id("D1"), reason="gains these effects")

    assert get_card_bulleted("32295838") == {
        "ygoprodeck_id": "32295838",
        "code": "D1",
        "name": "Mandatory grant",
        "description": (
            "1 or more bullets, granted as a single indivisible bundle: one binary condition on the card either "
            "grants all of them or none of them. There is no branch and no scale — the bundle is never split "
            "into a subset."
        ),
        "category_note": (
            "Contrast with C: a card whose criteria select a subset of bullets, or move between them as some "
            "value changes, belongs in C, not here, even if the bullets are grant-phrased."
        ),
        "reason": "gains these effects",
        "note": None,
    }


def test_get_returns_none_for_an_unknown_passcode():
    from aijudge.db.card_bulleted_repo import get_card_bulleted

    assert get_card_bulleted("12345678") is None


def test_upsert_zero_pads_a_short_passcode():
    from aijudge.db.card_bulleted_repo import get_card_bulleted, upsert_card_bulleted

    upsert_card_bulleted(ygoprodeck_id="7403341", bullet_category_id=_category_id("C"))

    assert get_card_bulleted("07403341")["ygoprodeck_id"] == "07403341"


def test_get_matches_with_or_without_the_leading_zero():
    from aijudge.db.card_bulleted_repo import get_card_bulleted, upsert_card_bulleted

    upsert_card_bulleted(ygoprodeck_id="07403341", bullet_category_id=_category_id("C"))

    assert get_card_bulleted("7403341")["code"] == "C"


def test_reason_is_nullable():
    from aijudge.db.card_bulleted_repo import get_card_bulleted, upsert_card_bulleted

    upsert_card_bulleted(ygoprodeck_id="32295838", bullet_category_id=_category_id("B1"))

    assert get_card_bulleted("32295838")["reason"] is None


def test_upsert_updates_category_and_reason_but_keeps_note():
    from aijudge.db.card_bulleted_repo import get_card_bulleted, update_card_bulleted_note, upsert_card_bulleted

    upsert_card_bulleted(ygoprodeck_id="32295838", bullet_category_id=_category_id("B1"), reason="old")
    update_card_bulleted_note("32295838", "kept here as a deliberate exception")
    upsert_card_bulleted(ygoprodeck_id="32295838", bullet_category_id=_category_id("D1"), reason="new")

    row = get_card_bulleted("32295838")
    assert (row["code"], row["reason"], row["note"]) == ("D1", "new", "kept here as a deliberate exception")


def test_one_row_per_passcode():
    from aijudge.db.card_bulleted_repo import upsert_card_bulleted
    from aijudge.db.connection import get_connection

    upsert_card_bulleted(ygoprodeck_id="32295838", bullet_category_id=_category_id("B1"))
    upsert_card_bulleted(ygoprodeck_id="32295838", bullet_category_id=_category_id("B2"))

    with get_connection() as conn:
        assert conn.execute("SELECT count(*) FROM card_bulleted").fetchone()[0] == 1


def test_unknown_bullet_category_id_is_rejected():
    import uuid

    from aijudge.db.card_bulleted_repo import upsert_card_bulleted

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        upsert_card_bulleted(ygoprodeck_id="32295838", bullet_category_id=uuid.uuid4())


def test_update_note_on_a_missing_passcode_raises():
    from aijudge.db.card_bulleted_repo import update_card_bulleted_note

    with pytest.raises(LookupError):
        update_card_bulleted_note("12345678", "note")


def test_bulk_upsert_writes_every_row_in_one_call():
    from aijudge.db.card_bulleted_repo import get_card_bulleted, upsert_card_bulleted_rows

    count = upsert_card_bulleted_rows([
        {"ygoprodeck_id": "32295838", "bullet_category_id": _category_id("B1"), "reason": "a"},
        {"ygoprodeck_id": "7403341", "bullet_category_id": _category_id("C"), "reason": None},
    ])

    assert count == 2
    assert get_card_bulleted("32295838")["code"] == "B1"
    assert get_card_bulleted("07403341")["code"] == "C"


def test_rows_survive_rerunning_migrations():
    from aijudge.db.card_bulleted_repo import get_card_bulleted, upsert_card_bulleted
    from aijudge.db.migrate import run_migrations

    upsert_card_bulleted(ygoprodeck_id="32295838", bullet_category_id=_category_id("B1"))
    run_migrations()

    assert get_card_bulleted("32295838")["code"] == "B1"
```

In `tests/db/test_migrate.py`, add `"card_bulleted"` to the table tuple:

```python
        for table in ("card", "card_errata_versions", "rulings", "card_effects_structured", "rulebook_chunks", "qa_test_cases", "bullet_category", "card_bulleted"):
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/db/test_card_bulleted_repo.py tests/db/test_migrate.py -q`
Expected: FAIL. The repo tests error in `setup_function` because `card_bulleted` doesn't exist, and
`test_migrate` fails with "expected table 'card_bulleted' to exist".

- [ ] **Step 3: Add the table to `schema.sql`**

Append at the end of `src/aijudge/db/schema.sql`:

```sql

-- Which bullet_category each card's bulleted effect list belongs to, from the
-- hand-reviewed "Bulleted Effects Review" (see docs/superpowers/specs/
-- 2026-09-24-card-bulleted-design.md). Keyed on the 8-digit passcode, the same
-- value as card.ygoprodeck_id but deliberately not a foreign key to `card`:
-- most reviewed cards aren't ingested, and a card ingested later is covered
-- with no backfill. Rows are data, loaded by ingestion.card_bulleted_seed, not
-- seeded here.
CREATE TABLE IF NOT EXISTS card_bulleted (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bullet_category_id UUID NOT NULL REFERENCES bullet_category (id),
    ygoprodeck_id TEXT NOT NULL UNIQUE,
    reason TEXT,
    note TEXT
);
```

- [ ] **Step 4: Write the repo**

`src/aijudge/db/card_bulleted_repo.py`:

```python
from .cards_repo import normalize_passcode
from .connection import get_connection

_UPSERT = """
    INSERT INTO card_bulleted (ygoprodeck_id, bullet_category_id, reason)
    VALUES (%s, %s, %s)
    ON CONFLICT (ygoprodeck_id) DO UPDATE SET
        bullet_category_id = EXCLUDED.bullet_category_id,
        reason = EXCLUDED.reason
"""


def upsert_card_bulleted(*, ygoprodeck_id: str, bullet_category_id, reason: str | None = None) -> str:
    """Insert or update a card's bullet category. Never touches `note`, which
    holds hand-written decisions that re-seeding must not wipe."""
    with get_connection() as conn:
        row = conn.execute(
            _UPSERT + " RETURNING id", (normalize_passcode(ygoprodeck_id), bullet_category_id, reason)
        ).fetchone()
        conn.commit()
    return str(row[0])


def upsert_card_bulleted_rows(rows: list[dict]) -> int:
    """Upsert many rows in one transaction: all of them are written, or none."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                _UPSERT,
                [(normalize_passcode(r["ygoprodeck_id"]), r["bullet_category_id"], r["reason"]) for r in rows],
            )
        conn.commit()
    return len(rows)


def get_card_bulleted(ygoprodeck_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT cb.ygoprodeck_id, bc.code, bc.name, bc.description, bc.note, cb.reason, cb.note "
            "FROM card_bulleted cb JOIN bullet_category bc ON bc.id = cb.bullet_category_id "
            "WHERE cb.ygoprodeck_id = %s",
            (normalize_passcode(ygoprodeck_id),),
        ).fetchone()
    if row is None:
        return None
    keys = ("ygoprodeck_id", "code", "name", "description", "category_note", "reason", "note")
    return dict(zip(keys, row))


def update_card_bulleted_note(ygoprodeck_id: str, note: str | None) -> None:
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE card_bulleted SET note = %s WHERE ygoprodeck_id = %s", (note, normalize_passcode(ygoprodeck_id))
        )
        if cur.rowcount == 0:
            raise LookupError(f"no card_bulleted row for passcode {ygoprodeck_id!r}")
        conn.commit()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/db/test_card_bulleted_repo.py tests/db/test_migrate.py -q`
Expected: all pass.

- [ ] **Step 6: Document it in `CLAUDE.md`**

Insert right after the `bullet_category` bullet in the `db/` section:

```markdown
  - `card_bulleted` maps a card's passcode (`ygoprodeck_id`, 8 digits, `UNIQUE`) to its `bullet_category_id`
    (FK to `bullet_category(id)`), with nullable `reason` (this card's evidence for the category, e.g. the phrase
    that decides it) and nullable `note` (a hand-written per-card decision). `ygoprodeck_id` is the same value as
    `card.ygoprodeck_id` but deliberately **not** a foreign key to `card`: most reviewed cards aren't ingested,
    and a card ingested later is covered with no backfill. How to read a category lives once, in
    `bullet_category.description`, never copied per card. `card_bulleted_repo`: `upsert_card_bulleted()` /
    `upsert_card_bulleted_rows()` (one transaction) never touch `note`; `get_card_bulleted(passcode)` joins the
    category and returns `{ygoprodeck_id, code, name, description, category_note, reason, note}` or `None`;
    `update_card_bulleted_note()` raises `LookupError` on a missing row. Every passcode goes through
    `normalize_passcode`.
```

- [ ] **Step 7: Run the full suite and commit**

Run: `python -m pytest -q`. Expected: all pass (560 + 11 new).

```bash
git add src/aijudge/db/schema.sql src/aijudge/db/card_bulleted_repo.py tests/db/test_card_bulleted_repo.py tests/db/test_migrate.py CLAUDE.md
git commit -m "feat(db): add card_bulleted table and repo"
```

---

### Task 2: Seed function

**Files:**
- Create: `src/aijudge/ingestion/card_bulleted_seed.py`
- Test: `tests/ingestion/test_card_bulleted_seed.py`
- Modify: `CLAUDE.md` (the `ingestion/` bullet, after the `rulebook_seed.py` sentence)

**Interfaces:**
- Consumes: `get_all_bullet_categories() -> list[dict]` (each with `code`, `id`);
  `upsert_card_bulleted_rows(rows) -> int` from Task 1.
- Produces: `seed_card_bulleted(path: Path = DEFAULT_FIXTURE_PATH) -> int`; `DEFAULT_FIXTURE_PATH` (a `Path` to
  `src/aijudge/ingestion/data/card_bulleted.json`); `UnknownBulletCategoryError(ValueError)`.
  Fixture format: a JSON list of `{"ygoprodeck_id": str, "name": str, "category_code": str, "reason": str | null}`.

- [ ] **Step 1: Write the failing tests**

`tests/ingestion/test_card_bulleted_seed.py`:

```python
import json
import os

import pytest

pytestmark = pytest.mark.skipif("TEST_DATABASE_URL" not in os.environ, reason="requires TEST_DATABASE_URL (a dedicated test Postgres database)")


def setup_function():
    from aijudge.db.connection import get_connection
    from aijudge.db.migrate import run_migrations

    run_migrations()
    with get_connection() as conn:
        conn.execute("TRUNCATE card_bulleted")
        conn.commit()


def _write_fixture(tmp_path, entries):
    path = tmp_path / "card_bulleted.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


_ENTRIES = [
    {"ygoprodeck_id": "32295838", "name": "Digitron", "category_code": "B1", "reason": "activate 1 of these"},
    {"ygoprodeck_id": "07403341", "name": "Cynet Conflict", "category_code": "C", "reason": None},
]


def _count():
    from aijudge.db.connection import get_connection

    with get_connection() as conn:
        return conn.execute("SELECT count(*) FROM card_bulleted").fetchone()[0]


def test_seed_loads_every_fixture_entry(tmp_path):
    from aijudge.db.card_bulleted_repo import get_card_bulleted
    from aijudge.ingestion.card_bulleted_seed import seed_card_bulleted

    assert seed_card_bulleted(_write_fixture(tmp_path, _ENTRIES)) == 2

    assert get_card_bulleted("32295838")["code"] == "B1"
    assert get_card_bulleted("32295838")["reason"] == "activate 1 of these"
    assert get_card_bulleted("07403341")["reason"] is None


def test_reseeding_does_not_duplicate_rows(tmp_path):
    from aijudge.ingestion.card_bulleted_seed import seed_card_bulleted

    path = _write_fixture(tmp_path, _ENTRIES)
    seed_card_bulleted(path)
    seed_card_bulleted(path)

    assert _count() == 2


def test_reseeding_keeps_a_hand_written_note(tmp_path):
    from aijudge.db.card_bulleted_repo import get_card_bulleted, update_card_bulleted_note
    from aijudge.ingestion.card_bulleted_seed import seed_card_bulleted

    path = _write_fixture(tmp_path, _ENTRIES)
    seed_card_bulleted(path)
    update_card_bulleted_note("32295838", "deliberate exception")
    seed_card_bulleted(path)

    assert get_card_bulleted("32295838")["note"] == "deliberate exception"


def test_unknown_category_code_raises_and_writes_nothing(tmp_path):
    from aijudge.ingestion.card_bulleted_seed import UnknownBulletCategoryError, seed_card_bulleted

    bad = _ENTRIES + [{"ygoprodeck_id": "12345678", "name": "Nope", "category_code": "Q9", "reason": None}]

    with pytest.raises(UnknownBulletCategoryError, match="Q9"):
        seed_card_bulleted(_write_fixture(tmp_path, bad))

    assert _count() == 0


def test_default_fixture_path_points_into_the_package():
    from aijudge.ingestion.card_bulleted_seed import DEFAULT_FIXTURE_PATH

    assert DEFAULT_FIXTURE_PATH.parts[-3:] == ("ingestion", "data", "card_bulleted.json")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/ingestion/test_card_bulleted_seed.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'aijudge.ingestion.card_bulleted_seed'`.

- [ ] **Step 3: Write the seed module**

`src/aijudge/ingestion/card_bulleted_seed.py`:

```python
import json
from pathlib import Path

from aijudge.db.bullet_categories_repo import get_all_bullet_categories
from aijudge.db.card_bulleted_repo import upsert_card_bulleted_rows

DEFAULT_FIXTURE_PATH = Path(__file__).parent / "data" / "card_bulleted.json"


class UnknownBulletCategoryError(ValueError):
    pass


def seed_card_bulleted(path: Path = DEFAULT_FIXTURE_PATH) -> int:
    """Load the card_bulleted fixture into the DB. Safe to re-run: rows are
    upserted on their passcode, `note` is never overwritten, and rows absent
    from the fixture are left alone. Every category code is checked before
    anything is written, so a fixture/legend mismatch can't cause a partial load."""
    entries = json.loads(Path(path).read_text(encoding="utf-8"))
    category_ids = {c["code"]: c["id"] for c in get_all_bullet_categories()}
    unknown = sorted({e["category_code"] for e in entries} - category_ids.keys())
    if unknown:
        raise UnknownBulletCategoryError(f"fixture uses bullet category codes missing from bullet_category: {unknown}")
    return upsert_card_bulleted_rows([
        {
            "ygoprodeck_id": e["ygoprodeck_id"],
            "bullet_category_id": category_ids[e["category_code"]],
            "reason": e["reason"],
        }
        for e in entries
    ])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/ingestion/test_card_bulleted_seed.py -q`
Expected: 5 passed.

- [ ] **Step 5: Document it in `CLAUDE.md`**

In the `ingestion/` bullet, after the sentence ending "expected to be re-run whenever the live rulebook page
changes.", add:

```markdown
  `card_bulleted_seed.py` — `seed_card_bulleted(path=DEFAULT_FIXTURE_PATH)` loads
  `ingestion/data/card_bulleted.json` (984 hand-reviewed cards: `{ygoprodeck_id, name, category_code, reason}`,
  exported once from the "Bulleted Effects Review" artifact) into `card_bulleted` in one transaction. It checks
  every category code first and raises `UnknownBulletCategoryError` without writing anything on a mismatch.
  Re-running is safe (upsert on passcode, `note` never overwritten), and is how fixture corrections are applied.
  Run `run_migrations()` first.
```

- [ ] **Step 6: Run the full suite and commit**

Run: `python -m pytest -q`. Expected: all pass.

```bash
git add src/aijudge/ingestion/card_bulleted_seed.py tests/ingestion/test_card_bulleted_seed.py CLAUDE.md
git commit -m "feat(ingestion): add card_bulleted seed"
```

---

### Task 3: Export the fixture and seed the app database

This task runs in the main session: it needs the Artifact and ArtifactData tools, which subagents don't have.

**Files:**
- Create: `src/aijudge/ingestion/data/card_bulleted.json` (generated)
- Modify: `pyproject.toml`
- Test: `tests/ingestion/test_card_bulleted_fixture.py`

**Interfaces:**
- Consumes: the fixture format and `DEFAULT_FIXTURE_PATH` from Task 2; `seed_card_bulleted()`.
- Produces: the committed 984-entry fixture that Task 4's live check relies on.

- [ ] **Step 1: Write the failing fixture-integrity tests (no DB)**

`tests/ingestion/test_card_bulleted_fixture.py`:

```python
import json

import pytest

from aijudge.ingestion.card_bulleted_seed import DEFAULT_FIXTURE_PATH

_LEGEND_CODES = {"A1", "A2", "B1", "B2", "C", "D1", "D2", "E1", "E2", "F", "G", "H", "Z"}


@pytest.fixture(scope="module")
def entries():
    return json.loads(DEFAULT_FIXTURE_PATH.read_text(encoding="utf-8"))


def test_fixture_has_all_984_reviewed_cards(entries):
    assert len(entries) == 984


def test_every_entry_has_exactly_the_fixture_fields(entries):
    assert all(set(e) == {"ygoprodeck_id", "name", "category_code", "reason"} for e in entries)


def test_passcodes_are_unique_eight_digit_strings(entries):
    passcodes = [e["ygoprodeck_id"] for e in entries]
    assert all(isinstance(p, str) and len(p) == 8 and p.isdigit() for p in passcodes)
    assert len(set(passcodes)) == len(passcodes)


def test_names_are_unique(entries):
    assert len({e["name"] for e in entries}) == len(entries)


def test_every_category_code_is_in_the_legend(entries):
    assert {e["category_code"] for e in entries} <= _LEGEND_CODES


def test_moved_cards_have_no_reason(entries):
    # The 113 cards the user moved during review carry a first-sort reason that
    # argues for the category they were moved away from, so it isn't imported.
    assert sum(e["reason"] is None for e in entries) == 113


def test_no_reason_keeps_the_stale_earlier_label_suffix(entries):
    assert not any("differs from your earlier label" in (e["reason"] or "") for e in entries)


def test_entries_are_sorted_by_name(entries):
    names = [e["name"] for e in entries]
    assert names == sorted(names)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/ingestion/test_card_bulleted_fixture.py -q`
Expected: ERROR with `FileNotFoundError` on `card_bulleted.json`.

- [ ] **Step 3: Fetch the artifact's current data**

Re-read both sources fresh, since the user may have edited them since the spec was written:
- `Artifact` `action: "read"`, `url: "https://claude.ai/artifact/YDX8ux6UVwJ1cK3ZjchskV"`. Note the saved HTML path
  it reports.
- `ArtifactData` `action: "get"`, same `url`, `collection: "review"`, `doc_id: "state_v2"`, `out_dir:` the session
  scratchpad. Note the saved JSON path.

- [ ] **Step 4: Write and run the export script (scratchpad, not committed)**

Save as `<scratchpad>/export_card_bulleted.py`, filling in the two paths from Step 3:

```python
import json
import re
import sys
from pathlib import Path

import requests

from aijudge.db.cards_repo import normalize_passcode

HTML_PATH = Path(sys.argv[1])
STATE_PATH = Path(sys.argv[2])
OUT_PATH = Path(sys.argv[3])
STALE_SUFFIX = re.compile(r"\s+—\s+differs from your earlier label$")

html = HTML_PATH.read_text(encoding="utf-8")
dataset = json.loads(re.search(r'<script id="dataset" type="application/json">(.*?)</script>', html, re.S).group(1))
entries = json.loads(STATE_PATH.read_text(encoding="utf-8"))["entries"]
assert {d["name"] for d in dataset} == set(entries), "dataset and review state disagree on card names"

# One call for the whole card pool; the artifact's names came from this same API.
all_cards = requests.get("https://db.ygoprodeck.com/api/v7/cardinfo.php", timeout=120).json()["data"]
passcodes = {}
for card in all_cards:
    passcodes.setdefault(card["name"], set()).add(normalize_passcode(str(card["id"])))

out, problems = [], []
for d in dataset:
    state = entries[d["name"]]
    found = passcodes.get(d["name"], set())
    if len(found) != 1:
        problems.append(f"{d['name']!r}: {sorted(found) or 'no match'}")
        continue
    reason = None
    if state["status"] == "confirmed":
        assert state["bucket"] == d["bucket"], f"{d['name']!r} confirmed but bucket changed"
        reason = STALE_SUFFIX.sub("", d["why"])
    out.append({
        "ygoprodeck_id": found.pop(),
        "name": d["name"],
        "category_code": state["bucket"].split("_", 1)[0],
        "reason": reason,
    })

if problems:
    sys.exit("unresolved names:\n" + "\n".join(problems))
out.sort(key=lambda e: e["name"])
OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(len(out), "entries written")
```

Run: `python <scratchpad>/export_card_bulleted.py <html> <state_json> src/aijudge/ingestion/data/card_bulleted.json`
Expected: `984 entries written`. If it exits with "unresolved names", **stop and show the list to the user.** Don't
guess passcodes. A name that matches several passcodes is usually an alternate-art print; ask the user which to
use.

- [ ] **Step 5: Run the fixture tests to verify they pass**

Run: `python -m pytest tests/ingestion/test_card_bulleted_fixture.py -q`
Expected: 8 passed. If the 113 count fails, re-check the review state's `changed` count before changing the test,
because the user may have re-reviewed cards since. Update the test's number only to match the fresh state.

- [ ] **Step 6: Ship the fixture as package data**

In `pyproject.toml`, after the `[tool.setuptools.packages.find]` block, add:

```toml
[tool.setuptools.package-data]
"aijudge.ingestion" = ["data/*.json"]
```

- [ ] **Step 7: Seed the app database and check it**

```bash
python -c "from aijudge.db.migrate import run_migrations; from aijudge.ingestion.card_bulleted_seed import seed_card_bulleted; run_migrations(); print(seed_card_bulleted())"
docker exec aijudge-db-1 psql -U aijudge -d aijudge -c "select bc.code, count(*) from card_bulleted cb join bullet_category bc on bc.id = cb.bullet_category_id group by bc.code order by bc.code"
```

Expected: `984`, then per-code counts matching the review: A1 4, A2 6, B1 275, B2 43, C 152, D1 256, D2 46, E1 8,
E2 12, F 159, G 19, H 4 (Z absent).

- [ ] **Step 8: Run the full suite and commit**

Run: `python -m pytest -q`. Expected: all pass.

```bash
git add src/aijudge/ingestion/data/card_bulleted.json tests/ingestion/test_card_bulleted_fixture.py pyproject.toml
git commit -m "feat(ingestion): add reviewed card_bulleted fixture"
```

---

### Task 4: Bullet category line in KNOWN FACTS

**Files:**
- Modify: `src/aijudge/orchestration/preflight.py` (imports at lines 40-43; `build_known_facts_context`, lines 53-107)
- Test: `tests/orchestration/test_preflight.py` (append), `tests/orchestration/test_card_effect_pipeline.py`
  (fixture at lines 12-45)
- Modify: `CLAUDE.md` (the `preflight.py` bullet)

**Interfaces:**
- Consumes: `get_card_bulleted(ygoprodeck_id) -> dict | None` from Task 1.
- Produces: `build_known_facts_context(card: dict) -> str` (same signature). When
  `card.get("ygoprodeck_id")` has a `card_bulleted` row, one extra final line is added:
  `- <name>: bullet list category <code> (<name>): <description>[ Note: <category_note>][ On this card: <reason>.][ Card note: <note>]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/orchestration/test_preflight.py`:

```python
_BULLET_CARD = {
    "id": "card-1",
    "name": "Digitron",
    "card_type": "Effect Monster",
    "card_text": "text",
    "race": "Cyberse",
    "ygoprodeck_id": "32295838",
}

_ONE_EFFECT = [{
    "effect_type": "ignition",
    "activation_condition": None,
    "cost": None,
    "targeting": None,
    "effect": "Do a thing.",
    "damage_step_category": None,
    "usage_limit_text": None,
}]


def _bullet_row(**overrides):
    row = {
        "ygoprodeck_id": "32295838",
        "code": "B1",
        "name": "Player choice · activation",
        "description": 'Always choose strictly 1 bullet, at activation ("activate 1 of these effects").',
        "category_note": None,
        "reason": 'activate exactly 1 bullet (activation): "activate 1 of these"',
        "note": None,
    }
    row.update(overrides)
    return row


def _stub(monkeypatch, *, effects, bullet_row):
    from aijudge.orchestration import preflight

    looked_up = []
    monkeypatch.setattr(preflight, "get_confirmed_effects", lambda card_id: effects)

    def fake_get_card_bulleted(passcode):
        looked_up.append(passcode)
        return bullet_row

    monkeypatch.setattr(preflight, "get_card_bulleted", fake_get_card_bulleted)
    return looked_up


def test_known_facts_adds_the_bullet_category_line_last(monkeypatch):
    from aijudge.orchestration.preflight import build_known_facts_context

    looked_up = _stub(monkeypatch, effects=_ONE_EFFECT, bullet_row=_bullet_row())

    context = build_known_facts_context(_BULLET_CARD)

    assert looked_up == ["32295838"]
    assert context.splitlines()[-1] == (
        '- Digitron: bullet list category B1 (Player choice · activation): Always choose strictly 1 bullet, '
        'at activation ("activate 1 of these effects"). On this card: activate exactly 1 bullet (activation): '
        '"activate 1 of these".'
    )


def test_bullet_line_includes_category_note_and_card_note_when_present(monkeypatch):
    from aijudge.orchestration.preflight import build_known_facts_context

    _stub(
        monkeypatch,
        effects=_ONE_EFFECT,
        bullet_row=_bullet_row(category_note="Contrast with C.", note="deliberate exception"),
    )

    last = build_known_facts_context(_BULLET_CARD).splitlines()[-1]

    assert " Note: Contrast with C. On this card: " in last
    assert last.endswith(" Card note: deliberate exception")


def test_bullet_line_omits_a_null_reason(monkeypatch):
    from aijudge.orchestration.preflight import build_known_facts_context

    _stub(monkeypatch, effects=_ONE_EFFECT, bullet_row=_bullet_row(reason=None))

    last = build_known_facts_context(_BULLET_CARD).splitlines()[-1]

    assert last.startswith("- Digitron: bullet list category B1")
    assert "On this card" not in last


def test_no_bullet_row_leaves_the_block_unchanged(monkeypatch):
    from aijudge.orchestration.preflight import build_known_facts_context

    _stub(monkeypatch, effects=_ONE_EFFECT, bullet_row=None)

    context = build_known_facts_context(_BULLET_CARD)

    assert "bullet list category" not in context
    assert len(context.splitlines()) == 2  # header + one effect line


def test_card_without_a_passcode_skips_the_lookup(monkeypatch):
    from aijudge.orchestration.preflight import build_known_facts_context

    looked_up = _stub(monkeypatch, effects=_ONE_EFFECT, bullet_row=_bullet_row())
    card = {k: v for k, v in _BULLET_CARD.items() if k != "ygoprodeck_id"}

    assert "bullet list category" not in build_known_facts_context(card)
    assert looked_up == []


def test_card_with_no_confirmed_effects_still_returns_empty(monkeypatch):
    from aijudge.orchestration.preflight import build_known_facts_context

    _stub(monkeypatch, effects=[], bullet_row=_bullet_row())

    assert build_known_facts_context(_BULLET_CARD) == ""
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/orchestration/test_preflight.py -q`
Expected: the new tests FAIL with `AttributeError: <module 'aijudge.orchestration.preflight'> has no attribute
'get_card_bulleted'` (from `monkeypatch.setattr`).

- [ ] **Step 3: Implement**

In `src/aijudge/orchestration/preflight.py`, add the import next to the other `aijudge.db` imports:

```python
from aijudge.db.card_bulleted_repo import get_card_bulleted
```

Add this helper just above `def build_known_facts_context`:

```python
def _bullet_category_line(card: dict) -> str | None:
    """The card's hand-reviewed bullet category (how to read its bulleted list),
    or None if it has no passcode or no card_bulleted row. Absent parts are
    left out rather than guessed at."""
    passcode = card.get("ygoprodeck_id")
    if not passcode:
        return None
    bulleted = get_card_bulleted(passcode)
    if bulleted is None:
        return None
    line = (
        f"- {card['name']}: bullet list category {bulleted['code']} ({bulleted['name']}): "
        f"{bulleted['description']}"
    )
    if bulleted["category_note"]:
        line += f" Note: {bulleted['category_note']}"
    if bulleted["reason"]:
        line += f" On this card: {bulleted['reason']}."
    if bulleted["note"]:
        line += f" Card note: {bulleted['note']}"
    return line
```

In `build_known_facts_context`, replace the final `return "\n".join(lines)` with:

```python
    bullet_line = _bullet_category_line(card)
    if bullet_line is not None:
        lines.append(bullet_line)
    return "\n".join(lines)
```

- [ ] **Step 4: Stub the new lookup in the pipeline tests' fixture**

In `tests/orchestration/test_card_effect_pipeline.py`, at the end of the autouse fixture `mock_db_for_test_cards`,
right after its `monkeypatch.setattr(preflight, "get_confirmed_effects", ...)` line, add:

```python
    # These fake cards have no card_bulleted row; never reach the DB for it.
    monkeypatch.setattr(preflight, "get_card_bulleted", lambda passcode: None)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/orchestration -q`
Expected: all pass, including the existing `test_preflight_db.py` tests. Those cards have no `card_bulleted` rows
in the test DB, so their blocks are unchanged.

- [ ] **Step 6: Document it in `CLAUDE.md`**

In the `preflight.py` bullet, after the sentence ending "caught in manual testing.", add:

```markdown
    When the card's `ygoprodeck_id` has a `card_bulleted` row, the block ends with one more line giving its
    bullet list category (code, name, the category's `description` and `note`) plus this card's `reason` and
    per-card `note`, each omitted when empty. No passcode or no row means no line. The line only extends an
    existing block: a card with no confirmed effects still gets `""`.
```

- [ ] **Step 7: Check against the live app database**

```bash
python -c "
from aijudge.db.cards_repo import get_card_by_name
from aijudge.orchestration.preflight import build_known_facts_context
for name in ['Digitron', 'Cynet Conflict', 'Amazoness Call']:
    card = get_card_by_name(name)
    print(name, '->', [l for l in build_known_facts_context(card).splitlines() if 'bullet list category' in l])
"
```

Expected: each of the 10 seed cards that's in the fixture gets its line, and one that isn't gets `[]`. Report which
seed cards are covered. This is informational, not an assertion.

- [ ] **Step 8: Run the full suite and commit**

Run: `python -m pytest -q`. Expected: all pass.

```bash
git add src/aijudge/orchestration/preflight.py tests/orchestration/test_preflight.py tests/orchestration/test_card_effect_pipeline.py CLAUDE.md
git commit -m "feat(preflight): add card bullet category to KNOWN FACTS"
```
