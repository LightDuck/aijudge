# AIJudge Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the independently-testable foundation of AIJudge — the deterministic rules engine, the Postgres+pgvector data layer, the code-based PSCT effect parser with an LLM confidence-review agent, and the seed ingestion script for a hand-picked card set — with no LLM orchestration or CLI wiring yet (that's the follow-up plan).

**Architecture:** A `src/aijudge/` package with clearly separated modules: `rules_engine/` (pure Python, no DB/LLM dependency), `db/` (psycopg3 + pgvector repos over a hand-written schema), `embeddings/` and `llm/` (small `Protocol` interfaces with mock implementations, so no API key is required yet), `effect_parser/` (grammar-based PSCT parser plus an LLM-scored review step), and `ingestion/` (external API clients and the seed script that ties everything together for a small hand-picked card list).

**Tech Stack:** Python 3.11+, psycopg3, pgvector, Postgres 16 (pgvector/pgvector:pg16 via Docker Compose), pytest, requests, python-dotenv.

**Spec:** `docs/superpowers/specs/2026-08-18-thin-slice-design.md`

## Global Constraints

- Implementation follows TDD: a failing test before implementation code, for every task in this plan (per spec's "Development process" section).
- No ORM — raw SQL via psycopg3, matching the project's "custom code over generic frameworks" direction.
- LLM and embedding calls go through mockable interfaces (`LLMClient`, `EmbeddingClient`) — no real API key required for this plan; a real provider is wired in later.
- Card/errata text is never overwritten — errata gets a new `card_errata_versions` row (per spec's data schema).
- `card_effects_structured` rows start `pending` and only move to `confirmed` via the review agent's confidence score or manual confirmation — the rules engine must never be given a `pending` effect to treat as ground truth (that wiring happens in the Orchestration plan, but the repo-level distinction is established here).
- Tests that need a live Postgres instance are marked to skip when `DATABASE_URL` isn't set, so the pure-Python parts of the suite always run without Docker.

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `tests/__init__.py`
- Test: `tests/test_scaffolding.py`

**Interfaces:**
- Consumes: nothing
- Produces: an installable `aijudge` package under `src/aijudge/`, a `docker compose` Postgres+pgvector service, and pytest configured with `pythonpath = ["src"]`.

- [ ] **Step 1: Create the non-code project files**

`pyproject.toml`:
```toml
[project]
name = "aijudge"
version = "0.1.0"
description = "Yu-Gi-Oh! TCG rules-adjudication assistant (thin slice)"
requires-python = ">=3.11"
dependencies = [
    "psycopg[binary]>=3.1",
    "pgvector>=0.2",
    "requests>=2.31",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

`docker-compose.yml`:
```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: aijudge
      POSTGRES_PASSWORD: aijudge
      POSTGRES_DB: aijudge
    ports:
      - "5432:5432"
    volumes:
      - aijudge_pgdata:/var/lib/postgresql/data

volumes:
  aijudge_pgdata:
```

`.env.example`:
```
DATABASE_URL=postgresql://aijudge:aijudge@localhost:5432/aijudge
```

`.gitignore`:
```
.env
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/
```

`tests/__init__.py`: empty file.

- [ ] **Step 2: Write a failing smoke test**

`tests/test_scaffolding.py`:
```python
import aijudge


def test_package_importable():
    assert aijudge.__name__ == "aijudge"
```

- [ ] **Step 3: Run the test and confirm it fails**

Run: `pip install -e ".[dev]" && pytest tests/test_scaffolding.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aijudge'`

- [ ] **Step 4: Create the package**

`src/aijudge/__init__.py`:
```python
"""AIJudge: Yu-Gi-Oh! TCG rules-adjudication assistant."""
```

- [ ] **Step 5: Run the test and confirm it passes**

Run: `pytest tests/test_scaffolding.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml docker-compose.yml .env.example .gitignore tests/__init__.py tests/test_scaffolding.py src/aijudge/__init__.py
git commit -m "chore: project scaffolding"
```

---

### Task 2: Rules engine models (effect type, spell speed)

**Files:**
- Create: `src/aijudge/rules_engine/__init__.py`
- Create: `src/aijudge/rules_engine/models.py`
- Test: `tests/rules_engine/test_models.py`
- Create: `tests/rules_engine/__init__.py`

**Interfaces:**
- Consumes: nothing
- Produces: `EffectType` (enum), `SpellSpeed` (enum), `spell_speed_for(effect_type: EffectType) -> SpellSpeed`, `Effect` (dataclass: `card_id: str`, `card_name: str`, `effect_type: EffectType`, `controller: str`), `ChainLink` (dataclass: `link_number: int`, `effect: Effect`) — used by every other `rules_engine` module in this plan.

- [ ] **Step 1: Write the failing tests**

`tests/rules_engine/__init__.py`: empty file.

`tests/rules_engine/test_models.py`:
```python
from aijudge.rules_engine.models import Effect, EffectType, SpellSpeed, spell_speed_for


def test_quick_and_quick_like_effects_are_spell_speed_2():
    assert spell_speed_for(EffectType.QUICK) == SpellSpeed.QUICK
    assert spell_speed_for(EffectType.QUICK_LIKE) == SpellSpeed.QUICK


def test_other_effect_types_default_to_spell_speed_1():
    assert spell_speed_for(EffectType.IGNITION) == SpellSpeed.NORMAL
    assert spell_speed_for(EffectType.TRIGGER) == SpellSpeed.NORMAL
    assert spell_speed_for(EffectType.CONTINUOUS) == SpellSpeed.NORMAL
    assert spell_speed_for(EffectType.UNCLASSIFIED) == SpellSpeed.NORMAL


def test_effect_is_constructible():
    effect = Effect(
        card_id="1",
        card_name="Called by the Grave",
        effect_type=EffectType.QUICK_LIKE,
        controller="player_a",
    )
    assert effect.controller == "player_a"
```

- [ ] **Step 2: Run tests, confirm failure**

Run: `pytest tests/rules_engine/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aijudge.rules_engine'`

- [ ] **Step 3: Implement**

`src/aijudge/rules_engine/__init__.py`: empty file.

`src/aijudge/rules_engine/models.py`:
```python
from dataclasses import dataclass
from enum import Enum


class EffectType(str, Enum):
    TRIGGER = "trigger"
    IGNITION = "ignition"
    QUICK = "quick"
    CONTINUOUS = "continuous"
    UNCLASSIFIED = "unclassified"
    CONDITION = "condition"
    EFFECT = "effect"
    TRIGGER_LIKE = "trigger-like"
    QUICK_LIKE = "quick-like"


class SpellSpeed(int, Enum):
    NORMAL = 1
    QUICK = 2


_QUICK_EFFECT_TYPES = {EffectType.QUICK, EffectType.QUICK_LIKE}


def spell_speed_for(effect_type: EffectType) -> SpellSpeed:
    return SpellSpeed.QUICK if effect_type in _QUICK_EFFECT_TYPES else SpellSpeed.NORMAL


@dataclass
class Effect:
    card_id: str
    card_name: str
    effect_type: EffectType
    controller: str


@dataclass
class ChainLink:
    link_number: int
    effect: Effect
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `pytest tests/rules_engine/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/rules_engine/__init__.py src/aijudge/rules_engine/models.py tests/rules_engine/__init__.py tests/rules_engine/test_models.py
git commit -m "feat(rules_engine): effect type and spell speed models"
```

---

### Task 3: Chain — LIFO resolution order

**Files:**
- Create: `src/aijudge/rules_engine/chain.py`
- Test: `tests/rules_engine/test_chain.py`

**Interfaces:**
- Consumes: `Effect`, `ChainLink` from Task 2 (`aijudge.rules_engine.models`)
- Produces: `Chain` class with `add_link(effect: Effect) -> ChainLink`, `links: list[ChainLink]` (property), `pending_links: list[ChainLink]` (property), `resolution_order() -> list[ChainLink]`, `resolve_next() -> ChainLink` — consumed by `segoc.py` (Task 4) and `priority.py` (Task 5), and by the Orchestration plan's `resolve_chain` tool.

- [ ] **Step 1: Write the failing tests**

`tests/rules_engine/test_chain.py`:
```python
import pytest

from aijudge.rules_engine.chain import Chain
from aijudge.rules_engine.models import Effect, EffectType


def _effect(name: str, controller: str = "player_a") -> Effect:
    return Effect(card_id=name, card_name=name, effect_type=EffectType.IGNITION, controller=controller)


def test_add_link_assigns_increasing_link_numbers():
    chain = Chain()
    link1 = chain.add_link(_effect("Card A"))
    link2 = chain.add_link(_effect("Card B"))
    assert link1.link_number == 1
    assert link2.link_number == 2


def test_resolution_order_is_lifo():
    chain = Chain()
    chain.add_link(_effect("Card A"))
    chain.add_link(_effect("Card B"))
    chain.add_link(_effect("Card C"))
    order = chain.resolution_order()
    assert [link.effect.card_name for link in order] == ["Card C", "Card B", "Card A"]


def test_resolve_next_pops_highest_link_first():
    chain = Chain()
    chain.add_link(_effect("Card A"))
    chain.add_link(_effect("Card B"))
    first = chain.resolve_next()
    second = chain.resolve_next()
    assert first.effect.card_name == "Card B"
    assert second.effect.card_name == "Card A"
    assert chain.pending_links == []


def test_resolve_next_raises_when_chain_is_empty():
    chain = Chain()
    with pytest.raises(ValueError):
        chain.resolve_next()
```

- [ ] **Step 2: Run tests, confirm failure**

Run: `pytest tests/rules_engine/test_chain.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aijudge.rules_engine.chain'`

- [ ] **Step 3: Implement**

`src/aijudge/rules_engine/chain.py`:
```python
from .models import ChainLink, Effect


class Chain:
    def __init__(self) -> None:
        self._links: list[ChainLink] = []
        self._resolved: list[ChainLink] = []

    def add_link(self, effect: Effect) -> ChainLink:
        link = ChainLink(link_number=len(self._links) + 1, effect=effect)
        self._links.append(link)
        return link

    @property
    def links(self) -> list[ChainLink]:
        return list(self._links)

    @property
    def pending_links(self) -> list[ChainLink]:
        return [link for link in self._links if link not in self._resolved]

    def resolution_order(self) -> list[ChainLink]:
        """Chain links resolve LIFO: the most recently added link resolves first."""
        return sorted(self.pending_links, key=lambda link: link.link_number, reverse=True)

    def resolve_next(self) -> ChainLink:
        order = self.resolution_order()
        if not order:
            raise ValueError("no pending chain links to resolve")
        next_link = order[0]
        self._resolved.append(next_link)
        return next_link
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `pytest tests/rules_engine/test_chain.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/rules_engine/chain.py tests/rules_engine/test_chain.py
git commit -m "feat(rules_engine): LIFO chain resolution order"
```

---

### Task 4: SEGOC ordering

**Files:**
- Create: `src/aijudge/rules_engine/segoc.py`
- Test: `tests/rules_engine/test_segoc.py`

**Interfaces:**
- Consumes: `Chain` (Task 3), `Effect` (Task 2)
- Produces: `apply_segoc(chain: Chain, turn_player: str, triggered_effects: list[Effect]) -> Chain` — consumed by the Orchestration plan's `resolve_chain` tool whenever multiple effects trigger simultaneously.

This is the module flagged in the spec as the most common source of wrong answers: **the turn player chains their simultaneous effects first, which — because resolution is LIFO — means the turn player's effects resolve LAST**, not first.

- [ ] **Step 1: Write the failing tests**

`tests/rules_engine/test_segoc.py`:
```python
from aijudge.rules_engine.chain import Chain
from aijudge.rules_engine.models import Effect, EffectType
from aijudge.rules_engine.segoc import apply_segoc


def _triggered(name: str, controller: str) -> Effect:
    return Effect(card_id=name, card_name=name, effect_type=EffectType.TRIGGER, controller=controller)


def test_turn_player_effects_are_chained_first_and_so_resolve_last():
    chain = Chain()
    turn_player_effect = _triggered("Turn Player's Card", "player_a")
    opponent_effect = _triggered("Opponent's Card", "player_b")

    apply_segoc(chain, turn_player="player_a", triggered_effects=[turn_player_effect, opponent_effect])

    assert [link.effect.card_name for link in chain.links] == ["Turn Player's Card", "Opponent's Card"]

    order = chain.resolution_order()
    assert order[0].effect.card_name == "Opponent's Card"
    assert order[1].effect.card_name == "Turn Player's Card"


def test_within_one_players_effects_the_given_order_is_preserved():
    chain = Chain()
    first = _triggered("Turn Player's First Choice", "player_a")
    second = _triggered("Turn Player's Second Choice", "player_a")

    apply_segoc(chain, turn_player="player_a", triggered_effects=[first, second])

    assert [link.effect.card_name for link in chain.links] == [
        "Turn Player's First Choice",
        "Turn Player's Second Choice",
    ]
```

- [ ] **Step 2: Run tests, confirm failure**

Run: `pytest tests/rules_engine/test_segoc.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aijudge.rules_engine.segoc'`

- [ ] **Step 3: Implement**

`src/aijudge/rules_engine/segoc.py`:
```python
from .chain import Chain
from .models import Effect


def apply_segoc(chain: Chain, *, turn_player: str, triggered_effects: list[Effect]) -> Chain:
    """Add simultaneously-triggered effects to the chain per SEGOC.

    The turn player's effects are chained first (in the order given —
    ordering *within* one player's simultaneous effects is that
    player's choice, not a rule this function decides). Because chain
    resolution is LIFO, chaining first means resolving LAST. The
    non-turn player's effects are chained second and so resolve first.
    """
    turn_player_effects = [e for e in triggered_effects if e.controller == turn_player]
    non_turn_player_effects = [e for e in triggered_effects if e.controller != turn_player]

    for effect in turn_player_effects:
        chain.add_link(effect)
    for effect in non_turn_player_effects:
        chain.add_link(effect)

    return chain
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `pytest tests/rules_engine/test_segoc.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/rules_engine/segoc.py tests/rules_engine/test_segoc.py
git commit -m "feat(rules_engine): SEGOC ordering for simultaneous triggers"
```

---

### Task 5: Priority / spell-speed activation window

**Files:**
- Create: `src/aijudge/rules_engine/priority.py`
- Test: `tests/rules_engine/test_priority.py`

**Interfaces:**
- Consumes: `Chain` (Task 3), `SpellSpeed` (Task 2)
- Produces: `can_activate_now(spell_speed: SpellSpeed, chain: Chain) -> bool` — consumed by the Orchestration plan when checking whether a proposed activation is legal given the current chain state.

- [ ] **Step 1: Write the failing tests**

`tests/rules_engine/test_priority.py`:
```python
from aijudge.rules_engine.chain import Chain
from aijudge.rules_engine.models import Effect, EffectType, SpellSpeed
from aijudge.rules_engine.priority import can_activate_now


def test_any_spell_speed_can_activate_when_chain_is_empty():
    chain = Chain()
    assert can_activate_now(SpellSpeed.NORMAL, chain) is True
    assert can_activate_now(SpellSpeed.QUICK, chain) is True


def test_normal_speed_effect_cannot_respond_to_a_chain_in_progress():
    chain = Chain()
    chain.add_link(Effect(card_id="1", card_name="Card A", effect_type=EffectType.IGNITION, controller="player_a"))
    assert can_activate_now(SpellSpeed.NORMAL, chain) is False


def test_quick_speed_effect_can_respond_to_a_chain_in_progress():
    chain = Chain()
    chain.add_link(Effect(card_id="1", card_name="Card A", effect_type=EffectType.IGNITION, controller="player_a"))
    assert can_activate_now(SpellSpeed.QUICK, chain) is True
```

- [ ] **Step 2: Run tests, confirm failure**

Run: `pytest tests/rules_engine/test_priority.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aijudge.rules_engine.priority'`

- [ ] **Step 3: Implement**

`src/aijudge/rules_engine/priority.py`:
```python
from .chain import Chain
from .models import SpellSpeed


def can_activate_now(spell_speed: SpellSpeed, chain: Chain) -> bool:
    """Whether an effect of the given spell speed may be added to the
    chain right now.

    A Spell Speed 1 effect may only be activated when the chain is
    empty — it cannot respond to anything already on the chain. A
    Spell Speed 2 effect may always respond, chain empty or not.
    """
    if not chain.pending_links:
        return True
    return spell_speed == SpellSpeed.QUICK
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `pytest tests/rules_engine/test_priority.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/rules_engine/priority.py tests/rules_engine/test_priority.py
git commit -m "feat(rules_engine): spell-speed activation window check"
```

---

### Task 6: Missing-timing check (quick effects)

**Files:**
- Create: `src/aijudge/rules_engine/timing.py`
- Test: `tests/rules_engine/test_timing.py`

**Interfaces:**
- Consumes: nothing beyond stdlib
- Produces: `check_missing_timing(trigger_step: int, current_step: int) -> bool` — consumed by the Orchestration plan when a Quick Effect's activation is being validated against the sequence of events that occurred since it would have triggered. Per spec's non-goals, this covers Quick Effects only; optional-trigger missing timing is deferred.

- [ ] **Step 1: Write the failing tests**

`tests/rules_engine/test_timing.py`:
```python
import pytest

from aijudge.rules_engine.timing import check_missing_timing


def test_activating_at_the_very_next_opportunity_does_not_miss_timing():
    assert check_missing_timing(trigger_step=3, current_step=3) is False


def test_any_intervening_step_means_timing_is_missed():
    assert check_missing_timing(trigger_step=3, current_step=4) is True


def test_current_step_cannot_precede_trigger_step():
    with pytest.raises(ValueError):
        check_missing_timing(trigger_step=3, current_step=2)
```

- [ ] **Step 2: Run tests, confirm failure**

Run: `pytest tests/rules_engine/test_timing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aijudge.rules_engine.timing'`

- [ ] **Step 3: Implement**

`src/aijudge/rules_engine/timing.py`:
```python
def check_missing_timing(trigger_step: int, current_step: int) -> bool:
    """Whether a Quick Effect has missed timing.

    A Quick Effect must be activated at the very next opportunity
    after the event that would trigger it (`trigger_step`). If any
    other step — another chain link resolving, a phase change — has
    passed since then (`current_step` > `trigger_step`), timing is
    missed and the effect can no longer be activated for this trigger.
    """
    if current_step < trigger_step:
        raise ValueError("current_step cannot precede trigger_step")
    return current_step > trigger_step
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `pytest tests/rules_engine/test_timing.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/rules_engine/timing.py tests/rules_engine/test_timing.py
git commit -m "feat(rules_engine): missing-timing check for quick effects"
```

---

### Task 7: Database schema, migration runner, connection module

**Files:**
- Create: `src/aijudge/db/__init__.py`
- Create: `src/aijudge/db/connection.py`
- Create: `src/aijudge/db/schema.sql`
- Create: `src/aijudge/db/migrate.py`
- Test: `tests/db/__init__.py`
- Test: `tests/db/test_migrate.py`

**Interfaces:**
- Consumes: `DATABASE_URL` environment variable (loaded from `.env` via `python-dotenv`)
- Produces: `get_connection() -> psycopg.Connection` and `run_migrations() -> None` — consumed by every repo module in this plan (Tasks 8–10, 12) and by the seed script (Task 19).

**Prerequisite:** `docker compose up -d db` running, and `.env` created from `.env.example` (copy it — `.env` is gitignored). Tests in this task and all later DB-touching tasks are skipped automatically when `DATABASE_URL` is not set.

- [ ] **Step 1: Write the failing test**

`tests/db/__init__.py`: empty file.

`tests/db/test_migrate.py`:
```python
import os

import pytest

pytestmark = pytest.mark.skipif("DATABASE_URL" not in os.environ, reason="requires a running Postgres instance")


def test_run_migrations_creates_all_tables():
    from aijudge.db.connection import get_connection
    from aijudge.db.migrate import run_migrations

    run_migrations()
    with get_connection() as conn:
        for table in ("cards", "card_errata_versions", "rulings", "card_effects_structured", "rulebook_chunks", "qa_test_cases"):
            row = conn.execute("SELECT to_regclass(%s)", (f"public.{table}",)).fetchone()
            assert row[0] == table, f"expected table {table!r} to exist"
```

- [ ] **Step 2: Run test, confirm failure**

Run: `pytest tests/db/test_migrate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aijudge.db'`

- [ ] **Step 3: Implement**

`src/aijudge/db/__init__.py`: empty file.

`src/aijudge/db/connection.py`:
```python
import os

import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector

load_dotenv()


def get_connection() -> psycopg.Connection:
    database_url = os.environ["DATABASE_URL"]
    conn = psycopg.connect(database_url)
    try:
        register_vector(conn)
    except psycopg.errors.UndefinedObject:
        # The `vector` extension may not exist yet on a brand-new
        # database (migrate.py creates it) — fall back to an
        # unregistered connection rather than failing to connect.
        conn.rollback()
    return conn
```

`src/aijudge/db/schema.sql`:
```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS cards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    card_text TEXT NOT NULL,
    card_type TEXT NOT NULL,
    attribute TEXT,
    monster_type TEXT,
    level INTEGER,
    rank INTEGER,
    link_rating INTEGER,
    archetype TEXT,
    atk INTEGER,
    def INTEGER,
    ygoprodeck_id TEXT,
    ygoresources_id TEXT,
    source TEXT NOT NULL,
    fetched_at DATE NOT NULL,
    has_errata BOOLEAN NOT NULL DEFAULT FALSE,
    card_materials TEXT
);

CREATE TABLE IF NOT EXISTS card_errata_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    card_id UUID NOT NULL REFERENCES cards (id),
    errata_date DATE NOT NULL,
    errata_text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rulings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    card_id UUID NOT NULL REFERENCES cards (id),
    ruling_text TEXT NOT NULL,
    source TEXT NOT NULL,
    ruling_date DATE,
    embedding VECTOR(384)
);

CREATE TABLE IF NOT EXISTS card_effects_structured (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    card_id UUID NOT NULL REFERENCES cards (id),
    effect_type TEXT NOT NULL,
    activation_condition TEXT,
    cost TEXT,
    targeting TEXT,
    effect TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    confidence_score REAL,
    CHECK (status IN ('pending', 'confirmed'))
);

CREATE TABLE IF NOT EXISTS rulebook_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_text TEXT NOT NULL,
    source TEXT NOT NULL,
    section_reference TEXT,
    embedding VECTOR(384)
);

CREATE TABLE IF NOT EXISTS qa_test_cases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question TEXT NOT NULL,
    expected_answer TEXT NOT NULL,
    expected_citation TEXT,
    notes TEXT
);
```

`src/aijudge/db/migrate.py`:
```python
from pathlib import Path

from .connection import get_connection

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def run_migrations() -> None:
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with get_connection() as conn:
        conn.execute(schema_sql)
        conn.commit()
```

- [ ] **Step 4: Run test, confirm pass**

Run: `docker compose up -d db && cp .env.example .env && pytest tests/db/test_migrate.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/db/__init__.py src/aijudge/db/connection.py src/aijudge/db/schema.sql src/aijudge/db/migrate.py tests/db/__init__.py tests/db/test_migrate.py
git commit -m "feat(db): schema, migration runner, and connection module"
```

---

### Task 8: Cards repo

**Files:**
- Create: `src/aijudge/db/cards_repo.py`
- Test: `tests/db/test_cards_repo.py`

**Interfaces:**
- Consumes: `get_connection` (Task 7)
- Produces: `insert_card(...) -> str` (returns card id), `get_card_by_name(name: str) -> dict | None`, `insert_errata_version(*, card_id: str, errata_date: date, errata_text: str) -> str` — consumed by the seed script (Task 19) and by the Orchestration plan's `lookup_card` tool.

- [ ] **Step 1: Write the failing test**

`tests/db/test_cards_repo.py`:
```python
import os
from datetime import date

import pytest

pytestmark = pytest.mark.skipif("DATABASE_URL" not in os.environ, reason="requires a running Postgres instance")


def setup_function():
    from aijudge.db.connection import get_connection
    from aijudge.db.migrate import run_migrations

    run_migrations()
    with get_connection() as conn:
        conn.execute("TRUNCATE cards CASCADE")
        conn.commit()


def test_insert_and_get_card_by_name():
    from aijudge.db.cards_repo import get_card_by_name, insert_card

    insert_card(
        name="Called by the Grave",
        card_text=(
            "During either player's turn, if a monster(s) is banished, or a card "
            "or effect in the Graveyard is activated: You can target 1 banished "
            "monster; banish it. You can only activate 1 \"Called by the Grave\" "
            "per turn."
        ),
        card_type="Quick-Play Spell",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
    )

    card = get_card_by_name("Called by the Grave")

    assert card is not None
    assert card["card_type"] == "Quick-Play Spell"
    assert card["has_errata"] is False


def test_get_card_by_name_returns_none_when_missing():
    from aijudge.db.cards_repo import get_card_by_name

    assert get_card_by_name("Nonexistent Card") is None


def test_insert_errata_version_sets_has_errata_flag():
    from aijudge.db.cards_repo import get_card_by_name, insert_card, insert_errata_version

    card_id = insert_card(
        name="Card With Errata",
        card_text="Original text.",
        card_type="Normal Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
    )

    insert_errata_version(card_id=card_id, errata_date=date(2026, 8, 18), errata_text="Errata'd text.")

    card = get_card_by_name("Card With Errata")
    assert card["has_errata"] is True
```

- [ ] **Step 2: Run test, confirm failure**

Run: `pytest tests/db/test_cards_repo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aijudge.db.cards_repo'`

- [ ] **Step 3: Implement**

`src/aijudge/db/cards_repo.py`:
```python
from datetime import date

from .connection import get_connection

_CARD_COLUMNS = [
    "id", "name", "card_text", "card_type", "attribute", "monster_type",
    "level", "rank", "link_rating", "archetype", "atk", "def", "has_errata",
]


def insert_card(
    *,
    name: str,
    card_text: str,
    card_type: str,
    source: str,
    fetched_at: date,
    attribute: str | None = None,
    monster_type: str | None = None,
    level: int | None = None,
    rank: int | None = None,
    link_rating: int | None = None,
    archetype: str | None = None,
    atk: int | None = None,
    def_: int | None = None,
    ygoprodeck_id: str | None = None,
    ygoresources_id: str | None = None,
    card_materials: str | None = None,
) -> str:
    with get_connection() as conn:
        row = conn.execute(
            """
            INSERT INTO cards (
                name, card_text, card_type, attribute, monster_type,
                level, rank, link_rating, archetype, atk, def,
                ygoprodeck_id, ygoresources_id, source, fetched_at, card_materials
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                name, card_text, card_type, attribute, monster_type,
                level, rank, link_rating, archetype, atk, def_,
                ygoprodeck_id, ygoresources_id, source, fetched_at, card_materials,
            ),
        ).fetchone()
        conn.commit()
        return str(row[0])


def get_card_by_name(name: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, name, card_text, card_type, attribute, monster_type, "
            "level, rank, link_rating, archetype, atk, def, has_errata "
            "FROM cards WHERE name = %s",
            (name,),
        ).fetchone()
    if row is None:
        return None
    return dict(zip(_CARD_COLUMNS, row))


def insert_errata_version(*, card_id: str, errata_date: date, errata_text: str) -> str:
    with get_connection() as conn:
        row = conn.execute(
            """
            INSERT INTO card_errata_versions (card_id, errata_date, errata_text)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (card_id, errata_date, errata_text),
        ).fetchone()
        conn.execute("UPDATE cards SET has_errata = TRUE WHERE id = %s", (card_id,))
        conn.commit()
        return str(row[0])
```

- [ ] **Step 4: Run test, confirm pass**

Run: `pytest tests/db/test_cards_repo.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/db/cards_repo.py tests/db/test_cards_repo.py
git commit -m "feat(db): cards repo with errata versioning"
```

---

### Task 9: Rulings repo

**Files:**
- Create: `src/aijudge/db/rulings_repo.py`
- Test: `tests/db/test_rulings_repo.py`

**Interfaces:**
- Consumes: `get_connection` (Task 7), a `card_id` from `cards_repo.insert_card` (Task 8)
- Produces: `insert_ruling(*, card_id: str, ruling_text: str, source: str, ruling_date: date | None = None) -> str`, `get_rulings_for_card(card_id: str) -> list[dict]` — consumed by the seed script (Task 19) and by the Orchestration plan's `get_rulings` tool.

- [ ] **Step 1: Write the failing test**

`tests/db/test_rulings_repo.py`:
```python
import os
from datetime import date

import pytest

pytestmark = pytest.mark.skipif("DATABASE_URL" not in os.environ, reason="requires a running Postgres instance")


def setup_function():
    from aijudge.db.connection import get_connection
    from aijudge.db.migrate import run_migrations

    run_migrations()
    with get_connection() as conn:
        conn.execute("TRUNCATE cards CASCADE")
        conn.commit()


def test_insert_and_get_rulings_for_card():
    from aijudge.db.cards_repo import insert_card
    from aijudge.db.rulings_repo import get_rulings_for_card, insert_ruling

    card_id = insert_card(
        name="Ash Blossom & Joyous Spring",
        card_text="You can only use each of the following effects of \"Ash Blossom & Joyous Spring\" once per turn.",
        card_type="Effect Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
    )

    insert_ruling(
        card_id=card_id,
        ruling_text="Ash Blossom's effect cannot be activated in response to itself.",
        source="db.ygoresources",
        ruling_date=date(2021, 1, 1),
    )

    rulings = get_rulings_for_card(card_id)

    assert len(rulings) == 1
    assert rulings[0]["source"] == "db.ygoresources"


def test_get_rulings_for_card_returns_empty_list_when_none_exist():
    from aijudge.db.cards_repo import insert_card
    from aijudge.db.rulings_repo import get_rulings_for_card

    card_id = insert_card(
        name="No Rulings Card",
        card_text="Text.",
        card_type="Normal Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
    )

    assert get_rulings_for_card(card_id) == []
```

- [ ] **Step 2: Run test, confirm failure**

Run: `pytest tests/db/test_rulings_repo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aijudge.db.rulings_repo'`

- [ ] **Step 3: Implement**

`src/aijudge/db/rulings_repo.py`:
```python
from datetime import date

from .connection import get_connection


def insert_ruling(*, card_id: str, ruling_text: str, source: str, ruling_date: date | None = None) -> str:
    with get_connection() as conn:
        row = conn.execute(
            """
            INSERT INTO rulings (card_id, ruling_text, source, ruling_date)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (card_id, ruling_text, source, ruling_date),
        ).fetchone()
        conn.commit()
        return str(row[0])


def get_rulings_for_card(card_id: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, ruling_text, source, ruling_date FROM rulings WHERE card_id = %s",
            (card_id,),
        ).fetchall()
    return [
        {"id": str(r[0]), "ruling_text": r[1], "source": r[2], "ruling_date": r[3]}
        for r in rows
    ]
```

- [ ] **Step 4: Run test, confirm pass**

Run: `pytest tests/db/test_rulings_repo.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/db/rulings_repo.py tests/db/test_rulings_repo.py
git commit -m "feat(db): rulings repo"
```

---

### Task 10: Structured-effects repo (pending/confirmed)

**Files:**
- Create: `src/aijudge/db/effects_repo.py`
- Test: `tests/db/test_effects_repo.py`

**Interfaces:**
- Consumes: `get_connection` (Task 7), a `card_id` from `cards_repo.insert_card` (Task 8)
- Produces: `insert_pending_effect(*, card_id, effect_type, effect, activation_condition=None, cost=None, targeting=None, confidence_score=None) -> str`, `confirm_effect(effect_id: str) -> None`, `get_confirmed_effect(card_id: str) -> dict | None` — consumed by the review agent (Task 15) and the seed script (Task 19), and by the Orchestration plan (a `pending` effect must never be treated as ground truth).

- [ ] **Step 1: Write the failing test**

`tests/db/test_effects_repo.py`:
```python
import os
from datetime import date

import pytest

pytestmark = pytest.mark.skipif("DATABASE_URL" not in os.environ, reason="requires a running Postgres instance")


def setup_function():
    from aijudge.db.connection import get_connection
    from aijudge.db.migrate import run_migrations

    run_migrations()
    with get_connection() as conn:
        conn.execute("TRUNCATE cards CASCADE")
        conn.commit()


def _make_card_id() -> str:
    from aijudge.db.cards_repo import insert_card

    return insert_card(
        name="Infinite Impermanence",
        card_text="Target 1 face-up monster on the field; negate its effects...",
        card_type="Trap Card",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
    )


def test_pending_effect_is_not_returned_as_confirmed():
    from aijudge.db.effects_repo import get_confirmed_effect, insert_pending_effect

    card_id = _make_card_id()
    insert_pending_effect(
        card_id=card_id,
        effect_type="quick-like",
        effect="negate its effects, also, if this card is in the Graveyard...",
        targeting="Target 1 face-up monster on the field",
    )

    assert get_confirmed_effect(card_id) is None


def test_confirm_effect_makes_it_retrievable():
    from aijudge.db.effects_repo import confirm_effect, get_confirmed_effect, insert_pending_effect

    card_id = _make_card_id()
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="quick-like",
        effect="negate its effects.",
        targeting="Target 1 face-up monster on the field",
    )

    confirm_effect(effect_id)
    confirmed = get_confirmed_effect(card_id)

    assert confirmed is not None
    assert confirmed["effect_type"] == "quick-like"
    assert confirmed["targeting"] == "Target 1 face-up monster on the field"
```

- [ ] **Step 2: Run test, confirm failure**

Run: `pytest tests/db/test_effects_repo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aijudge.db.effects_repo'`

- [ ] **Step 3: Implement**

`src/aijudge/db/effects_repo.py`:
```python
from .connection import get_connection

_EFFECT_COLUMNS = ["id", "effect_type", "activation_condition", "cost", "targeting", "effect"]


def insert_pending_effect(
    *,
    card_id: str,
    effect_type: str,
    effect: str,
    activation_condition: str | None = None,
    cost: str | None = None,
    targeting: str | None = None,
    confidence_score: float | None = None,
) -> str:
    with get_connection() as conn:
        row = conn.execute(
            """
            INSERT INTO card_effects_structured (
                card_id, effect_type, activation_condition, cost, targeting,
                effect, status, confidence_score
            ) VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s)
            RETURNING id
            """,
            (card_id, effect_type, activation_condition, cost, targeting, effect, confidence_score),
        ).fetchone()
        conn.commit()
        return str(row[0])


def confirm_effect(effect_id: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE card_effects_structured SET status = 'confirmed' WHERE id = %s",
            (effect_id,),
        )
        conn.commit()


def get_confirmed_effect(card_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, effect_type, activation_condition, cost, targeting, effect
            FROM card_effects_structured
            WHERE card_id = %s AND status = 'confirmed'
            """,
            (card_id,),
        ).fetchone()
    if row is None:
        return None
    return dict(zip(_EFFECT_COLUMNS, row))
```

- [ ] **Step 4: Run test, confirm pass**

Run: `pytest tests/db/test_effects_repo.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/db/effects_repo.py tests/db/test_effects_repo.py
git commit -m "feat(db): structured-effects repo with pending/confirmed status"
```

---

### Task 11: Embedding client interface + mock

**Files:**
- Create: `src/aijudge/embeddings/__init__.py`
- Create: `src/aijudge/embeddings/client.py`
- Test: `tests/embeddings/__init__.py`
- Test: `tests/embeddings/test_client.py`

**Interfaces:**
- Consumes: nothing
- Produces: `EMBEDDING_DIM = 384`, `EmbeddingClient` (Protocol: `embed(text: str) -> list[float]`), `MockEmbeddingClient` — consumed by the rulebook loader (Task 18) and the Orchestration plan's `search_rulebook` tool.

- [ ] **Step 1: Write the failing tests**

`tests/embeddings/__init__.py`: empty file.

`tests/embeddings/test_client.py`:
```python
from aijudge.embeddings.client import EMBEDDING_DIM, MockEmbeddingClient


def test_embed_returns_a_vector_of_the_expected_dimension():
    client = MockEmbeddingClient()
    vector = client.embed("some rulebook text")
    assert len(vector) == EMBEDDING_DIM


def test_embed_is_deterministic():
    client = MockEmbeddingClient()
    assert client.embed("same text") == client.embed("same text")


def test_embed_differs_for_different_text():
    client = MockEmbeddingClient()
    assert client.embed("text one") != client.embed("text two")
```

- [ ] **Step 2: Run tests, confirm failure**

Run: `pytest tests/embeddings/test_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aijudge.embeddings'`

- [ ] **Step 3: Implement**

`src/aijudge/embeddings/__init__.py`: empty file.

`src/aijudge/embeddings/client.py`:
```python
import hashlib
from typing import Protocol

EMBEDDING_DIM = 384


class EmbeddingClient(Protocol):
    def embed(self, text: str) -> list[float]: ...


class MockEmbeddingClient:
    """Deterministic fake embedding client for tests and dev without a real provider."""

    def embed(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [digest[i % len(digest)] / 255 for i in range(EMBEDDING_DIM)]
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `pytest tests/embeddings/test_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/embeddings/__init__.py src/aijudge/embeddings/client.py tests/embeddings/__init__.py tests/embeddings/test_client.py
git commit -m "feat(embeddings): embedding client interface and mock"
```

---

### Task 12: Rulebook chunks repo

**Files:**
- Create: `src/aijudge/db/rulebook_repo.py`
- Test: `tests/db/test_rulebook_repo.py`

**Interfaces:**
- Consumes: `get_connection` (Task 7), a `list[float]` embedding (produced by `EmbeddingClient.embed`, Task 11 — this repo just stores whatever vector it's given)
- Produces: `insert_chunk(*, chunk_text: str, source: str, embedding: list[float], section_reference: str | None = None) -> str`, `list_chunks(source: str | None = None) -> list[dict]` — consumed by the rulebook loader (Task 18) and the Orchestration plan's `search_rulebook` tool.

- [ ] **Step 1: Write the failing test**

`tests/db/test_rulebook_repo.py`:
```python
import os

import pytest

pytestmark = pytest.mark.skipif("DATABASE_URL" not in os.environ, reason="requires a running Postgres instance")


def setup_function():
    from aijudge.db.connection import get_connection
    from aijudge.db.migrate import run_migrations

    run_migrations()
    with get_connection() as conn:
        conn.execute("TRUNCATE rulebook_chunks")
        conn.commit()


def test_insert_and_list_chunks():
    from aijudge.db.rulebook_repo import insert_chunk, list_chunks
    from aijudge.embeddings.client import MockEmbeddingClient

    embedding = MockEmbeddingClient().embed("Priority is the ability of a player to activate...")
    insert_chunk(
        chunk_text="Priority is the ability of a player to activate...",
        source="konami_rulebook",
        embedding=embedding,
        section_reference="3.2",
    )

    chunks = list_chunks(source="konami_rulebook")

    assert len(chunks) == 1
    assert chunks[0]["section_reference"] == "3.2"


def test_list_chunks_filters_by_source():
    from aijudge.db.rulebook_repo import insert_chunk, list_chunks
    from aijudge.embeddings.client import MockEmbeddingClient

    embedding = MockEmbeddingClient().embed("some PSCT guidance")
    insert_chunk(chunk_text="some PSCT guidance", source="psct_guide", embedding=embedding)

    assert list_chunks(source="konami_rulebook") == []
    assert len(list_chunks(source="psct_guide")) == 1
```

- [ ] **Step 2: Run test, confirm failure**

Run: `pytest tests/db/test_rulebook_repo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aijudge.db.rulebook_repo'`

- [ ] **Step 3: Implement**

`src/aijudge/db/rulebook_repo.py`:
```python
from .connection import get_connection


def insert_chunk(
    *, chunk_text: str, source: str, embedding: list[float], section_reference: str | None = None
) -> str:
    with get_connection() as conn:
        row = conn.execute(
            """
            INSERT INTO rulebook_chunks (chunk_text, source, section_reference, embedding)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (chunk_text, source, section_reference, embedding),
        ).fetchone()
        conn.commit()
        return str(row[0])


def list_chunks(source: str | None = None) -> list[dict]:
    query = "SELECT id, chunk_text, source, section_reference FROM rulebook_chunks"
    params: tuple = ()
    if source is not None:
        query += " WHERE source = %s"
        params = (source,)
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [
        {"id": str(r[0]), "chunk_text": r[1], "source": r[2], "section_reference": r[3]}
        for r in rows
    ]
```

- [ ] **Step 4: Run test, confirm pass**

Run: `pytest tests/db/test_rulebook_repo.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/db/rulebook_repo.py tests/db/test_rulebook_repo.py
git commit -m "feat(db): rulebook chunks repo"
```

---

### Task 13: LLM client interface + mock

**Files:**
- Create: `src/aijudge/llm/__init__.py`
- Create: `src/aijudge/llm/client.py`
- Test: `tests/llm/__init__.py`
- Test: `tests/llm/test_client.py`

**Interfaces:**
- Consumes: nothing
- Produces: `LLMClient` (Protocol: `complete(prompt: str) -> str`), `MockLLMClient` (with `queue_response(response: str) -> None` and `complete(prompt: str) -> str`, FIFO — each call to `complete` pops the next queued response, raising `AssertionError` if the queue is empty) — consumed by the review agent (Task 15) now, and by the full agentic orchestration loop in the Orchestration plan.

- [ ] **Step 1: Write the failing tests**

`tests/llm/__init__.py`: empty file.

`tests/llm/test_client.py`:
```python
import pytest

from aijudge.llm.client import MockLLMClient


def test_complete_returns_the_next_queued_response():
    client = MockLLMClient()
    client.queue_response("first")
    client.queue_response("second")

    assert client.complete("any prompt") == "first"
    assert client.complete("any prompt") == "second"


def test_complete_raises_when_queue_is_empty():
    client = MockLLMClient()
    with pytest.raises(AssertionError):
        client.complete("any prompt")
```

- [ ] **Step 2: Run tests, confirm failure**

Run: `pytest tests/llm/test_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aijudge.llm'`

- [ ] **Step 3: Implement**

`src/aijudge/llm/__init__.py`: empty file.

`src/aijudge/llm/client.py`:
```python
from typing import Protocol


class LLMClient(Protocol):
    def complete(self, prompt: str) -> str: ...


class MockLLMClient:
    """Deterministic fake LLM client for tests and dev without a real provider.

    Each call to `complete` pops the next response off a FIFO queue,
    regardless of the prompt — this keeps tests decoupled from exact
    prompt wording while still letting each call in a multi-step flow
    be scripted independently.
    """

    def __init__(self) -> None:
        self._queue: list[str] = []

    def queue_response(self, response: str) -> None:
        self._queue.append(response)

    def complete(self, prompt: str) -> str:
        if not self._queue:
            raise AssertionError("MockLLMClient.complete called with no queued response")
        return self._queue.pop(0)
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `pytest tests/llm/test_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/llm/__init__.py src/aijudge/llm/client.py tests/llm/__init__.py tests/llm/test_client.py
git commit -m "feat(llm): LLM client interface and mock"
```

---

### Task 14: Effect parser (PSCT grammar)

**Files:**
- Create: `src/aijudge/effect_parser/__init__.py`
- Create: `src/aijudge/effect_parser/parser.py`
- Test: `tests/effect_parser/__init__.py`
- Test: `tests/effect_parser/test_parser.py`

**Interfaces:**
- Consumes: `EffectType` (Task 2, for `classify_effect_type`'s return type)
- Produces: `ParsedEffect` (dataclass: `activation_condition: str | None`, `cost: str | None`, `targeting: str | None`, `effect: str`), `parse_psct(card_text: str) -> ParsedEffect`, `classify_effect_type(card_text: str, *, is_monster: bool) -> EffectType` — consumed by the review agent (Task 15) and the seed script (Task 19).

Known limitation documented by tests below (not hidden): the cost/targeting split is a keyword heuristic, not a full parse. It's expected to be wrong on genuinely ambiguous PSCT — that's exactly what the review agent (Task 15) exists to catch.

- [ ] **Step 1: Write the failing tests**

`tests/effect_parser/__init__.py`: empty file.

`tests/effect_parser/test_parser.py`:
```python
from aijudge.effect_parser.parser import classify_effect_type, parse_psct
from aijudge.rules_engine.models import EffectType


def test_splits_condition_cost_and_effect_on_colon_and_semicolon():
    text = "Once per turn: You can banish 1 card from your hand; add 1 card from your Deck to your hand."
    parsed = parse_psct(text)
    assert parsed.activation_condition == "Once per turn"
    assert parsed.effect == "add 1 card from your Deck to your hand."


def test_no_colon_means_no_activation_condition():
    text = "You can target 1 banished monster; banish it."
    parsed = parse_psct(text)
    assert parsed.activation_condition is None
    assert parsed.targeting == "target 1 banished monster"
    assert parsed.effect == "banish it."


def test_no_semicolon_means_the_whole_remainder_is_the_effect():
    text = "As long as this card is on the field, all monsters you control gain 100 ATK."
    parsed = parse_psct(text)
    assert parsed.activation_condition is None
    assert parsed.cost is None
    assert parsed.targeting is None
    assert parsed.effect == text


def test_cost_before_targeting_is_split_on_a_cost_keyword():
    text = "Once per turn: You can banish 1 card from your hand, then target 1 monster on the field; destroy it."
    parsed = parse_psct(text)
    assert parsed.cost == "You can banish 1 card from your hand, then"
    assert parsed.targeting == "target 1 monster on the field"


def test_targeting_only_segment_with_no_cost_keyword_has_no_cost():
    text = "You can target 1 banished monster; banish it."
    parsed = parse_psct(text)
    assert parsed.cost is None


def test_classify_effect_type_for_a_monster_trigger_effect():
    text = "If this card is Normal Summoned: You can add 1 \"Junk\" card from your Deck to your hand."
    assert classify_effect_type(text, is_monster=True) == EffectType.TRIGGER


def test_classify_effect_type_for_a_monster_quick_effect():
    text = "During your Main Phase (Quick Effect): You can target 1 monster; destroy it."
    assert classify_effect_type(text, is_monster=True) == EffectType.QUICK


def test_classify_effect_type_for_a_continuous_effect():
    text = "While this card is face-up on the field, as long as you control no other monsters, this card gains 500 ATK."
    assert classify_effect_type(text, is_monster=True) == EffectType.CONTINUOUS
```

- [ ] **Step 2: Run tests, confirm failure**

Run: `pytest tests/effect_parser/test_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aijudge.effect_parser'`

- [ ] **Step 3: Implement**

`src/aijudge/effect_parser/__init__.py`: empty file.

`src/aijudge/effect_parser/parser.py`:
```python
from dataclasses import dataclass

from aijudge.rules_engine.models import EffectType

_COST_KEYWORDS = ("banish", "discard", "pay", "send", "tribute", "remove", "reveal", "shuffle")


@dataclass
class ParsedEffect:
    activation_condition: str | None
    cost: str | None
    targeting: str | None
    effect: str


def parse_psct(card_text: str) -> ParsedEffect:
    """Split PSCT-formatted card text using its formal grammar:
    `[Condition] : [Cost/Target] ; [Effect]`, where the Condition and
    Cost/Target segments are optional.
    """
    text = card_text.strip()

    if ":" in text:
        activation_condition, remainder = text.split(":", 1)
        activation_condition = activation_condition.strip() or None
        remainder = remainder.strip()
    else:
        activation_condition = None
        remainder = text

    if ";" in remainder:
        cost_and_targeting, effect = remainder.split(";", 1)
        cost_and_targeting = cost_and_targeting.strip()
        effect = effect.strip()
    else:
        cost_and_targeting = None
        effect = remainder

    cost, targeting = _split_cost_and_targeting(cost_and_targeting)

    return ParsedEffect(activation_condition=activation_condition, cost=cost, targeting=targeting, effect=effect)


def _split_cost_and_targeting(segment: str | None) -> tuple[str | None, str | None]:
    if not segment:
        return None, None

    lowered = segment.lower()
    target_index = lowered.find("target")
    if target_index == -1:
        return segment, None

    before_target = segment[:target_index]
    targeting = segment[target_index:].strip()
    has_cost_keyword = any(keyword in before_target.lower() for keyword in _COST_KEYWORDS)
    if not has_cost_keyword:
        return None, targeting

    cost = before_target.strip().rstrip(",")
    return (cost or None), targeting


def classify_effect_type(card_text: str, *, is_monster: bool) -> EffectType:
    lowered = card_text.lower()

    if lowered.startswith("if ") or lowered.startswith("when "):
        return EffectType.TRIGGER if is_monster else EffectType.TRIGGER_LIKE

    if "(quick effect)" in lowered:
        return EffectType.QUICK if is_monster else EffectType.QUICK_LIKE

    if "as long as" in lowered or lowered.startswith("while "):
        return EffectType.CONTINUOUS

    if ":" in card_text:
        return EffectType.IGNITION if is_monster else EffectType.EFFECT

    return EffectType.UNCLASSIFIED if is_monster else EffectType.CONDITION
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `pytest tests/effect_parser/test_parser.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/effect_parser/__init__.py src/aijudge/effect_parser/parser.py tests/effect_parser/__init__.py tests/effect_parser/test_parser.py
git commit -m "feat(effect_parser): code-based PSCT grammar parser and effect-type classifier"
```

---

### Task 15: Effect-parse review agent

**Files:**
- Create: `src/aijudge/effect_parser/review_agent.py`
- Test: `tests/effect_parser/test_review_agent.py`

**Interfaces:**
- Consumes: `LLMClient` (Task 13), `ParsedEffect` (Task 14)
- Produces: `DEFAULT_CONFIDENCE_THRESHOLD = 0.9`, `ReviewResult` (dataclass: `confidence: float`, `auto_confirmed: bool`), `review_parsed_effect(llm_client: LLMClient, *, raw_text: str, activation_condition, cost, targeting, effect, threshold: float = DEFAULT_CONFIDENCE_THRESHOLD) -> ReviewResult` — consumed by the seed script (Task 19).

- [ ] **Step 1: Write the failing tests**

`tests/effect_parser/test_review_agent.py`:
```python
from aijudge.effect_parser.review_agent import review_parsed_effect
from aijudge.llm.client import MockLLMClient


def test_confidence_at_or_above_threshold_auto_confirms():
    llm_client = MockLLMClient()
    llm_client.queue_response("0.95")

    result = review_parsed_effect(
        llm_client,
        raw_text="You can target 1 banished monster; banish it.",
        activation_condition=None,
        cost=None,
        targeting="target 1 banished monster",
        effect="banish it.",
    )

    assert result.confidence == 0.95
    assert result.auto_confirmed is True


def test_confidence_below_threshold_does_not_auto_confirm():
    llm_client = MockLLMClient()
    llm_client.queue_response("0.4")

    result = review_parsed_effect(
        llm_client,
        raw_text="banish 1 card from your hand and target 1 face-up monster; negate it.",
        activation_condition=None,
        cost="ambiguous 'and' — could be a second cost or part of the effect",
        targeting="target 1 face-up monster",
        effect="negate it.",
    )

    assert result.confidence == 0.4
    assert result.auto_confirmed is False


def test_custom_threshold_is_respected():
    llm_client = MockLLMClient()
    llm_client.queue_response("0.92")

    result = review_parsed_effect(
        llm_client,
        raw_text="text",
        activation_condition=None,
        cost=None,
        targeting=None,
        effect="text",
        threshold=0.95,
    )

    assert result.auto_confirmed is False
```

- [ ] **Step 2: Run tests, confirm failure**

Run: `pytest tests/effect_parser/test_review_agent.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aijudge.effect_parser.review_agent'`

- [ ] **Step 3: Implement**

`src/aijudge/effect_parser/review_agent.py`:
```python
from dataclasses import dataclass

from aijudge.llm.client import LLMClient

DEFAULT_CONFIDENCE_THRESHOLD = 0.9


@dataclass
class ReviewResult:
    confidence: float
    auto_confirmed: bool


def review_parsed_effect(
    llm_client: LLMClient,
    *,
    raw_text: str,
    activation_condition: str | None,
    cost: str | None,
    targeting: str | None,
    effect: str,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> ReviewResult:
    prompt = (
        "Score how accurately this structured breakdown captures the raw "
        "card text, from 0.0 to 1.0. Respond with only the number.\n\n"
        f"Raw text: {raw_text}\n\n"
        f"Activation condition: {activation_condition}\n"
        f"Cost: {cost}\n"
        f"Targeting: {targeting}\n"
        f"Effect: {effect}"
    )
    response = llm_client.complete(prompt)
    confidence = float(response)
    return ReviewResult(confidence=confidence, auto_confirmed=confidence >= threshold)
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `pytest tests/effect_parser/test_review_agent.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/effect_parser/review_agent.py tests/effect_parser/test_review_agent.py
git commit -m "feat(effect_parser): LLM confidence review agent"
```

---

### Task 16: YGOPRODeck ingestion client

**Files:**
- Create: `src/aijudge/ingestion/__init__.py`
- Create: `src/aijudge/ingestion/ygoprodeck_client.py`
- Test: `tests/ingestion/__init__.py`
- Test: `tests/ingestion/test_ygoprodeck_client.py`

**Interfaces:**
- Consumes: nothing (network access injected via `http_get` parameter for testability)
- Produces: `CardNotFoundError`, `fetch_card(name: str, *, http_get=requests.get) -> dict` — consumed by the seed script (Task 19) and, later, the Orchestration plan's live-fallback lookup.

- [ ] **Step 1: Write the failing tests**

`tests/ingestion/__init__.py`: empty file.

`tests/ingestion/test_ygoprodeck_client.py`:
```python
import pytest

from aijudge.ingestion.ygoprodeck_client import CardNotFoundError, fetch_card


class _FakeResponse:
    def __init__(self, status_code: int, json_body: dict) -> None:
        self.status_code = status_code
        self._json_body = json_body

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._json_body


def test_fetch_card_returns_first_match():
    def fake_get(url, params, timeout):
        return _FakeResponse(200, {"data": [{"name": params["name"], "type": "Quick-Play Spell"}]})

    card = fetch_card("Called by the Grave", http_get=fake_get)

    assert card["name"] == "Called by the Grave"
    assert card["type"] == "Quick-Play Spell"


def test_fetch_card_raises_card_not_found_on_400():
    def fake_get(url, params, timeout):
        return _FakeResponse(400, {})

    with pytest.raises(CardNotFoundError):
        fetch_card("Nonexistent Card", http_get=fake_get)
```

- [ ] **Step 2: Run tests, confirm failure**

Run: `pytest tests/ingestion/test_ygoprodeck_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aijudge.ingestion'`

- [ ] **Step 3: Implement**

`src/aijudge/ingestion/__init__.py`: empty file.

`src/aijudge/ingestion/ygoprodeck_client.py`:
```python
from typing import Callable

import requests

API_URL = "https://db.ygoprodeck.com/api/v7/cardinfo.php"


class CardNotFoundError(Exception):
    pass


def fetch_card(name: str, *, http_get: Callable[..., "requests.Response"] = requests.get) -> dict:
    response = http_get(API_URL, params={"name": name}, timeout=10)
    if response.status_code == 400:
        raise CardNotFoundError(f"no card found for name={name!r}")
    response.raise_for_status()
    data = response.json()["data"]
    return data[0]
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `pytest tests/ingestion/test_ygoprodeck_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/ingestion/__init__.py src/aijudge/ingestion/ygoprodeck_client.py tests/ingestion/__init__.py tests/ingestion/test_ygoprodeck_client.py
git commit -m "feat(ingestion): YGOPRODeck card-fetch client"
```

---

### Task 17: db.ygoresources ingestion client

**Files:**
- Create: `src/aijudge/ingestion/ygoresources_client.py`
- Test: `tests/ingestion/test_ygoresources_client.py`

**Interfaces:**
- Consumes: nothing (network access injected via `http_get` parameter for testability)
- Produces: `fetch_rulings(card_name: str, *, http_get=requests.get) -> list[dict]` (each dict: `{"text": str, "date": str | None}`) — consumed by the seed script (Task 19).

**Note for the implementer:** db.ygoresources doesn't have widely-published API docs the way YGOPRODeck does. The endpoint/params/response-shape below are a reasonable placeholder contract — verify the real request/response shape against the live site before running the seed script against it for real, and adjust this file's `API_URL`, `params`, and response parsing to match. The test below is written against the *assumed* shape so the module is complete and testable now; update the test alongside the implementation once the real shape is confirmed.

- [ ] **Step 1: Write the failing test**

`tests/ingestion/test_ygoresources_client.py`:
```python
from aijudge.ingestion.ygoresources_client import fetch_rulings


class _FakeResponse:
    def __init__(self, json_body: dict) -> None:
        self._json_body = json_body

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._json_body


def test_fetch_rulings_returns_text_and_date_pairs():
    def fake_get(url, params, timeout):
        return _FakeResponse({"rulings": [{"text": "Ash Blossom cannot respond to itself.", "date": "2021-01-01"}]})

    rulings = fetch_rulings("Ash Blossom & Joyous Spring", http_get=fake_get)

    assert rulings == [{"text": "Ash Blossom cannot respond to itself.", "date": "2021-01-01"}]


def test_fetch_rulings_returns_empty_list_when_none_exist():
    def fake_get(url, params, timeout):
        return _FakeResponse({"rulings": []})

    assert fetch_rulings("No Rulings Card", http_get=fake_get) == []
```

- [ ] **Step 2: Run test, confirm failure**

Run: `pytest tests/ingestion/test_ygoresources_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aijudge.ingestion.ygoresources_client'`

- [ ] **Step 3: Implement**

`src/aijudge/ingestion/ygoresources_client.py`:
```python
from typing import Callable

import requests

API_URL = "https://db.ygoresources.com/api/rulings"


def fetch_rulings(card_name: str, *, http_get: Callable[..., "requests.Response"] = requests.get) -> list[dict]:
    response = http_get(API_URL, params={"card": card_name}, timeout=10)
    response.raise_for_status()
    body = response.json()
    return [{"text": r["text"], "date": r.get("date")} for r in body.get("rulings", [])]
```

- [ ] **Step 4: Run test, confirm pass**

Run: `pytest tests/ingestion/test_ygoresources_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/ingestion/ygoresources_client.py tests/ingestion/test_ygoresources_client.py
git commit -m "feat(ingestion): db.ygoresources rulings client (assumed API shape, verify before real use)"
```

---

### Task 18: Rulebook loader (chunking)

**Files:**
- Create: `src/aijudge/ingestion/rulebook_loader.py`
- Test: `tests/ingestion/test_rulebook_loader.py`

**Interfaces:**
- Consumes: nothing beyond stdlib
- Produces: `chunk_text(text: str, *, max_chars: int = 800) -> list[str]`, `load_rulebook_file(path: Path) -> list[str]` — consumed by the seed script (Task 19), which pairs each chunk with an `EmbeddingClient.embed()` call before storing via `rulebook_repo.insert_chunk`.

- [ ] **Step 1: Write the failing tests**

`tests/ingestion/test_rulebook_loader.py`:
```python
from aijudge.ingestion.rulebook_loader import chunk_text, load_rulebook_file


def test_short_paragraphs_are_grouped_into_one_chunk():
    text = "Paragraph one.\n\nParagraph two."
    chunks = chunk_text(text, max_chars=800)
    assert chunks == ["Paragraph one.\n\nParagraph two."]


def test_paragraphs_exceeding_max_chars_split_into_separate_chunks():
    text = "A" * 500 + "\n\n" + "B" * 500
    chunks = chunk_text(text, max_chars=800)
    assert len(chunks) == 2
    assert chunks[0] == "A" * 500
    assert chunks[1] == "B" * 500


def test_load_rulebook_file_reads_and_chunks(tmp_path):
    file_path = tmp_path / "rulebook.txt"
    file_path.write_text("Section one.\n\nSection two.", encoding="utf-8")

    chunks = load_rulebook_file(file_path)

    assert chunks == ["Section one.\n\nSection two."]
```

- [ ] **Step 2: Run tests, confirm failure**

Run: `pytest tests/ingestion/test_rulebook_loader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aijudge.ingestion.rulebook_loader'`

- [ ] **Step 3: Implement**

`src/aijudge/ingestion/rulebook_loader.py`:
```python
from pathlib import Path


def chunk_text(text: str, *, max_chars: int = 800) -> list[str]:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) + 2 > max_chars:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        chunks.append(current)
    return chunks


def load_rulebook_file(path: Path) -> list[str]:
    return chunk_text(path.read_text(encoding="utf-8"))
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `pytest tests/ingestion/test_rulebook_loader.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/ingestion/rulebook_loader.py tests/ingestion/test_rulebook_loader.py
git commit -m "feat(ingestion): rulebook text chunker"
```

---

### Task 19: Seed script for the hand-picked card set

**Files:**
- Create: `src/aijudge/ingestion/seed.py`
- Test: `tests/ingestion/test_seed.py`

**Interfaces:**
- Consumes: `fetch_card` (Task 16), `fetch_rulings` (Task 17), `insert_card`/`insert_errata_version` (Task 8), `insert_ruling` (Task 9), `parse_psct`/`classify_effect_type` (Task 14), `review_parsed_effect` (Task 15), `insert_pending_effect`/`confirm_effect` (Task 10), `LLMClient` (Task 13)
- Produces: `HAND_PICKED_CARDS: list[str]`, `seed_card(name: str, *, llm_client: LLMClient, fetch_card_fn=fetch_card, fetch_rulings_fn=fetch_rulings) -> str` (returns the card id), `run_seed(llm_client: LLMClient) -> list[str]` (seeds every card in `HAND_PICKED_CARDS`, returns their ids) — this is the integration point the Orchestration plan's tools query against.

- [ ] **Step 1: Write the failing test**

`tests/ingestion/test_seed.py`:
```python
import os
from datetime import date

import pytest

pytestmark = pytest.mark.skipif("DATABASE_URL" not in os.environ, reason="requires a running Postgres instance")


def setup_function():
    from aijudge.db.connection import get_connection
    from aijudge.db.migrate import run_migrations

    run_migrations()
    with get_connection() as conn:
        conn.execute("TRUNCATE cards CASCADE")
        conn.commit()


def test_seed_card_stores_card_ruling_and_confirms_a_high_confidence_effect():
    from aijudge.db.cards_repo import get_card_by_name
    from aijudge.db.effects_repo import get_confirmed_effect
    from aijudge.db.rulings_repo import get_rulings_for_card
    from aijudge.ingestion.seed import seed_card
    from aijudge.llm.client import MockLLMClient

    def fake_fetch_card(name, http_get=None):
        return {
            "name": name,
            "type": "Quick-Play Spell",
            "desc": "You can target 1 banished monster; banish it.",
        }

    def fake_fetch_rulings(name, http_get=None):
        return [{"text": "Can target monsters banished this turn.", "date": "2021-01-01"}]

    llm_client = MockLLMClient()
    llm_client.queue_response("0.97")  # review agent confidence for the parsed effect

    card_id = seed_card(
        "Called by the Grave",
        llm_client=llm_client,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=fake_fetch_rulings,
    )

    card = get_card_by_name("Called by the Grave")
    assert card is not None
    assert card["id"] == card_id

    rulings = get_rulings_for_card(card_id)
    assert len(rulings) == 1

    confirmed_effect = get_confirmed_effect(card_id)
    assert confirmed_effect is not None
    assert confirmed_effect["targeting"] == "target 1 banished monster"


def test_seed_card_leaves_low_confidence_effect_pending():
    from aijudge.db.cards_repo import get_card_by_name
    from aijudge.db.effects_repo import get_confirmed_effect
    from aijudge.ingestion.seed import seed_card
    from aijudge.llm.client import MockLLMClient

    def fake_fetch_card(name, http_get=None):
        return {
            "name": name,
            "type": "Trap Card",
            "desc": "Target 1 face-up monster; negate its effects.",
        }

    def fake_fetch_rulings(name, http_get=None):
        return []

    llm_client = MockLLMClient()
    llm_client.queue_response("0.3")  # deliberately low confidence

    card_id = seed_card(
        "Ambiguous Trap",
        llm_client=llm_client,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=fake_fetch_rulings,
    )

    assert get_card_by_name("Ambiguous Trap")["id"] == card_id
    assert get_confirmed_effect(card_id) is None
```

- [ ] **Step 2: Run test, confirm failure**

Run: `pytest tests/ingestion/test_seed.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aijudge.ingestion.seed'`

- [ ] **Step 3: Implement**

`src/aijudge/ingestion/seed.py`:
```python
from datetime import date, datetime
from typing import Callable

from aijudge.db.cards_repo import insert_card
from aijudge.db.effects_repo import confirm_effect, insert_pending_effect
from aijudge.db.rulings_repo import insert_ruling
from aijudge.effect_parser.parser import classify_effect_type, parse_psct
from aijudge.effect_parser.review_agent import review_parsed_effect
from aijudge.ingestion.ygoprodeck_client import fetch_card
from aijudge.ingestion.ygoresources_client import fetch_rulings
from aijudge.llm.client import LLMClient

HAND_PICKED_CARDS: list[str] = [
    "Ash Blossom & Joyous Spring",
    "Called by the Grave",
    "Infinite Impermanence",
    "Effect Veiler",
    "Solemn Strike",
]

_MONSTER_TYPES = {"Effect Monster", "Normal Monster", "Fusion Monster", "Synchro Monster", "Xyz Monster", "Link Monster"}


def seed_card(
    name: str,
    *,
    llm_client: LLMClient,
    fetch_card_fn: Callable[..., dict] = fetch_card,
    fetch_rulings_fn: Callable[..., list[dict]] = fetch_rulings,
) -> str:
    card_data = fetch_card_fn(name)
    card_type = card_data["type"]
    card_text = card_data["desc"]

    card_id = insert_card(
        name=card_data["name"],
        card_text=card_text,
        card_type=card_type,
        source="ygoprodeck",
        fetched_at=datetime.utcnow().date(),
    )

    for ruling in fetch_rulings_fn(name):
        raw_date = ruling.get("date")
        insert_ruling(
            card_id=card_id,
            ruling_text=ruling["text"],
            source="db.ygoresources",
            ruling_date=date.fromisoformat(raw_date) if raw_date else None,
        )

    is_monster = card_type in _MONSTER_TYPES
    effect_type = classify_effect_type(card_text, is_monster=is_monster)
    parsed = parse_psct(card_text)

    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type=effect_type.value,
        effect=parsed.effect,
        activation_condition=parsed.activation_condition,
        cost=parsed.cost,
        targeting=parsed.targeting,
    )

    review = review_parsed_effect(
        llm_client,
        raw_text=card_text,
        activation_condition=parsed.activation_condition,
        cost=parsed.cost,
        targeting=parsed.targeting,
        effect=parsed.effect,
    )
    if review.auto_confirmed:
        confirm_effect(effect_id)

    return card_id


def run_seed(llm_client: LLMClient) -> list[str]:
    return [seed_card(name, llm_client=llm_client) for name in HAND_PICKED_CARDS]


if __name__ == "__main__":
    from aijudge.llm.client import MockLLMClient

    ids = run_seed(MockLLMClient())
    print(f"seeded {len(ids)} cards")
```

- [ ] **Step 4: Run test, confirm pass**

Run: `pytest tests/ingestion/test_seed.py -v`
Expected: PASS

- [ ] **Step 5: Run the full test suite to confirm nothing regressed**

Run: `pytest -v`
Expected: all tests PASS (DB-dependent ones require `docker compose up -d db` and a populated `.env`)

- [ ] **Step 6: Commit**

```bash
git add src/aijudge/ingestion/seed.py tests/ingestion/test_seed.py
git commit -m "feat(ingestion): seed script for the hand-picked card set"
```
