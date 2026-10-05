# Rulings Grounding (Step A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put each grounded card's already-stored ygoresources rulings — readable, ranked, budgeted and citable as
`ruling:<id>` — into the deterministic context the tool-free answering turn sees.

**Architecture:** Ingestion resolves `<<konami_id>>` placeholders into card names (keeping the raw text) and records
whether the rulings fetch worked. A new pure module, `orchestration/rulings_context.py`, ranks and budgets a
question's rulings and renders one RULINGS block. Rulings ride on the existing `grounded_cards` dicts into
`confidence.update_signals`, which registers them as citable, so `run_loop` is unchanged.

**Tech Stack:** Python 3, psycopg3 (raw SQL), Postgres 16, pytest, `requests`, FastAPI (existing).

**Spec:** `docs/superpowers/specs/2026-10-05-rulings-grounding-design.md`

## Global Constraints

- Branch off `dev` (never `main`); this plan doc itself lives on `dev`.
- TDD: every code change starts with a failing test. Test fixtures use **real** cards, passcodes, Konami ids and
  ruling texts — never invented ones.
- DB tests run only against `TEST_DATABASE_URL` and carry the module-level skip marker
  `pytestmark = pytest.mark.skipif("TEST_DATABASE_URL" not in os.environ, reason="requires TEST_DATABASE_URL (a dedicated test Postgres database)")`.
- `schema.sql` stays idempotent (`ADD COLUMN IF NOT EXISTS`; constraints added inside `DO $$ ... EXCEPTION WHEN duplicate_object THEN NULL; END $$;`).
- Raw `rulings.ruling_text` is never modified after insert.
- `card.rulings_status` values: `'fetched'`, `'failed'`, `'no_konami_id'`, or `NULL` (pre-change rows).
- Only `rulings_status == 'failed'` sets the retrieval gap (−0.3). Zero rulings, `'no_konami_id'` and `NULL` carry no penalty.
- `DEFAULT_RULINGS_BUDGET_CHARS = 6000`; a ruling is never truncated.
- An unresolvable placeholder renders as `[card #<id>]`, never a guessed name and never a bare `<<id>>`.
- `OLLAMA_NUM_CTX` default `8192`.
- No network call at answer time; no network call in tests.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Deliberate deviations from the spec (decided while planning)

1. **`build_grounded_result` keeps its one-argument signature.** Existing CLI/API tests inject one-argument
   `build_grounded_result_fn` lambdas. Rulings are attached afterwards by a new helper,
   `rulings_context.attach_rulings(grounded_cards, cards, grounding)`, which adds the same `"rulings"` and
   `"rulings_status"` keys the spec describes.
2. **`OllamaLLMClient` reads `OLLAMA_NUM_CTX` itself**, like it already reads `OLLAMA_MODEL`/`OLLAMA_BASE_URL`,
   since both entrypoints construct it as `OllamaLLMClient()`. The behavior is the same.
3. **`build_pipeline_context` gains a keyword `rulings_context=""`** so the RULINGS block lands before LOOKUP
   FAILURES (which stays last); three existing test lambdas are widened to accept it.
4. **Bare ruling ids are normalized** (`<uuid>` → `ruling:<uuid>`) in `normalize_cited_ids`, mirroring the existing
   bare-card-id handling. The spec didn't mention it; without it a sloppy citation scores 0.0.

## Review Focus

1. **A ruling with no placeholders, or a malformed one like `<<abc>>`** — returned unchanged, with an empty id list. Test in Task 2.
2. **One very long real ruling that doesn't fit a card's share but fits the pooled leftover** — picked up in the second pass, never truncated. Test in Task 5.
3. **The model cites a ruling's bare uuid without the `ruling:` prefix** — treated as the known ruling, not fabricated. Test in Task 6.
4. **A pre-backfill card (`ygoresources_id` and `rulings_status` both `NULL`, rulings unresolved)** — renders `[card #id]` text, no cross-reference ranking, no crash, no penalty. Test in Task 5.
5. **The name index download fails during on-demand ingestion** — the card and its rulings are still stored (unresolved, ids parsed), status `fetched`. Test in Task 3.

## File structure

| File | Change | Responsibility |
|---|---|---|
| `src/aijudge/db/schema.sql` | modify | new columns + CHECK |
| `src/aijudge/db/cards_repo.py` | modify | `rulings_status` in card dicts and inserts; `set_card_rulings_source`; `list_cards` |
| `src/aijudge/db/rulings_repo.py` | modify | new columns on insert/read; `list_unresolved_rulings`; `update_ruling_resolution` |
| `src/aijudge/ingestion/ygoresources_client.py` | modify | name index, placeholder parsing/resolution |
| `src/aijudge/ingestion/seed.py` | modify | fetch status, Konami id, resolution at ingest |
| `src/aijudge/ingestion/rulings_backfill.py` | create | one-off, re-runnable backfill |
| `src/aijudge/orchestration/rulings_context.py` | create | rank, budget, render; attach to grounded cards |
| `src/aijudge/orchestration/confidence.py` | modify | register rulings as citable; gap on `failed`; bare-id normalization |
| `src/aijudge/orchestration/card_effect_pipeline.py` | modify | rulings for pipeline-resolved cards |
| `src/aijudge/cli.py`, `src/aijudge/api/app.py` | modify | rulings for locally matched cards |
| `src/aijudge/orchestration/protocol.py` | modify | answering prompt mentions RULINGS / `ruling:<id>` |
| `src/aijudge/llm/client.py` | modify | `num_ctx` |
| `tests/rulings_fixtures.py` | create | real ruling texts and Konami ids shared by tests |
| `tests/conftest.py` | modify | autouse guard: no real name-index download in tests |
| `CLAUDE.md` | modify | document the above |

---

### Task 1: Schema and repo support

**Files:**
- Modify: `src/aijudge/db/schema.sql` (append after the `CREATE TABLE IF NOT EXISTS rulings (...)` block, currently ending line 85)
- Modify: `src/aijudge/db/cards_repo.py`
- Modify: `src/aijudge/db/rulings_repo.py`
- Test: `tests/db/test_rulings_repo.py`, `tests/db/test_cards_repo.py`

**Interfaces:**
- Produces:
  - `cards_repo.insert_card(..., rulings_status: str | None = None)`; every card dict now has key `"rulings_status"`.
  - `cards_repo.set_card_rulings_source(card_id: str, *, rulings_status: str | None, ygoresources_id: str | None = None) -> None` (a `None` `ygoresources_id` leaves the stored one unchanged).
  - `cards_repo.list_cards() -> list[dict]` (all cards, same dict shape as `get_card_by_id`).
  - `rulings_repo.insert_ruling(*, card_id, ruling_text, source, ruling_date=None, ruling_text_resolved: str | None = None, referenced_konami_ids: Sequence[int] = ()) -> str`
  - `rulings_repo.get_rulings_for_card(card_id) -> list[dict]` with keys `id, ruling_text, source, ruling_date, ruling_text_resolved, referenced_konami_ids` (`referenced_konami_ids` is a `list[int]`).
  - `rulings_repo.list_unresolved_rulings() -> list[dict]` (same keys plus `card_id`).
  - `rulings_repo.update_ruling_resolution(ruling_id: str, *, ruling_text_resolved: str, referenced_konami_ids: Sequence[int]) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/db/test_rulings_repo.py`:

```python
def _insert_amazoness_call():
    from aijudge.db.cards_repo import insert_card

    return insert_card(
        name="Amazoness Call",
        card_text=(
            'Take 1 "Amazoness" card from your Deck, except "Amazoness Call", and either add it to your hand or '
            'send it to the GY. During your Main Phase: You can banish this card from your GY, then target 1 '
            '"Amazoness" monster you control; this turn, that monster can attack all monsters your opponent '
            'controls, once each, also other monsters you control cannot attack. You can only activate 1 '
            '"Amazoness Call" per turn.'
        ),
        card_type="Spell Card",
        race="Quick-Play",
        source="ygoprodeck",
        fetched_at=date(2026, 10, 5),
        ygoprodeck_id="57312333",
        deterministic_parse_eligible=True,
    )


def test_insert_ruling_stores_resolved_text_and_referenced_ids():
    from aijudge.db.rulings_repo import get_rulings_for_card, insert_ruling
    from tests.rulings_fixtures import AMAZONESS_CALL_RULING_2017

    card_id = _insert_amazoness_call()
    insert_ruling(
        card_id=card_id,
        ruling_text=AMAZONESS_CALL_RULING_2017,
        source="db.ygoresources",
        ruling_date=date(2017, 7, 22),
        ruling_text_resolved="Q: I activate the second effect of Amazoness Call ...",
        referenced_konami_ids=[13174, 8963, 5505, 5682],
    )

    [ruling] = get_rulings_for_card(card_id)
    assert ruling["ruling_text"] == AMAZONESS_CALL_RULING_2017
    assert ruling["ruling_text_resolved"] == "Q: I activate the second effect of Amazoness Call ..."
    assert ruling["referenced_konami_ids"] == [13174, 8963, 5505, 5682]


def test_insert_ruling_defaults_to_unresolved_with_no_ids():
    from aijudge.db.rulings_repo import get_rulings_for_card, insert_ruling
    from tests.rulings_fixtures import AMAZONESS_CALL_RULING_2017

    card_id = _insert_amazoness_call()
    insert_ruling(card_id=card_id, ruling_text=AMAZONESS_CALL_RULING_2017, source="db.ygoresources")

    [ruling] = get_rulings_for_card(card_id)
    assert ruling["ruling_text_resolved"] is None
    assert ruling["referenced_konami_ids"] == []


def test_list_unresolved_rulings_and_update_ruling_resolution():
    from aijudge.db.rulings_repo import (
        get_rulings_for_card,
        insert_ruling,
        list_unresolved_rulings,
        update_ruling_resolution,
    )
    from tests.rulings_fixtures import AMAZONESS_CALL_RULING_2017

    card_id = _insert_amazoness_call()
    ruling_id = insert_ruling(card_id=card_id, ruling_text=AMAZONESS_CALL_RULING_2017, source="db.ygoresources")

    unresolved = list_unresolved_rulings()
    assert [r["id"] for r in unresolved] == [ruling_id]
    assert unresolved[0]["card_id"] == card_id

    update_ruling_resolution(ruling_id, ruling_text_resolved="resolved text", referenced_konami_ids=[13174, 8963])

    assert list_unresolved_rulings() == []
    [ruling] = get_rulings_for_card(card_id)
    assert ruling["ruling_text_resolved"] == "resolved text"
    assert ruling["referenced_konami_ids"] == [13174, 8963]
    assert ruling["ruling_text"] == AMAZONESS_CALL_RULING_2017
```

Append to `tests/db/test_cards_repo.py` (it already has the skip marker and a `TRUNCATE card CASCADE` setup; add
`from datetime import date` if not already imported):

```python
def _insert_digitron(**overrides):
    from aijudge.db.cards_repo import insert_card

    kwargs = dict(
        name="Digitron",
        card_text="A Cyberse born from the depths of cyberspace.",
        card_type="Normal Monster",
        race="Cyberse",
        source="ygoprodeck",
        fetched_at=date(2026, 10, 5),
        ygoprodeck_id="32295838",
        deterministic_parse_eligible=True,
    )
    kwargs.update(overrides)
    return insert_card(**kwargs)


def test_card_dict_carries_rulings_status_defaulting_to_none():
    from aijudge.db.cards_repo import get_card_by_id

    card_id = _insert_digitron()
    assert get_card_by_id(card_id)["rulings_status"] is None


def test_insert_card_stores_rulings_status_and_ygoresources_id():
    from aijudge.db.cards_repo import get_card_by_name

    _insert_digitron(rulings_status="fetched", ygoresources_id="13192")
    card = get_card_by_name("Digitron")
    assert card["rulings_status"] == "fetched"
    assert card["ygoresources_id"] == "13192"


def test_rulings_status_rejects_an_unknown_value():
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_digitron(rulings_status="maybe")


def test_set_card_rulings_source_updates_status_and_keeps_id_when_none_given():
    from aijudge.db.cards_repo import get_card_by_id, set_card_rulings_source

    card_id = _insert_digitron(ygoresources_id="13192")
    set_card_rulings_source(card_id, rulings_status="failed")

    card = get_card_by_id(card_id)
    assert card["rulings_status"] == "failed"
    assert card["ygoresources_id"] == "13192"


def test_list_cards_returns_every_card():
    from aijudge.db.cards_repo import list_cards

    _insert_digitron()
    assert [card["name"] for card in list_cards()] == ["Digitron"]
```

Create `tests/rulings_fixtures.py` (real data: ruling texts copied verbatim from `db.ygoresources` as stored in the
app DB on 2026-10-05; names from `https://db.ygoresources.com/data/idx/card/name/en`):

```python
"""Real ygoresources ruling texts and Konami ids shared by the rulings tests.

Copied verbatim from the app database's `rulings` rows (source db.ygoresources)
on 2026-10-05. Names come from https://db.ygoresources.com/data/idx/card/name/en.
"""

AMAZONESS_CALL_KONAMI_ID = 13174
AMAZONESS_QUEEN_KONAMI_ID = 8963
DIGITRON_KONAMI_ID = 13192

AMAZONESS_CALL_RULING_2017 = (
    "Q: I activate the second effect of <<13174>>, targeting an <<8963>> on my field. If my opponent chains "
    "<<5505>> and takes control of <<8963>>, how does the effect of <<13174>> resolve?\n"
    "A: Even if your opponent has taken control of the monster targeted with the second effect of <<13174>> when "
    "that effect resolves, the effect is applied normally. In this scenario, monsters on your field other than the "
    "targeted monster cannot attack this turn. (If you regain control of that <<8963>> this turn using an effect "
    "such as <<5682>>, etc., then it can attack all monsters on your opponent's field once each.)"
)

AMAZONESS_CALL_RULING_2026 = (
    "Q: I activate the『You can banish this card from your Graveyard, then target 1 \"Amazoness\" monster you "
    "control; this turn, that monster can attack all monsters your opponent controls, once each, also other "
    "monsters you control cannot attack』effect of <<13174>> in my Graveyard and targeted an <<8963>> that's "
    "face-up in my Monster Zone.\n\n"
    "If the opponent activates <<5914>> in response, and the targeted <<8963>> is returned to the hand and is no "
    "longer on the field, what happens to the effect's resolution?\n"
    "A: In the situation of the question, the <<8963>> that was targeted by the effect of <<13174>> activated in "
    "the Graveyard is no longer on the field, so as a result the『that monster can attack all monsters your "
    "opponent controls, once each』effect won'tbe applied, but the『this turn, other monsters you control "
    "cannot attack』effect will be applied, so your monsters can no longer attack this turn."
)

DIGITRON_RULING_2019 = (
    "Q: I Link Summon a <<13489>>, using a <<13034>> and <<13192>> as materials. At this time, can I activate 2 "
    "copies of <<14436>>?\n"
    "A: You can activate 2 copies of <<14436>> in the same Chain when you successfully Link Summon a monster. (In "
    "this scenario, since <<13034>> and <<13192>> were both sent to the Graveyard as materials, each of them can "
    "be targeted by the effect of <<14436>>.)"
)

# A real slice of /data/idx/card/name/en ({name: [konami_id, ...]}), covering
# every id the rulings above reference, plus Cyber Angel Benten's two names
# for the renamed-card case.
NAME_INDEX_SLICE = {
    "Amazoness Call": [13174],
    "Amazoness Queen": [8963],
    "Enemy Controller": [5505],
    "Remove Brainwashing": [5682],
    "Compulsory Evacuation Device": [5914],
    "Security Dragon": [13489],
    "Link Spider": [13034],
    "Digitron": [13192],
    "Cynet Cascade": [14436],
    "Cyber Angel - Benten": [6845],
    "Cyber Angel Benten": [6845],
}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/db/test_rulings_repo.py tests/db/test_cards_repo.py -v`
Expected: FAIL — `insert_ruling() got an unexpected keyword argument 'ruling_text_resolved'`, `KeyError: 'rulings_status'`, `ImportError: cannot import name 'list_cards'`.
(If they're all SKIPPED, `TEST_DATABASE_URL` isn't set — set it and make sure `docker ps` shows `aijudge-db-1`.)

- [ ] **Step 3: Implement**

`schema.sql` — append directly after the `rulings` `CREATE TABLE` block:

```sql
-- Rulings grounding (docs/superpowers/specs/2026-10-05-rulings-grounding-design.md).
-- rulings_status records whether ingestion's ygoresources fetch worked, so a
-- failed fetch is no longer indistinguishable from a card with no rulings.
-- NULL means a row created before this column existed.
ALTER TABLE card ADD COLUMN IF NOT EXISTS rulings_status TEXT;
DO $$ BEGIN
    ALTER TABLE card ADD CONSTRAINT card_rulings_status_check
        CHECK (rulings_status IN ('fetched', 'failed', 'no_konami_id') OR rulings_status IS NULL);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ruling_text stays exactly as ygoresources wrote it (<<konami_id>> placeholders
-- included); ruling_text_resolved is the readable form, NULL until resolved.
ALTER TABLE rulings ADD COLUMN IF NOT EXISTS ruling_text_resolved TEXT;
ALTER TABLE rulings ADD COLUMN IF NOT EXISTS referenced_konami_ids INTEGER[] NOT NULL DEFAULT '{}';
```

`cards_repo.py`:
- Append `"rulings_status"` to `_CARD_COLUMNS`.
- Replace (all six occurrences) the SELECT fragment `"ygoprodeck_id, ygoresources_id, deterministic_parse_eligible "`
  with `"ygoprodeck_id, ygoresources_id, deterministic_parse_eligible, rulings_status "`.
- `insert_card`: add the keyword parameter `rulings_status: str | None = None` after `ygoresources_id`, add
  `rulings_status` to the column list and one more `%s`, and pass `rulings_status` last in the values tuple:

```python
            INSERT INTO card (
                name, card_text, card_type, race, attribute, monster_type,
                level, rank, link_rating, archetype, atk, def,
                ygoprodeck_id, ygoresources_id, source, fetched_at, deterministic_parse_eligible,
                rulings_status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                name, card_text, card_type, race, attribute, monster_type,
                level, rank, link_rating, archetype, atk, def_,
                normalize_passcode(ygoprodeck_id), ygoresources_id, source, fetched_at, deterministic_parse_eligible,
                rulings_status,
            ),
```

- Add, after `list_card_names`:

```python
def list_cards() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, card_text, card_type, race, attribute, monster_type, "
            "level, rank, link_rating, archetype, atk, def, has_errata, "
            "ygoprodeck_id, ygoresources_id, deterministic_parse_eligible, rulings_status "
            "FROM card ORDER BY name"
        ).fetchall()
    return [dict(zip(_CARD_COLUMNS, [str(row[0])] + list(row[1:]))) for row in rows]


def set_card_rulings_source(
    card_id: str, *, rulings_status: str | None, ygoresources_id: str | None = None
) -> None:
    """Record a card's ygoresources rulings fetch outcome (and its Konami id,
    when known). A None ygoresources_id keeps whatever is already stored."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE card SET rulings_status = %s, ygoresources_id = COALESCE(%s, ygoresources_id) WHERE id = %s",
            (rulings_status, ygoresources_id, card_id),
        )
        conn.commit()
```

`rulings_repo.py` — replace the whole module with:

```python
from collections.abc import Sequence
from datetime import date

from .connection import get_connection

_RULING_SELECT = "SELECT id, ruling_text, source, ruling_date, ruling_text_resolved, referenced_konami_ids"


def _row_to_ruling(row) -> dict:
    return {
        "id": str(row[0]),
        "ruling_text": row[1],
        "source": row[2],
        "ruling_date": row[3],
        "ruling_text_resolved": row[4],
        "referenced_konami_ids": list(row[5] or []),
    }


def insert_ruling(
    *,
    card_id: str,
    ruling_text: str,
    source: str,
    ruling_date: date | None = None,
    ruling_text_resolved: str | None = None,
    referenced_konami_ids: Sequence[int] = (),
) -> str:
    with get_connection() as conn:
        row = conn.execute(
            """
            INSERT INTO rulings (card_id, ruling_text, source, ruling_date, ruling_text_resolved, referenced_konami_ids)
            VALUES (%s, %s, %s, %s, %s, %s::integer[])
            RETURNING id
            """,
            (card_id, ruling_text, source, ruling_date, ruling_text_resolved, list(referenced_konami_ids)),
        ).fetchone()
        conn.commit()
        return str(row[0])


def get_rulings_for_card(card_id: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(f"{_RULING_SELECT} FROM rulings WHERE card_id = %s", (card_id,)).fetchall()
    return [_row_to_ruling(r) for r in rows]


def list_unresolved_rulings() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            f"{_RULING_SELECT}, card_id FROM rulings WHERE ruling_text_resolved IS NULL ORDER BY id"
        ).fetchall()
    return [{**_row_to_ruling(r), "card_id": str(r[6])} for r in rows]


def update_ruling_resolution(
    ruling_id: str, *, ruling_text_resolved: str, referenced_konami_ids: Sequence[int]
) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE rulings SET ruling_text_resolved = %s, referenced_konami_ids = %s::integer[] WHERE id = %s",
            (ruling_text_resolved, list(referenced_konami_ids), ruling_id),
        )
        conn.commit()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/db -v`
Expected: PASS (including the pre-existing repo tests).

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/db/schema.sql src/aijudge/db/cards_repo.py src/aijudge/db/rulings_repo.py tests/db/test_rulings_repo.py tests/db/test_cards_repo.py tests/rulings_fixtures.py
git commit -m "feat(db): store rulings fetch status and resolved ruling text"
```

---

### Task 2: Placeholder parsing and name resolution (`ygoresources_client`)

**Files:**
- Modify: `src/aijudge/ingestion/ygoresources_client.py`
- Modify: `tests/conftest.py`
- Test: `tests/ingestion/test_ygoresources_client.py`

**Interfaces:**
- Consumes: `tests/rulings_fixtures.py` (Task 1).
- Produces (all in `aijudge.ingestion.ygoresources_client`):
  - `parse_referenced_ids(text: str) -> list[int]` — distinct ids, first-appearance order.
  - `invert_name_index(index: dict[str, list[int]]) -> dict[int, list[str]]`
  - `fetch_card_name_index(*, http_get=requests.get) -> dict[int, list[str]]`
  - `cached_card_name_index() -> dict[int, list[str]]` — `lru_cache(maxsize=1)` over the real fetch.
  - `fetch_current_card_name(konami_id: int, *, http_get=requests.get) -> str | None`
  - `resolve_ruling_text(text: str, name_index: dict[int, list[str]], *, http_get=requests.get) -> tuple[str, list[int]]`
  - `unresolved_display_text(text: str) -> str` — every `<<id>>` → `[card #id]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/ingestion/test_ygoresources_client.py` (it already defines `_FakeResponse`):

```python
from aijudge.ingestion.ygoresources_client import (
    fetch_card_name_index,
    invert_name_index,
    parse_referenced_ids,
    resolve_ruling_text,
    unresolved_display_text,
)
from tests.rulings_fixtures import (
    AMAZONESS_CALL_RULING_2017,
    DIGITRON_RULING_2019,
    NAME_INDEX_SLICE,
)


def _no_network(url, timeout):
    raise AssertionError(f"unexpected network call to {url}")


def test_parse_referenced_ids_returns_distinct_ids_in_first_appearance_order():
    assert parse_referenced_ids(AMAZONESS_CALL_RULING_2017) == [13174, 8963, 5505, 5682]


def test_parse_referenced_ids_ignores_text_without_numeric_placeholders():
    assert parse_referenced_ids("Q: Can I chain <<abc>> to it?\nA: No.") == []


def test_invert_name_index_maps_each_id_to_all_its_names():
    inverted = invert_name_index(NAME_INDEX_SLICE)
    assert inverted[13174] == ["Amazoness Call"]
    assert inverted[6845] == ["Cyber Angel - Benten", "Cyber Angel Benten"]


def test_fetch_card_name_index_downloads_and_inverts_the_english_index():
    def fake_get(url, timeout):
        assert url == "https://db.ygoresources.com/data/idx/card/name/en"
        return _FakeResponse(NAME_INDEX_SLICE)

    assert fetch_card_name_index(http_get=fake_get)[13192] == ["Digitron"]


def test_resolve_ruling_text_replaces_every_placeholder_with_its_name():
    index = invert_name_index(NAME_INDEX_SLICE)

    resolved, ids = resolve_ruling_text(AMAZONESS_CALL_RULING_2017, index, http_get=_no_network)

    assert ids == [13174, 8963, 5505, 5682]
    assert "<<" not in resolved
    assert resolved.startswith(
        "Q: I activate the second effect of Amazoness Call, targeting an Amazoness Queen on my field. "
        "If my opponent chains Enemy Controller and takes control of Amazoness Queen"
    )
    assert "using an effect such as Remove Brainwashing, etc." in resolved


def test_resolve_ruling_text_marks_an_id_missing_from_the_index_as_unknown():
    index = invert_name_index({"Digitron": [13192]})

    resolved, ids = resolve_ruling_text(DIGITRON_RULING_2019, index, http_get=_no_network)

    assert ids == [13489, 13034, 13192, 14436]
    assert resolved.startswith("Q: I Link Summon a [card #13489], using a [card #13034] and Digitron as materials.")


def test_resolve_ruling_text_asks_ygoresources_for_the_current_name_of_a_renamed_card():
    index = invert_name_index(NAME_INDEX_SLICE)

    def fake_get(url, timeout):
        assert url == "https://db.ygoresources.com/data/card/6845"
        return _FakeResponse({"cardData": {"en": {"name": "Cyber Angel Benten"}}})

    resolved, ids = resolve_ruling_text("Q: Does <<6845>> inflict damage?\nA: Yes.", index, http_get=fake_get)

    assert resolved == "Q: Does Cyber Angel Benten inflict damage?\nA: Yes."
    assert ids == [6845]


def test_resolve_ruling_text_marks_a_renamed_card_unknown_when_its_lookup_fails():
    index = invert_name_index(NAME_INDEX_SLICE)

    def failing_get(url, timeout):
        raise requests.ConnectionError("ygoresources unreachable")

    resolved, _ = resolve_ruling_text("Q: Does <<6845>> inflict damage?\nA: Yes.", index, http_get=failing_get)

    assert resolved == "Q: Does [card #6845] inflict damage?\nA: Yes."


def test_resolve_ruling_text_leaves_text_without_placeholders_unchanged():
    resolved, ids = resolve_ruling_text("Q: Can I chain <<abc>> to it?\nA: No.", {}, http_get=_no_network)
    assert resolved == "Q: Can I chain <<abc>> to it?\nA: No."
    assert ids == []


def test_unresolved_display_text_never_shows_a_bare_placeholder():
    assert unresolved_display_text("Q: Can <<13174>> target <<8963>>?") == "Q: Can [card #13174] target [card #8963]?"
```

Also add `import requests` at the top of that test file if it isn't there.

Add an autouse guard to `tests/conftest.py` so no test downloads the real ~520 KB index through the cached default
(tests that need an index pass one explicitly):

```python
@pytest.fixture(autouse=True)
def no_real_card_name_index(monkeypatch):
    """seed_card/backfill fall back to ygoresources_client.cached_card_name_index
    when no index function is injected; never let that reach the network in tests."""
    from aijudge.ingestion import ygoresources_client

    monkeypatch.setattr(ygoresources_client, "cached_card_name_index", lambda: {})
```

(Import `pytest` at the top of `tests/conftest.py` if it isn't already.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/ingestion/test_ygoresources_client.py -v`
Expected: FAIL — `ImportError: cannot import name 'fetch_card_name_index'`. (The conftest fixture also errors until
`cached_card_name_index` exists, which is expected at this step.)

- [ ] **Step 3: Implement**

Add to `src/aijudge/ingestion/ygoresources_client.py` (add `import functools` and `import logging` at the top):

```python
logger = logging.getLogger(__name__)

NAME_INDEX_URL = f"{BASE_URL}/data/idx/card/name/en"

_PLACEHOLDER_RE = re.compile(r"<<(\d+)>>")


def parse_referenced_ids(text: str) -> list[int]:
    """Every distinct Konami id ygoresources wrote as a <<id>> placeholder, in
    first-appearance order. Pure: needs no network, so it works even when the
    name index can't be fetched."""
    ids: list[int] = []
    for match in _PLACEHOLDER_RE.finditer(text):
        konami_id = int(match.group(1))
        if konami_id not in ids:
            ids.append(konami_id)
    return ids


def invert_name_index(index: dict[str, list[int]]) -> dict[int, list[str]]:
    inverted: dict[int, list[str]] = {}
    for name, konami_ids in index.items():
        for konami_id in konami_ids:
            inverted.setdefault(konami_id, []).append(name)
    return inverted


def fetch_card_name_index(*, http_get: Callable[..., "requests.Response"] = requests.get) -> dict[int, list[str]]:
    response = http_get(NAME_INDEX_URL, timeout=30)
    response.raise_for_status()
    return invert_name_index(response.json())


@functools.lru_cache(maxsize=1)
def cached_card_name_index() -> dict[int, list[str]]:
    """One download per process: the on-demand lookup_card path ingests cards
    one at a time, and the index is large and slow-changing. Exceptions aren't
    cached by lru_cache, so a failed download is retried next time."""
    return fetch_card_name_index()


def fetch_current_card_name(
    konami_id: int, *, http_get: Callable[..., "requests.Response"] = requests.get
) -> str | None:
    response = http_get(f"{BASE_URL}/data/card/{konami_id}", timeout=10)
    response.raise_for_status()
    return ((response.json().get("cardData") or {}).get("en") or {}).get("name")


def _unknown_card(konami_id: int | str) -> str:
    return f"[card #{konami_id}]"


def resolve_ruling_text(
    text: str,
    name_index: dict[int, list[str]],
    *,
    http_get: Callable[..., "requests.Response"] = requests.get,
) -> tuple[str, list[int]]:
    """Replace each <<id>> with that card's English name. A renamed card (more
    than one name in the index) is looked up for its single current name. An
    id that can't be named becomes "[card #id]" -- never a guess."""
    ids = parse_referenced_ids(text)
    names: dict[int, str | None] = {}
    for konami_id in ids:
        candidates = name_index.get(konami_id, [])
        if len(candidates) == 1:
            names[konami_id] = candidates[0]
        elif len(candidates) > 1:
            try:
                names[konami_id] = fetch_current_card_name(konami_id, http_get=http_get)
            except requests.RequestException:
                logger.exception("could not fetch the current name of konami_id=%s", konami_id)
                names[konami_id] = None

    def replace(match: re.Match) -> str:
        konami_id = int(match.group(1))
        return names.get(konami_id) or _unknown_card(konami_id)

    return _PLACEHOLDER_RE.sub(replace, text), ids


def unresolved_display_text(text: str) -> str:
    """Display form of a ruling whose names were never resolved."""
    return _PLACEHOLDER_RE.sub(lambda match: _unknown_card(match.group(1)), text)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/ingestion/test_ygoresources_client.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/ingestion/ygoresources_client.py tests/ingestion/test_ygoresources_client.py tests/conftest.py
git commit -m "feat(ingestion): resolve ygoresources card-id placeholders to names"
```

---

### Task 3: Record the rulings fetch outcome in `seed_card`

**Files:**
- Modify: `src/aijudge/ingestion/seed.py` (the rulings section, currently lines 63–89)
- Test: `tests/ingestion/test_seed.py`

**Interfaces:**
- Consumes: Task 1 `insert_card(rulings_status=...)`, `insert_ruling(ruling_text_resolved=..., referenced_konami_ids=...)`; Task 2 `resolve_ruling_text`, `parse_referenced_ids`, `cached_card_name_index`.
- Produces: `seed_card(..., fetch_card_name_index_fn: Callable[[], dict[int, list[str]]] | None = None)`. `None` means `ygoresources_client.cached_card_name_index`, looked up at call time (so the conftest guard applies).

- [ ] **Step 1: Write the failing tests**

Append to `tests/ingestion/test_seed.py`:

```python
def _amazoness_call_card_data(name, **_kwargs):
    return {
        "id": 57312333,
        "name": name,
        "type": "Spell Card",
        "race": "Quick-Play",
        "desc": (
            'Take 1 "Amazoness" card from your Deck, except "Amazoness Call", and either add it to your hand or '
            'send it to the GY. During your Main Phase: You can banish this card from your GY, then target 1 '
            '"Amazoness" monster you control; this turn, that monster can attack all monsters your opponent '
            'controls, once each, also other monsters you control cannot attack. You can only activate 1 '
            '"Amazoness Call" per turn.'
        ),
        "misc_info": [{"konami_id": 13174}],
        "card_sets": [{"set_name": "Some Set"}],
    }


def _seed_amazoness_call(**kwargs):
    from aijudge.ingestion.seed import seed_card
    from aijudge.llm.client import MockLLMClient

    kwargs.setdefault("fetch_card_fn", _amazoness_call_card_data)
    kwargs.setdefault("fetch_sets_index_fn", lambda: {"Some Set": date(2020, 1, 1)})
    return seed_card("Amazoness Call", llm_client=MockLLMClient(), **kwargs)


def test_seed_card_stores_konami_id_status_and_resolved_rulings():
    from aijudge.db.cards_repo import get_card_by_id
    from aijudge.db.rulings_repo import get_rulings_for_card
    from aijudge.ingestion.ygoresources_client import invert_name_index
    from tests.rulings_fixtures import AMAZONESS_CALL_RULING_2017, NAME_INDEX_SLICE

    card_id = _seed_amazoness_call(
        fetch_rulings_fn=lambda konami_id: [{"text": AMAZONESS_CALL_RULING_2017, "date": "2017-07-22"}],
        fetch_card_name_index_fn=lambda: invert_name_index(NAME_INDEX_SLICE),
    )

    card = get_card_by_id(card_id)
    assert card["ygoresources_id"] == "13174"
    assert card["rulings_status"] == "fetched"
    [ruling] = get_rulings_for_card(card_id)
    assert ruling["ruling_text"] == AMAZONESS_CALL_RULING_2017
    assert ruling["ruling_text_resolved"].startswith("Q: I activate the second effect of Amazoness Call")
    assert ruling["referenced_konami_ids"] == [13174, 8963, 5505, 5682]


def test_seed_card_marks_zero_rulings_as_fetched():
    from aijudge.db.cards_repo import get_card_by_id

    card_id = _seed_amazoness_call(fetch_rulings_fn=lambda konami_id: [])

    assert get_card_by_id(card_id)["rulings_status"] == "fetched"


def test_seed_card_marks_a_failed_rulings_fetch_as_failed():
    from aijudge.db.cards_repo import get_card_by_id
    from aijudge.db.rulings_repo import get_rulings_for_card

    def failing_fetch(konami_id):
        raise requests.ConnectionError("ygoresources unreachable")

    card_id = _seed_amazoness_call(fetch_rulings_fn=failing_fetch)

    card = get_card_by_id(card_id)
    assert card["rulings_status"] == "failed"
    assert card["ygoresources_id"] == "13174"
    assert get_rulings_for_card(card_id) == []


def test_seed_card_marks_a_card_without_a_konami_id():
    from aijudge.db.cards_repo import get_card_by_id

    def card_data_without_konami_id(name, **_kwargs):
        data = _amazoness_call_card_data(name)
        data["misc_info"] = [{}]
        return data

    def must_not_fetch(konami_id):
        raise AssertionError("no konami_id, nothing to fetch")

    card_id = _seed_amazoness_call(fetch_card_fn=card_data_without_konami_id, fetch_rulings_fn=must_not_fetch)

    card = get_card_by_id(card_id)
    assert card["rulings_status"] == "no_konami_id"
    assert card["ygoresources_id"] is None


def test_seed_card_still_stores_rulings_when_the_name_index_is_unavailable():
    from aijudge.db.cards_repo import get_card_by_id
    from aijudge.db.rulings_repo import get_rulings_for_card
    from tests.rulings_fixtures import AMAZONESS_CALL_RULING_2017

    def failing_index():
        raise requests.ConnectionError("ygoresources unreachable")

    card_id = _seed_amazoness_call(
        fetch_rulings_fn=lambda konami_id: [{"text": AMAZONESS_CALL_RULING_2017, "date": "2017-07-22"}],
        fetch_card_name_index_fn=failing_index,
    )

    assert get_card_by_id(card_id)["rulings_status"] == "fetched"
    [ruling] = get_rulings_for_card(card_id)
    assert ruling["ruling_text_resolved"] is None
    assert ruling["referenced_konami_ids"] == [13174, 8963, 5505, 5682]
```

In the existing `test_seed_card_continues_when_fetching_rulings_fails`, add after its last assertion:

```python
    from aijudge.db.cards_repo import get_card_by_id

    assert get_card_by_id(card_id)["rulings_status"] == "failed"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/ingestion/test_seed.py -v`
Expected: the new tests FAIL (`unexpected keyword argument 'fetch_card_name_index_fn'`, `rulings_status` is `None`).

- [ ] **Step 3: Implement**

In `seed.py`: add `import logging`, `logger = logging.getLogger(__name__)`, change the `ygoresources_client`
import to `from aijudge.ingestion import ygoresources_client` plus
`from aijudge.ingestion.ygoresources_client import fetch_rulings, parse_referenced_ids, resolve_ruling_text`.

Add these helpers above `seed_card`:

```python
def _fetch_rulings_outcome(
    konami_id: int | None, fetch_rulings_fn: Callable[..., list[dict]]
) -> tuple[list[dict], str]:
    """The rulings plus card.rulings_status. A failed fetch is recorded as
    'failed' instead of looking exactly like a card with no rulings."""
    if konami_id is None:
        return [], "no_konami_id"
    try:
        return fetch_rulings_fn(konami_id), "fetched"
    except Exception:
        logger.exception("rulings fetch failed for konami_id=%s", konami_id)
        return [], "failed"


def _load_name_index(
    fetch_card_name_index_fn: Callable[[], dict[int, list[str]]] | None,
) -> dict[int, list[str]] | None:
    fetch_index = fetch_card_name_index_fn or ygoresources_client.cached_card_name_index
    try:
        return fetch_index()
    except Exception:
        logger.exception("card name index unavailable; rulings stored unresolved")
        return None


def _insert_rulings(card_id: str, rulings: list[dict], name_index: dict[int, list[str]] | None) -> None:
    for ruling in rulings:
        raw_date = ruling.get("date")
        if name_index is not None:
            resolved, referenced_ids = resolve_ruling_text(ruling["text"], name_index)
        else:
            resolved, referenced_ids = None, parse_referenced_ids(ruling["text"])
        insert_ruling(
            card_id=card_id,
            ruling_text=ruling["text"],
            source="db.ygoresources",
            ruling_date=date.fromisoformat(raw_date) if raw_date else None,
            ruling_text_resolved=resolved,
            referenced_konami_ids=referenced_ids,
        )
```

Change `seed_card`: add the parameter `fetch_card_name_index_fn: Callable[[], dict[int, list[str]]] | None = None`
after `fetch_sets_index_fn`. Move the Konami id lookup and rulings fetch **before** `insert_card`, pass the outcome
into `insert_card`, and replace the old `try/except` + `for ruling in rulings:` block:

```python
    misc_info = card_data.get("misc_info") or [{}]
    konami_id = misc_info[0].get("konami_id")
    rulings, rulings_status = _fetch_rulings_outcome(konami_id, fetch_rulings_fn)

    card_id = insert_card(
        name=card_data["name"],
        card_text=card_text,
        card_type=card_type,
        race=race,
        source="ygoprodeck",
        fetched_at=datetime.now(timezone.utc).date(),
        ygoprodeck_id=str(card_data["id"]),
        deterministic_parse_eligible=eligible,
        ygoresources_id=str(konami_id) if konami_id is not None else None,
        rulings_status=rulings_status,
    )

    if rulings:
        _insert_rulings(card_id, rulings, _load_name_index(fetch_card_name_index_fn))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/ingestion tests/orchestration/test_tools.py tests/orchestration/test_tools_db.py -v`
Expected: PASS (existing seed tests still pass; their plain-text rulings have no placeholders, and the conftest
guard supplies an empty index).

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/ingestion/seed.py tests/ingestion/test_seed.py
git commit -m "feat(ingestion): record rulings fetch status and resolve names at ingest"
```

---

### Task 4: Backfill for cards ingested before this change

**Files:**
- Create: `src/aijudge/ingestion/rulings_backfill.py`
- Test: `tests/ingestion/test_rulings_backfill.py`

**Interfaces:**
- Consumes: Task 1 `list_cards`, `set_card_rulings_source`, `get_rulings_for_card`, `insert_ruling`, `list_unresolved_rulings`, `update_ruling_resolution`; Task 2 `resolve_ruling_text`, `parse_referenced_ids`, `cached_card_name_index`; existing `ygoprodeck_client.fetch_card(query, *, field=None)` and `ygoresources_client.fetch_rulings(konami_id)`.
- Produces: `backfill_rulings(*, fetch_card_fn=fetch_card, fetch_rulings_fn=fetch_rulings, fetch_card_name_index_fn=None) -> BackfillReport`; `BackfillReport(konami_ids_stored: int, rulings_refetched: int, rulings_resolved: int, failures: list[str])`.

- [ ] **Step 1: Write the failing tests**

Create `tests/ingestion/test_rulings_backfill.py`:

```python
import os
from datetime import date

import pytest
import requests

pytestmark = pytest.mark.skipif("TEST_DATABASE_URL" not in os.environ, reason="requires TEST_DATABASE_URL (a dedicated test Postgres database)")


def setup_function():
    from aijudge.db.connection import get_connection
    from aijudge.db.migrate import run_migrations

    run_migrations()
    with get_connection() as conn:
        conn.execute("TRUNCATE card CASCADE")
        conn.commit()


def _insert_legacy_card(name, passcode, card_type, race, card_text):
    """A card as ingested before this change: no Konami id, NULL status."""
    from aijudge.db.cards_repo import insert_card

    return insert_card(
        name=name,
        card_text=card_text,
        card_type=card_type,
        race=race,
        source="ygoprodeck",
        fetched_at=date(2026, 9, 1),
        ygoprodeck_id=passcode,
        deterministic_parse_eligible=True,
    )


def _index():
    from aijudge.ingestion.ygoresources_client import invert_name_index
    from tests.rulings_fixtures import NAME_INDEX_SLICE

    return invert_name_index(NAME_INDEX_SLICE)


def _fake_fetch_card(konami_ids):
    def fetch(query, *, field=None):
        assert field == "id"
        return {"misc_info": [{"konami_id": konami_ids[query]}]}

    return fetch


def test_backfill_refetches_a_legacy_card_with_zero_rulings_and_resolves_them():
    from aijudge.db.cards_repo import get_card_by_id
    from aijudge.db.rulings_repo import get_rulings_for_card
    from aijudge.ingestion.rulings_backfill import backfill_rulings
    from tests.rulings_fixtures import DIGITRON_RULING_2019

    card_id = _insert_legacy_card(
        "Digitron", "32295838", "Normal Monster", "Cyberse", "A Cyberse born from the depths of cyberspace."
    )

    report = backfill_rulings(
        fetch_card_fn=_fake_fetch_card({"32295838": 13192}),
        fetch_rulings_fn=lambda konami_id: [{"text": DIGITRON_RULING_2019, "date": "2019-03-23"}],
        fetch_card_name_index_fn=_index,
    )

    card = get_card_by_id(card_id)
    assert card["ygoresources_id"] == "13192"
    assert card["rulings_status"] == "fetched"
    [ruling] = get_rulings_for_card(card_id)
    assert ruling["ruling_text_resolved"].startswith("Q: I Link Summon a Security Dragon, using a Link Spider and Digitron")
    assert (report.konami_ids_stored, report.rulings_refetched, report.rulings_resolved) == (1, 1, 1)
    assert report.failures == []


def test_backfill_marks_a_card_with_existing_rulings_fetched_without_duplicating_them():
    from aijudge.db.cards_repo import get_card_by_id
    from aijudge.db.rulings_repo import get_rulings_for_card, insert_ruling
    from aijudge.ingestion.rulings_backfill import backfill_rulings
    from tests.rulings_fixtures import AMAZONESS_CALL_RULING_2017

    card_id = _insert_legacy_card(
        "Amazoness Call", "57312333", "Spell Card", "Quick-Play",
        'Take 1 "Amazoness" card from your Deck, except "Amazoness Call", and either add it to your hand or send it to the GY.',
    )
    insert_ruling(card_id=card_id, ruling_text=AMAZONESS_CALL_RULING_2017, source="db.ygoresources")

    def must_not_refetch(konami_id):
        raise AssertionError("existing rulings prove the original fetch worked")

    backfill_rulings(
        fetch_card_fn=_fake_fetch_card({"57312333": 13174}),
        fetch_rulings_fn=must_not_refetch,
        fetch_card_name_index_fn=_index,
    )

    assert get_card_by_id(card_id)["rulings_status"] == "fetched"
    [ruling] = get_rulings_for_card(card_id)
    assert ruling["ruling_text_resolved"].startswith("Q: I activate the second effect of Amazoness Call")


def test_backfill_records_a_failed_refetch_and_reports_it():
    from aijudge.db.cards_repo import get_card_by_id
    from aijudge.ingestion.rulings_backfill import backfill_rulings

    card_id = _insert_legacy_card(
        "Digitron", "32295838", "Normal Monster", "Cyberse", "A Cyberse born from the depths of cyberspace."
    )

    def failing_fetch(konami_id):
        raise requests.ConnectionError("ygoresources unreachable")

    report = backfill_rulings(
        fetch_card_fn=_fake_fetch_card({"32295838": 13192}),
        fetch_rulings_fn=failing_fetch,
        fetch_card_name_index_fn=_index,
    )

    assert get_card_by_id(card_id)["rulings_status"] == "failed"
    assert report.failures == ["Digitron"]


def test_backfill_is_a_no_op_on_a_second_run():
    from aijudge.db.rulings_repo import get_rulings_for_card
    from aijudge.ingestion.rulings_backfill import backfill_rulings
    from tests.rulings_fixtures import DIGITRON_RULING_2019

    card_id = _insert_legacy_card(
        "Digitron", "32295838", "Normal Monster", "Cyberse", "A Cyberse born from the depths of cyberspace."
    )
    kwargs = dict(
        fetch_card_fn=_fake_fetch_card({"32295838": 13192}),
        fetch_rulings_fn=lambda konami_id: [{"text": DIGITRON_RULING_2019, "date": "2019-03-23"}],
        fetch_card_name_index_fn=_index,
    )
    backfill_rulings(**kwargs)

    second = backfill_rulings(**kwargs)

    assert (second.konami_ids_stored, second.rulings_refetched, second.rulings_resolved) == (0, 0, 0)
    assert len(get_rulings_for_card(card_id)) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/ingestion/test_rulings_backfill.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aijudge.ingestion.rulings_backfill'`.

- [ ] **Step 3: Implement**

Create `src/aijudge/ingestion/rulings_backfill.py`:

```python
"""One-off, re-runnable backfill for cards ingested before rulings grounding.

Stores each card's Konami id, re-fetches rulings for cards whose stored "zero
rulings" may have been a silently swallowed fetch failure, and resolves every
ruling's <<konami_id>> placeholders. Never deletes a ruling or rewrites its
raw text. Run after run_migrations():

    python -c "from aijudge.ingestion.rulings_backfill import backfill_rulings; print(backfill_rulings())"
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from aijudge.db.cards_repo import list_cards, set_card_rulings_source
from aijudge.db.rulings_repo import (
    get_rulings_for_card,
    insert_ruling,
    list_unresolved_rulings,
    update_ruling_resolution,
)
from aijudge.ingestion import ygoresources_client
from aijudge.ingestion.ygoprodeck_client import fetch_card
from aijudge.ingestion.ygoresources_client import fetch_rulings, parse_referenced_ids, resolve_ruling_text

logger = logging.getLogger(__name__)


@dataclass
class BackfillReport:
    konami_ids_stored: int = 0
    rulings_refetched: int = 0
    rulings_resolved: int = 0
    failures: list[str] = field(default_factory=list)


def _store_konami_id(card: dict, fetch_card_fn: Callable[..., dict], report: BackfillReport) -> int | None:
    try:
        # YGOPRODeck takes the passcode as a number; int() drops the printed leading zero.
        card_data = fetch_card_fn(str(int(card["ygoprodeck_id"])), field="id")
    except Exception:
        logger.exception("could not fetch %s from YGOPRODeck", card["name"])
        report.failures.append(card["name"])
        return None
    konami_id = (card_data.get("misc_info") or [{}])[0].get("konami_id")
    if konami_id is None:
        set_card_rulings_source(card["id"], rulings_status="no_konami_id")
        return None
    set_card_rulings_source(card["id"], rulings_status=card["rulings_status"], ygoresources_id=str(konami_id))
    report.konami_ids_stored += 1
    return konami_id


def _refetch_if_empty(
    card: dict, konami_id: int, fetch_rulings_fn: Callable[..., list[dict]], report: BackfillReport
) -> None:
    if get_rulings_for_card(card["id"]):
        set_card_rulings_source(card["id"], rulings_status="fetched")
        return
    try:
        rulings = fetch_rulings_fn(konami_id)
    except Exception:
        logger.exception("rulings refetch failed for %s", card["name"])
        set_card_rulings_source(card["id"], rulings_status="failed")
        report.failures.append(card["name"])
        return
    for ruling in rulings:
        raw_date = ruling.get("date")
        insert_ruling(
            card_id=card["id"],
            ruling_text=ruling["text"],
            source="db.ygoresources",
            ruling_date=date.fromisoformat(raw_date) if raw_date else None,
            referenced_konami_ids=parse_referenced_ids(ruling["text"]),
        )
    report.rulings_refetched += len(rulings)
    set_card_rulings_source(card["id"], rulings_status="fetched")


def backfill_rulings(
    *,
    fetch_card_fn: Callable[..., dict] = fetch_card,
    fetch_rulings_fn: Callable[..., list[dict]] = fetch_rulings,
    fetch_card_name_index_fn: Callable[[], dict[int, list[str]]] | None = None,
) -> BackfillReport:
    report = BackfillReport()

    for card in list_cards():
        if card["rulings_status"] == "no_konami_id":
            continue
        konami_id = int(card["ygoresources_id"]) if card["ygoresources_id"] else None
        if konami_id is None:
            konami_id = _store_konami_id(card, fetch_card_fn, report)
            if konami_id is None:
                continue
        if card["rulings_status"] in (None, "failed"):
            _refetch_if_empty(card, konami_id, fetch_rulings_fn, report)

    unresolved = list_unresolved_rulings()
    if not unresolved:
        return report
    fetch_index = fetch_card_name_index_fn or ygoresources_client.cached_card_name_index
    try:
        name_index = fetch_index()
    except Exception:
        logger.exception("card name index unavailable; rulings left unresolved")
        report.failures.append("card name index")
        return report
    for ruling in unresolved:
        resolved, referenced_ids = resolve_ruling_text(ruling["ruling_text"], name_index)
        update_ruling_resolution(ruling["id"], ruling_text_resolved=resolved, referenced_konami_ids=referenced_ids)
        report.rulings_resolved += 1
    return report
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/ingestion/test_rulings_backfill.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/ingestion/rulings_backfill.py tests/ingestion/test_rulings_backfill.py
git commit -m "feat(ingestion): add re-runnable rulings backfill"
```

---

### Task 5: Select and render rulings (`orchestration/rulings_context.py`)

**Files:**
- Create: `src/aijudge/orchestration/rulings_context.py`
- Test: `tests/orchestration/test_rulings_context.py`

**Interfaces:**
- Consumes: Task 1 `rulings_repo.get_rulings_for_card` (ruling dict keys listed there); Task 2 `unresolved_display_text`. Card dicts as returned by `cards_repo` (keys used: `id`, `name`, `ygoresources_id`, `rulings_status`).
- Produces:
  - `DEFAULT_RULINGS_BUDGET_CHARS = 6000`, `RULINGS_HEADER: str`
  - `@dataclass RulingsGrounding(context: str = "", rulings_by_card_id: dict[str, list[dict]] = {})` — each ruling dict is the repo dict plus `"display_text": str`.
  - `build_rulings_grounding(cards: list[dict], *, budget_chars: int = DEFAULT_RULINGS_BUDGET_CHARS) -> RulingsGrounding`
  - `attach_rulings(grounded_cards: list[dict], cards: list[dict], grounding: RulingsGrounding) -> list[dict]` — returns copies of `grounded_cards` (paired with `cards` by position) with `"rulings"` and `"rulings_status"` added.
  - `join_context(*parts: str) -> str` — joins the non-empty parts with a blank line.

- [ ] **Step 1: Write the failing tests**

Create `tests/orchestration/test_rulings_context.py`:

```python
from datetime import date

import pytest

from aijudge.orchestration import rulings_context
from aijudge.orchestration.rulings_context import (
    RULINGS_HEADER,
    RulingsGrounding,
    attach_rulings,
    build_rulings_grounding,
    join_context,
)
from tests.rulings_fixtures import (
    AMAZONESS_CALL_RULING_2017,
    AMAZONESS_CALL_RULING_2026,
    DIGITRON_RULING_2019,
)

AMAZONESS_CALL = {
    "id": "card-amazoness-call",
    "name": "Amazoness Call",
    "ygoresources_id": "13174",
    "rulings_status": "fetched",
}
AMAZONESS_QUEEN = {
    "id": "card-amazoness-queen",
    "name": "Amazoness Queen",
    "ygoresources_id": "8963",
    "rulings_status": "fetched",
}
DIGITRON = {"id": "card-digitron", "name": "Digitron", "ygoresources_id": "13192", "rulings_status": "fetched"}


def _ruling(ruling_id, raw_text, ruling_date, referenced_ids, resolved=None):
    return {
        "id": ruling_id,
        "ruling_text": raw_text,
        "source": "db.ygoresources",
        "ruling_date": ruling_date,
        "ruling_text_resolved": resolved,
        "referenced_konami_ids": referenced_ids,
    }


# 2026 references Amazoness Queen (8963); the 2025-dated stand-in does not.
CALL_2017 = _ruling("r-2017", AMAZONESS_CALL_RULING_2017, date(2017, 7, 22), [13174, 8963, 5505, 5682],
                    resolved="Q: Amazoness Call 2017 ruling (resolved).")
CALL_2026 = _ruling("r-2026", AMAZONESS_CALL_RULING_2026, date(2026, 1, 1), [13174, 8963, 5914],
                    resolved="Q: Amazoness Call 2026 ruling (resolved).")
CALL_NO_QUEEN = _ruling("r-2025", "Q: <<6000>> and <<5020>> attack targets.\nA: No, you cannot.", date(2025, 7, 13),
                        [6000, 5020], resolved="Q: Marshmallon and Patrician of Darkness attack targets.\nA: No, you cannot.")
DIGITRON_2019 = _ruling("r-dig", DIGITRON_RULING_2019, date(2019, 3, 23), [13489, 13034, 13192, 14436])


@pytest.fixture
def stored(monkeypatch):
    by_card = {}
    monkeypatch.setattr(rulings_context, "get_rulings_for_card", lambda card_id: list(by_card.get(card_id, [])))
    return by_card


def _ids(grounding, card):
    return [r["id"] for r in grounding.rulings_by_card_id[card["id"]]]


def test_no_cards_gives_an_empty_grounding(stored):
    assert build_rulings_grounding([]) == RulingsGrounding()


def test_newest_first_when_no_other_card_is_in_the_question(stored):
    stored[AMAZONESS_CALL["id"]] = [CALL_2017, CALL_NO_QUEEN, CALL_2026]

    grounding = build_rulings_grounding([AMAZONESS_CALL])

    assert _ids(grounding, AMAZONESS_CALL) == ["r-2026", "r-2025", "r-2017"]
    assert grounding.context.startswith(RULINGS_HEADER)
    assert "- ruling:r-2026 (Amazoness Call, 2026-01-01): Q: Amazoness Call 2026 ruling (resolved)." in grounding.context


def test_rulings_that_mention_another_card_in_the_question_come_first(stored):
    stored[AMAZONESS_CALL["id"]] = [CALL_NO_QUEEN, CALL_2017, CALL_2026]

    grounding = build_rulings_grounding([AMAZONESS_CALL, AMAZONESS_QUEEN])

    # Both Queen-referencing rulings (newest first) beat the newer non-Queen one.
    assert _ids(grounding, AMAZONESS_CALL) == ["r-2026", "r-2017", "r-2025"]


def test_undated_rulings_sort_last(stored):
    undated = {**CALL_2026, "id": "r-undated", "ruling_text": "Q: undated\nA: yes", "ruling_date": None}
    stored[AMAZONESS_CALL["id"]] = [undated, CALL_2017]

    grounding = build_rulings_grounding([AMAZONESS_CALL])

    assert _ids(grounding, AMAZONESS_CALL) == ["r-2017", "r-undated"]
    assert "(Amazoness Call, undated)" in grounding.context


def test_budget_skips_a_ruling_that_does_not_fit_and_tries_the_next(stored):
    long_ruling = {**CALL_2026, "ruling_text_resolved": "Q: " + "x" * 400}
    stored[AMAZONESS_CALL["id"]] = [long_ruling, CALL_2017]
    short_line = rulings_context.render_ruling_line(AMAZONESS_CALL, CALL_2017)

    grounding = build_rulings_grounding([AMAZONESS_CALL], budget_chars=len(short_line) + 10)

    assert _ids(grounding, AMAZONESS_CALL) == ["r-2017"]
    assert "- Amazoness Call: 1 more ruling not shown (context budget)." in grounding.context
    assert "x" * 400 not in grounding.context  # never truncated into the block


def test_unused_share_is_pooled_for_another_cards_skipped_ruling(stored):
    stored[AMAZONESS_CALL["id"]] = [CALL_2026, CALL_2017]
    stored[DIGITRON["id"]] = []
    line_2026 = rulings_context.render_ruling_line(AMAZONESS_CALL, CALL_2026)
    line_2017 = rulings_context.render_ruling_line(AMAZONESS_CALL, CALL_2017)
    # Each card's share fits only one Amazoness Call ruling; Digitron's unused
    # share must carry the second one.
    budget = 2 * max(len(line_2026), len(line_2017))

    grounding = build_rulings_grounding([AMAZONESS_CALL, DIGITRON], budget_chars=budget)

    assert _ids(grounding, AMAZONESS_CALL) == ["r-2026", "r-2017"]
    assert "not shown" not in grounding.context


def test_a_qa_stored_under_two_grounded_cards_is_rendered_once(stored):
    stored[AMAZONESS_CALL["id"]] = [CALL_2017]
    stored[AMAZONESS_QUEEN["id"]] = [{**CALL_2017, "id": "r-2017-queen-copy"}]

    grounding = build_rulings_grounding([AMAZONESS_CALL, AMAZONESS_QUEEN])

    assert _ids(grounding, AMAZONESS_CALL) == ["r-2017"]
    assert _ids(grounding, AMAZONESS_QUEEN) == []
    assert "Amazoness Queen: no official rulings on record" not in grounding.context


def test_a_card_with_no_rulings_is_reported_as_having_none(stored):
    grounding = build_rulings_grounding([DIGITRON])
    assert "- Digitron: no official rulings on record." in grounding.context


def test_a_failed_fetch_is_reported_as_unretrievable(stored):
    grounding = build_rulings_grounding([{**DIGITRON, "rulings_status": "failed"}])
    assert "- Digitron: rulings could not be retrieved -- do not guess what they say." in grounding.context


def test_a_pre_backfill_card_renders_unknown_card_markers_without_crashing(stored):
    legacy_card = {**DIGITRON, "ygoresources_id": None, "rulings_status": None}
    stored[DIGITRON["id"]] = [DIGITRON_2019]

    grounding = build_rulings_grounding([legacy_card, AMAZONESS_CALL])

    assert "Q: I Link Summon a [card #13489], using a [card #13034] and [card #13192]" in grounding.context
    assert "<<" not in grounding.context
    [ruling] = grounding.rulings_by_card_id[DIGITRON["id"]]
    assert ruling["display_text"].startswith("Q: I Link Summon a [card #13489]")


def test_attach_rulings_adds_rulings_and_status_to_each_grounded_card(stored):
    stored[AMAZONESS_CALL["id"]] = [CALL_2017]
    grounding = build_rulings_grounding([AMAZONESS_CALL])
    grounded = [{"found": True, "id": AMAZONESS_CALL["id"], "name": "Amazoness Call", "confirmed_effects": []}]

    [attached] = attach_rulings(grounded, [AMAZONESS_CALL], grounding)

    assert [r["id"] for r in attached["rulings"]] == ["r-2017"]
    assert attached["rulings_status"] == "fetched"
    assert "rulings" not in grounded[0]  # the input isn't mutated


def test_join_context_skips_empty_parts():
    assert join_context("KNOWN FACTS", "", "RULINGS") == "KNOWN FACTS\n\nRULINGS"
    assert join_context("", "") == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/orchestration/test_rulings_context.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aijudge.orchestration.rulings_context'`.

- [ ] **Step 3: Implement**

Create `src/aijudge/orchestration/rulings_context.py`:

```python
"""Deterministic selection and rendering of a question's stored rulings.

Given every card grounded for a question, picks which of their stored
ygoresources Q&As fit in the prompt -- rulings that mention another card in
the same question first, then newest first -- and renders them as one RULINGS
block. Rulings are included whole or not at all: a cut could drop the "A:"
half. Nothing here calls an LLM or the network.
"""

from dataclasses import dataclass, field

from aijudge.db.rulings_repo import get_rulings_for_card
from aijudge.ingestion.ygoresources_client import unresolved_display_text

DEFAULT_RULINGS_BUDGET_CHARS = 6000

RULINGS_HEADER = (
    "RULINGS (official Q&A from db.ygoresources -- do not contradict. A ruling applies only when the "
    "question's situation matches it. Cite each ruling you rely on as ruling:<id>.):"
)


@dataclass
class RulingsGrounding:
    context: str = ""
    rulings_by_card_id: dict[str, list[dict]] = field(default_factory=dict)


def join_context(*parts: str) -> str:
    return "\n\n".join(part for part in parts if part)


def _display_text(ruling: dict) -> str:
    return ruling["ruling_text_resolved"] or unresolved_display_text(ruling["ruling_text"])


def render_ruling_line(card: dict, ruling: dict) -> str:
    date_text = ruling["ruling_date"].isoformat() if ruling["ruling_date"] else "undated"
    return f"- ruling:{ruling['id']} ({card['name']}, {date_text}): {_display_text(ruling)}"


def _konami_id(card: dict) -> int | None:
    value = card.get("ygoresources_id")
    return int(value) if value else None


def _rank_key(ruling: dict, other_konami_ids: set[int]) -> tuple:
    mentions_other_card = bool(set(ruling["referenced_konami_ids"]) & other_konami_ids)
    ruling_date = ruling["ruling_date"]
    return (
        not mentions_other_card,
        ruling_date is None,
        -ruling_date.toordinal() if ruling_date else 0,
        ruling["id"],
    )


def build_rulings_grounding(
    cards: list[dict], *, budget_chars: int = DEFAULT_RULINGS_BUDGET_CHARS
) -> RulingsGrounding:
    if not cards:
        return RulingsGrounding()

    konami_ids = {card["id"]: _konami_id(card) for card in cards}
    seen_texts: set[str] = set()
    stored_counts: dict[str, int] = {}
    candidates: dict[str, list[tuple[dict, str]]] = {}
    for card in cards:
        other_ids = {kid for cid, kid in konami_ids.items() if cid != card["id"] and kid is not None}
        stored = get_rulings_for_card(card["id"])
        stored_counts[card["id"]] = len(stored)
        ranked = []
        for ruling in sorted(stored, key=lambda r: _rank_key(r, other_ids)):
            if ruling["ruling_text"] in seen_texts:
                continue
            seen_texts.add(ruling["ruling_text"])
            ranked.append((ruling, render_ruling_line(card, ruling)))
        candidates[card["id"]] = ranked

    share = budget_chars // len(cards)
    chosen_ids: dict[str, set[str]] = {card["id"]: set() for card in cards}
    skipped: dict[str, list[tuple[dict, str]]] = {card["id"]: [] for card in cards}
    leftover = 0
    for card in cards:
        remaining = share
        for ruling, line in candidates[card["id"]]:
            if len(line) <= remaining:
                chosen_ids[card["id"]].add(ruling["id"])
                remaining -= len(line)
            else:
                skipped[card["id"]].append((ruling, line))
        leftover += remaining
    for card in cards:
        still_skipped = []
        for ruling, line in skipped[card["id"]]:
            if len(line) <= leftover:
                chosen_ids[card["id"]].add(ruling["id"])
                leftover -= len(line)
            else:
                still_skipped.append((ruling, line))
        skipped[card["id"]] = still_skipped

    lines = [RULINGS_HEADER]
    rulings_by_card_id: dict[str, list[dict]] = {}
    for card in cards:
        chosen = [(r, line) for r, line in candidates[card["id"]] if r["id"] in chosen_ids[card["id"]]]
        rulings_by_card_id[card["id"]] = [{**r, "display_text": _display_text(r)} for r, _ in chosen]
        lines.extend(line for _, line in chosen)
        not_shown = len(skipped[card["id"]])
        if not_shown:
            plural = "s" if not_shown != 1 else ""
            lines.append(f"- {card['name']}: {not_shown} more ruling{plural} not shown (context budget).")
        if stored_counts[card["id"]] == 0:
            if card.get("rulings_status") == "failed":
                lines.append(f"- {card['name']}: rulings could not be retrieved -- do not guess what they say.")
            else:
                lines.append(f"- {card['name']}: no official rulings on record.")
    return RulingsGrounding(context="\n".join(lines), rulings_by_card_id=rulings_by_card_id)


def attach_rulings(grounded_cards: list[dict], cards: list[dict], grounding: RulingsGrounding) -> list[dict]:
    """Copies of `grounded_cards` (built from `cards`, same order) carrying the
    rulings shown for each card and its rulings_status, so run_loop's
    update_signals can register them as citable."""
    return [
        {
            **grounded,
            "rulings": grounding.rulings_by_card_id.get(card["id"], []),
            "rulings_status": card.get("rulings_status"),
        }
        for grounded, card in zip(grounded_cards, cards)
    ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/orchestration/test_rulings_context.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/orchestration/rulings_context.py tests/orchestration/test_rulings_context.py
git commit -m "feat(orchestration): rank, budget and render a question's rulings"
```

---

### Task 6: Rulings as citable sources (`confidence.py`)

**Files:**
- Modify: `src/aijudge/orchestration/confidence.py`
- Test: `tests/orchestration/test_confidence.py`

**Interfaces:**
- Consumes: grounded-card dicts carrying `"rulings"` (each with `id`, `ruling_date`, `display_text`) and `"rulings_status"` (Task 5 `attach_rulings`).
- Produces: `update_signals(state, "lookup_card", result)` registers `ruling:<id>` in `known_ids`/`citation_index` (label `"Official Q&A — <card name> (<YYYY-MM-DD or undated>)"`, text = `display_text`) and sets `retrieval_gap` only when `rulings_status == "failed"`. `normalize_cited_ids` maps a bare ruling uuid to `ruling:<uuid>`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/orchestration/test_confidence.py`:

```python
from datetime import date

_AMAZONESS_CALL_RESULT = {
    "found": True,
    "id": "card-amazoness-call",
    "ygoprodeck_id": "57312333",
    "name": "Amazoness Call",
    "card_text": 'Take 1 "Amazoness" card from your Deck, except "Amazoness Call", ...',
    "confirmed_effects": [{"effect": "..."}],
}
_RULING = {
    "id": "6f1c2a7e-0000-4000-8000-000000000001",
    "ruling_date": date(2017, 7, 22),
    "display_text": "Q: I activate the second effect of Amazoness Call, targeting an Amazoness Queen ...",
}


def test_grounded_rulings_become_known_citable_ids_with_readable_labels():
    state = SignalState()
    update_signals(state, "lookup_card", {**_AMAZONESS_CALL_RESULT, "rulings": [_RULING], "rulings_status": "fetched"})

    ruling_id = f"ruling:{_RULING['id']}"
    assert ruling_id in state.known_ids
    assert state.citation_index[ruling_id] == {
        "label": "Official Q&A — Amazoness Call (2017-07-22)",
        "text": _RULING["display_text"],
    }
    assert compute_confidence({"card:card-amazoness-call", ruling_id}, state) == pytest.approx(1.0)


def test_an_undated_ruling_is_labelled_undated():
    state = SignalState()
    undated = {**_RULING, "ruling_date": None}
    update_signals(state, "lookup_card", {**_AMAZONESS_CALL_RESULT, "rulings": [undated], "rulings_status": "fetched"})

    assert state.citation_index[f"ruling:{_RULING['id']}"]["label"] == "Official Q&A — Amazoness Call (undated)"


@pytest.mark.parametrize("status", ["fetched", "no_konami_id", None])
def test_zero_rulings_never_lowers_confidence(status):
    state = SignalState()
    update_signals(state, "lookup_card", {**_AMAZONESS_CALL_RESULT, "rulings": [], "rulings_status": status})

    assert state.retrieval_gap is False
    assert compute_confidence({"card:card-amazoness-call"}, state) == pytest.approx(1.0)


def test_a_failed_rulings_fetch_is_a_retrieval_gap():
    state = SignalState()
    update_signals(state, "lookup_card", {**_AMAZONESS_CALL_RESULT, "rulings": [], "rulings_status": "failed"})

    assert state.retrieval_gap is True
    assert compute_confidence({"card:card-amazoness-call"}, state) == pytest.approx(1.0 - RETRIEVAL_GAP_PENALTY)


def test_a_bare_ruling_uuid_is_normalized_to_its_known_ruling_id():
    state = SignalState()
    update_signals(state, "lookup_card", {**_AMAZONESS_CALL_RESULT, "rulings": [_RULING], "rulings_status": "fetched"})

    assert normalize_cited_ids({_RULING["id"]}, state) == {f"ruling:{_RULING['id']}"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/orchestration/test_confidence.py -v`
Expected: the new tests FAIL (`ruling:...` not in `known_ids`; `retrieval_gap` is `False` on `failed`).

- [ ] **Step 3: Implement**

In `update_signals`, inside `if result.get("found"):`, after the existing passcode-alias block (still inside the
`found` branch), add:

```python
            for ruling in result.get("rulings") or ():
                ruling_id = f"ruling:{ruling['id']}"
                ruling_date = ruling.get("ruling_date")
                date_text = ruling_date.isoformat() if ruling_date else "undated"
                state.known_ids.add(ruling_id)
                state.citation_index[ruling_id] = {
                    "label": f"Official Q&A — {result.get('name', '')} ({date_text})",
                    "text": ruling.get("display_text", ""),
                }
            # Zero rulings is complete data (many cards have no Q&As) and is not
            # penalized; only a fetch that actually failed at ingestion is a gap.
            if result.get("rulings_status") == "failed":
                state.retrieval_gap = True
```

Replace `normalize_cited_ids`'s loop body so a bare id tries both prefixes:

```python
    normalized = set()
    for cited_id in cited_ids:
        if cited_id in state.known_ids:
            normalized.add(cited_id)
            continue
        aliases = [f"{prefix}:{cited_id}" for prefix in ("card", "ruling")]
        normalized.add(next((alias for alias in aliases if alias in state.known_ids), cited_id))
    return normalized
```

and extend its docstring's first sentence to say "card:" **or "ruling:"** prefix.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/orchestration/test_confidence.py tests/orchestration/test_loop.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/orchestration/confidence.py tests/orchestration/test_confidence.py
git commit -m "feat(orchestration): register grounded rulings as citable sources"
```

---

### Task 7: Wire rulings into the pipeline, CLI and API

**Files:**
- Modify: `src/aijudge/orchestration/card_effect_pipeline.py`
- Modify: `src/aijudge/cli.py`
- Modify: `src/aijudge/api/app.py`
- Test: `tests/orchestration/test_card_effect_pipeline.py`, `tests/test_cli.py`, `tests/api/test_app.py`

**Interfaces:**
- Consumes: Task 5 `rulings_context.build_rulings_grounding`, `RulingsGrounding`, `attach_rulings`, `join_context`; Task 6 citation registration (exercised end-to-end through `run_loop`).
- Produces:
  - `build_pipeline_context(resolutions, *, rulings_context: str = "") -> str` (RULINGS after KNOWN FACTS, before LOOKUP FAILURES).
  - `resolve_card_effect_question(..., build_rulings_grounding_fn: Callable[[list[dict]], RulingsGrounding] | None = None)`
  - `run_cli(..., build_rulings_grounding_fn=None)` and `create_app(..., build_rulings_grounding_fn=None)`.
  - In all three, `None` means `rulings_context.build_rulings_grounding` **looked up at call time** (module attribute), so test modules can neutralize it with one autouse fixture.

- [ ] **Step 1: Write the failing tests**

Add to the top of each of `tests/orchestration/test_card_effect_pipeline.py`, `tests/test_cli.py` and
`tests/api/test_app.py` (add `import pytest` where missing) — existing tests use fake card ids with no DB, so the
default rulings lookup must not run for them:

```python
@pytest.fixture(autouse=True)
def no_rulings_grounding(monkeypatch):
    from aijudge.orchestration import rulings_context

    monkeypatch.setattr(rulings_context, "build_rulings_grounding", lambda cards, **kwargs: rulings_context.RulingsGrounding())
```

In `tests/orchestration/test_card_effect_pipeline.py`, widen the three one-argument `build_pipeline_context_fn`
lambdas (lines ~141, ~166, ~193) from `lambda resolutions: ...` to `lambda resolutions, **kwargs: ...`, then append:

```python
from datetime import date

from aijudge.orchestration.rulings_context import RulingsGrounding

_RULING = {
    "id": "6f1c2a7e-0000-4000-8000-000000000001",
    "ruling_date": date(2017, 7, 22),
    "display_text": "Q: I activate the second effect of Amazoness Call, targeting an Amazoness Queen ...",
}


def test_build_pipeline_context_places_rulings_before_lookup_failures():
    resolutions = [
        CardResolution(name="Amazoness Call", status="resolved",
                       card={"id": "abc", "name": "Amazoness Call", "card_type": "Spell Card",
                             "card_text": "Take 1 \"Amazoness\" card ...", "race": "Quick-Play", "ygoprodeck_id": None}),
        CardResolution(name="Amazoness Qeen", status="not_found"),
    ]

    context = build_pipeline_context(resolutions, rulings_context="RULINGS (official Q&A ...")

    assert context.index("KNOWN FACTS") < context.index("RULINGS") < context.index("LOOKUP FAILURES")


def test_resolve_card_effect_question_grounds_resolved_cards_with_their_rulings():
    card = {"id": "abc", "name": "Amazoness Call", "rulings_status": "fetched"}
    seen_cards = []

    def fake_grounding(cards):
        seen_cards.extend(cards)
        return RulingsGrounding(context="RULINGS block", rulings_by_card_id={"abc": [_RULING]})

    resolution = resolve_card_effect_question(
        "Can Amazoness Call target Amazoness Queen?",
        llm_client=MockLLMClient(),
        extract_card_names_fn=lambda question, **kw: ["Amazoness Call", "Amazoness Qeen"],
        resolve_named_cards_fn=lambda names, **kw: [
            CardResolution(name="Amazoness Call", status="resolved", card=card),
            CardResolution(name="Amazoness Qeen", status="not_found"),
        ],
        build_pipeline_context_fn=lambda resolutions, rulings_context="": f"FACTS|{rulings_context}|FAILURES",
        build_grounded_result_fn=lambda c: {"found": True, "id": c["id"], "name": c["name"], "confirmed_effects": []},
        build_rulings_grounding_fn=fake_grounding,
    )

    assert seen_cards == [card]
    assert resolution.context == "FACTS|RULINGS block|FAILURES"
    assert resolution.grounded_cards[0]["rulings"] == [_RULING]
    assert resolution.grounded_cards[0]["rulings_status"] == "fetched"
```

Append to `tests/test_cli.py`:

```python
def test_run_cli_grounds_a_matched_card_with_its_rulings_and_accepts_a_ruling_citation():
    from datetime import date

    from aijudge.orchestration.rulings_context import RulingsGrounding

    printed = []
    inputs = iter(["Does Amazoness Call still apply if my Amazoness Queen changes control?", "quit"])
    ruling = {
        "id": "6f1c2a7e-0000-4000-8000-000000000001",
        "ruling_date": date(2017, 7, 22),
        "display_text": "Q: I activate the second effect of Amazoness Call, targeting an Amazoness Queen ...",
    }
    llm = _CapturingLLMClient([
        "PROCEED",
        f"FINAL: The effect is still applied normally. ||CITES: card:1, ruling:{ruling['id']}||",
    ])
    card = {"id": "1", "name": "Amazoness Call", "card_type": "Spell Card", "rulings_status": "fetched"}

    run_cli(
        llm,
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: [card],
        build_known_facts_context_fn=lambda c: "KNOWN FACTS block",
        # Empty confirmed_effects: no structured-effect verification LLM call
        # (only two responses are queued); score 1.0 - 0.2 = 0.8 clears 0.75.
        build_grounded_result_fn=lambda c: {"found": True, "id": c["id"], "name": c["name"], "confirmed_effects": []},
        build_rulings_grounding_fn=lambda cards: RulingsGrounding(
            context=f"RULINGS block ruling:{ruling['id']}", rulings_by_card_id={"1": [ruling]}
        ),
    )

    answering_prompt = llm.prompts[1]
    assert answering_prompt.index("KNOWN FACTS block") < answering_prompt.index("RULINGS block")
    assert "The effect is still applied normally." in printed
```

Append to `tests/api/test_app.py`:

```python
def _amazoness_call_grounding():
    from datetime import date

    from aijudge.orchestration.rulings_context import RulingsGrounding

    ruling = {
        "id": "6f1c2a7e-0000-4000-8000-000000000001",
        "ruling_date": date(2017, 7, 22),
        "display_text": "Q: I activate the second effect of Amazoness Call, targeting an Amazoness Queen ...",
    }
    return ruling, RulingsGrounding(context=f"RULINGS block ruling:{ruling['id']}", rulings_by_card_id={"1": [ruling]})


_AMAZONESS_CALL = {"id": "1", "name": "Amazoness Call", "card_type": "Spell Card", "rulings_status": "fetched"}


def _grounded(card):
    # Empty confirmed_effects: no structured-effect verification LLM call, and
    # the score (1.0 - 0.2 = 0.8) still clears the 0.75 threshold.
    return {"found": True, "id": card["id"], "name": card["name"], "confirmed_effects": []}


def test_post_questions_cites_a_grounded_ruling_with_a_readable_label():
    ruling, grounding = _amazoness_call_grounding()
    llm = _CapturingLLMClient([
        "PROCEED",
        f"FINAL: The effect is still applied normally. ||CITES: card:1, ruling:{ruling['id']}||",
    ])

    response = _client(
        llm,
        find_matched_cards_fn=lambda question: [_AMAZONESS_CALL],
        build_known_facts_context_fn=lambda c: "KNOWN FACTS block",
        build_grounded_result_fn=_grounded,
        build_rulings_grounding_fn=lambda cards: grounding,
    ).post("/questions", json={"question": "Does Amazoness Call still apply if my Amazoness Queen changes control?"})

    body = response.json()
    assert body["status"] == "answer"
    assert {"label": "Official Q&A — Amazoness Call (2017-07-22)", "text": ruling["display_text"]} in body["citations"]
    assert "RULINGS block" in llm.prompts[1]


def test_post_questions_answer_grounds_the_disambiguated_card_with_its_rulings():
    ruling, grounding = _amazoness_call_grounding()
    other = {"id": "2", "name": "Amazoness Queen", "card_type": "Effect Monster", "rulings_status": "fetched"}
    llm = _CapturingLLMClient([f"FINAL: Applied normally. ||CITES: ruling:{ruling['id']}||"])

    response = _client(
        llm,
        find_matched_cards_fn=lambda question: [_AMAZONESS_CALL, other],
        build_known_facts_context_fn=lambda c: "KNOWN FACTS block",
        build_grounded_result_fn=_grounded,
        build_rulings_grounding_fn=lambda cards: grounding,
    ).post(
        "/questions/answer",
        json={
            "question": "Does Amazoness Call still apply?",
            "items": [{"kind": "disambiguate_card", "text": "Which card?"}],
            "answers": ["Amazoness Call"],
        },
    )

    assert response.json()["status"] == "answer"
    assert "RULINGS block" in llm.prompts[0]
```

(If `_CapturingLLMClient` in `tests/api/test_app.py` doesn't record a `system` argument, that's fine — these tests
only read `prompts`.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/orchestration/test_card_effect_pipeline.py tests/test_cli.py tests/api/test_app.py -v`
Expected: the new tests FAIL (`unexpected keyword argument 'build_rulings_grounding_fn'` / `'rulings_context'`);
the pre-existing ones still PASS.

- [ ] **Step 3: Implement**

`card_effect_pipeline.py`:

```python
from aijudge.orchestration import rulings_context
from aijudge.orchestration.rulings_context import RulingsGrounding, attach_rulings
```

```python
def build_pipeline_context(resolutions: list[CardResolution], *, rulings_context: str = "") -> str:
    ...  # existing known_facts_blocks loop unchanged
    failures = [r for r in resolutions if r.status != "resolved"]
    parts = list(known_facts_blocks)
    if rulings_context:
        parts.append(rulings_context)
    if failures:
        ...  # existing failure block unchanged
    return "\n\n".join(parts)
```

(The `rulings_context` parameter name shadows the imported module inside this one function only; that's fine
because the function doesn't use the module.)

In `resolve_card_effect_question`, add the parameter
`build_rulings_grounding_fn: Callable[[list[dict]], RulingsGrounding] | None = None` and replace the final `return`:

```python
    build_rulings_grounding_fn = build_rulings_grounding_fn or rulings_context.build_rulings_grounding
    resolved_cards = [r.card for r in resolutions if r.status == "resolved"]
    grounding = build_rulings_grounding_fn(resolved_cards)
    return PipelineResolution(
        supported=True,
        context=build_pipeline_context_fn(resolutions, rulings_context=grounding.context),
        grounded_cards=attach_rulings(
            [build_grounded_result_fn(card) for card in resolved_cards], resolved_cards, grounding
        ),
    )
```

`cli.py`: add imports `from .orchestration import rulings_context` and
`from .orchestration.rulings_context import RulingsGrounding, attach_rulings, join_context`; add the parameter
`build_rulings_grounding_fn: Callable[[list[dict]], RulingsGrounding] | None = None`. In the loop body:

- initialize `local_card: dict | None = None` next to `grounded_cards: list[dict] = []`;
- in `if len(matches) == 1:` add `local_card = matches[0]`;
- in `if chosen is not None:` add `local_card = chosen`;
- inside `if not matches or not grounded_cards:` (pipeline fallback) add `local_card = None` as its first line;
- immediately before `context = format_clarification_context(items, answers)` add:

```python
        if local_card is not None:
            # The pipeline fallback grounds its own cards' rulings; this covers
            # a card matched locally by preflight.
            grounding = (build_rulings_grounding_fn or rulings_context.build_rulings_grounding)([local_card])
            preflight_context = join_context(preflight_context, grounding.context)
            grounded_cards = attach_rulings(grounded_cards, [local_card], grounding)
```

`api/app.py`: add the same two imports (`from aijudge.orchestration import rulings_context` and
`from aijudge.orchestration.rulings_context import RulingsGrounding, attach_rulings, join_context`) and the
`create_app` parameter `build_rulings_grounding_fn: Callable[[list[dict]], RulingsGrounding] | None = None`.
Inside `create_app`, after the other defaults, add:

```python
    def _ground_rulings(context: str, grounded_cards: list[dict], card: dict) -> tuple[str, list[dict]]:
        grounding = (build_rulings_grounding_fn or rulings_context.build_rulings_grounding)([card])
        return join_context(context, grounding.context), attach_rulings(grounded_cards, [card], grounding)
```

In `post_question`, right after the `if not matches:` pipeline block and before `run_loop`:

```python
        if len(matches) == 1:
            preflight_context, grounded_cards = _ground_rulings(preflight_context, grounded_cards, matches[0])
```

In `post_answer`, right after the `if not matches or not grounded_cards:` pipeline block (a fallback only runs when
`card` is `None`) and before `context = format_clarification_context(...)`:

```python
        if card is not None:
            preflight_context, grounded_cards = _ground_rulings(preflight_context, grounded_cards, card)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/orchestration tests/test_cli.py tests/api -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/orchestration/card_effect_pipeline.py src/aijudge/cli.py src/aijudge/api/app.py tests/orchestration/test_card_effect_pipeline.py tests/test_cli.py tests/api/test_app.py
git commit -m "feat: ground answers with each card's stored rulings"
```

---

### Task 8: Answering prompt and Ollama context window

**Files:**
- Modify: `src/aijudge/orchestration/protocol.py` (`build_answering_system_prompt`)
- Modify: `src/aijudge/llm/client.py` (`OllamaLLMClient`)
- Test: `tests/orchestration/test_protocol.py`, `tests/llm/test_client.py`

**Interfaces:**
- Produces: the answering prompt names the RULINGS block and `ruling:<id>` citations; `OllamaLLMClient(..., num_ctx: int | None = None)`, `self.num_ctx`, `DEFAULT_OLLAMA_NUM_CTX = 8192`, `"options": {"num_ctx": ...}` in both request payloads.

- [ ] **Step 1: Write the failing tests**

Append to `tests/orchestration/test_protocol.py`:

```python
def test_answering_prompt_explains_rulings_and_their_citation_ids():
    prompt = build_answering_system_prompt()
    assert "RULINGS" in prompt
    assert "ruling:<id>" in prompt
    assert "situation" in prompt.lower()
```

Append to `tests/llm/test_client.py` (it already defines `FakeResponse`):

```python
def test_ollama_client_sends_the_default_context_window_on_generate(monkeypatch):
    monkeypatch.delenv("OLLAMA_NUM_CTX", raising=False)
    captured = {}

    def fake_post(url, json, timeout):
        captured["json"] = json
        return FakeResponse({"response": "0.95"})

    OllamaLLMClient(http_post=fake_post).complete("prompt")

    assert captured["json"]["options"] == {"num_ctx": 8192}


def test_ollama_client_reads_the_context_window_from_the_environment_on_chat(monkeypatch):
    monkeypatch.setenv("OLLAMA_NUM_CTX", "16384")
    captured = {}

    def fake_post(url, json, timeout):
        captured["json"] = json
        return FakeResponse({"message": {"content": "FINAL: ok ||CITES: ||"}})

    OllamaLLMClient(http_post=fake_post).complete("prompt", system="system text")

    assert captured["json"]["options"] == {"num_ctx": 16384}


def test_ollama_client_explicit_context_window_wins_over_the_environment(monkeypatch):
    monkeypatch.setenv("OLLAMA_NUM_CTX", "16384")
    assert OllamaLLMClient(num_ctx=4096, http_post=lambda **kw: None).num_ctx == 4096
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/orchestration/test_protocol.py tests/llm/test_client.py -v`
Expected: the new tests FAIL (`KeyError: 'options'`, `"RULINGS" not in prompt`).

- [ ] **Step 3: Implement**

`protocol.py`, in `build_answering_system_prompt`: replace
`"listing every source id (card:<id>) your answer relies on -- "` with
`"listing every source id (card:<id> or ruling:<id>) your answer relies on -- "`, and insert this sentence just
before `"Respond with a "`:

```python
        "The RULINGS block, when present, holds official Konami Q&A "
        "rulings for the cards above: when a ruling's situation matches "
        "the question, prefer it over your own reasoning and cite it as "
        "ruling:<id>; do not apply a ruling whose situation differs from "
        "the question's. "
```

`llm/client.py`: add `DEFAULT_OLLAMA_NUM_CTX = 8192` next to the other Ollama defaults; add the constructor
parameter `num_ctx: int | None = None` (after `timeout`) and:

```python
        # Explicit context window: without it Ollama uses its small default and
        # silently drops the start of an overlong prompt (KNOWN FACTS + RULINGS).
        self.num_ctx = (
            num_ctx if num_ctx is not None else int(os.environ.get("OLLAMA_NUM_CTX") or DEFAULT_OLLAMA_NUM_CTX)
        )
```

Add `"options": {"num_ctx": self.num_ctx},` to both the `/api/chat` and `/api/generate` `json` payloads.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/orchestration/test_protocol.py tests/llm/test_client.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/orchestration/protocol.py src/aijudge/llm/client.py tests/orchestration/test_protocol.py tests/llm/test_client.py
git commit -m "feat: explain rulings in the answering prompt and set Ollama num_ctx"
```

---

### Task 9: Documentation, full suite, and backfill

**Files:**
- Modify: `CLAUDE.md`
- Modify: `.env.example` (add `OLLAMA_NUM_CTX`)

- [ ] **Step 1: Update `CLAUDE.md`**

- `db/` bullet: document `card.rulings_status` (values and `NULL` meaning), `card.ygoresources_id` now holding the
  Konami id, and `rulings.ruling_text_resolved` / `referenced_konami_ids` (raw `ruling_text` never modified), plus
  the new repo functions.
- `ingestion/` bullet: `seed_card` records the fetch outcome and resolves names via the ygoresources name index;
  new `rulings_backfill.py` with its run command.
- `orchestration/` bullets: new `rulings_context.py` (ranking, 6,000-char budget, no truncation, the three
  status lines); `confidence.update_signals` registers grounded rulings and only `failed` is a gap;
  `normalize_cited_ids` handles bare ruling ids; `card_effect_pipeline`/`cli`/`api` call it once per question;
  the answering prompt's RULINGS instruction.
- `llm/` bullet: `OLLAMA_NUM_CTX` (default 8192).
- Fix the stated confidence threshold: `DEFAULT_CONFIDENCE_THRESHOLD` is **0.75** in `confidence.py`, not 0.9.
- Add `OLLAMA_NUM_CTX=8192` to `.env.example` with a one-line comment.

- [ ] **Step 2: Run the full suite**

Run: `pytest`
Expected: all tests PASS. Confirm the DB suites actually ran (not skipped): `pytest tests/db tests/ingestion -v | grep -c SKIPPED` should print `0`.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md .env.example
git commit -m "docs: document rulings grounding"
```

- [ ] **Step 4: Backfill the app database (operator step, after merge)**

```bash
python -c "from aijudge.db.migrate import run_migrations; run_migrations()"
python -c "from aijudge.ingestion.rulings_backfill import backfill_rulings; print(backfill_rulings())"
```

Expected on today's data: `konami_ids_stored=10`, `rulings_refetched=0` (every seeded card already has ≥1 ruling),
`rulings_resolved=65`, `failures=[]`. Then spot-check:
`docker exec aijudge-db-1 psql -U aijudge -d aijudge -c "select count(*) filter (where ruling_text_resolved like '%<<%') from rulings"` → `0`.
