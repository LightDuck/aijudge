# Deterministic Activation Recognition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ground activation legality in deterministic, already-confirmed data — structural activatability, a sourced Damage Step rule, and real rulebook content — instead of unvalidated LLM judgment, per the project's "the rules engine and database decide" principle.

**Architecture:** Two new pure rule functions in `rules_engine` (structural activatability, Damage Step legality) wired into `resolve_chain`'s existing violation pattern; two new ingestion-time classifiers in `effect_parser` feeding two new `card_effects_structured` columns through the existing `review_agent` confidence gate; a new `orchestration/preflight.py` module doing fuzzy card-name recognition and rendering confirmed facts, wired into `cli.py`; and a script that finally populates the previously-empty `rulebook_chunks` table.

**Tech Stack:** Python, psycopg3 + pgvector (Postgres), pytest. No new third-party dependencies — fuzzy matching uses stdlib `difflib`.

**Spec:** `docs/superpowers/specs/2026-08-27-activation-recognition-design.md`

## Global Constraints

- TDD: a failing test precedes implementation code in every task (project-wide convention, restated here since it governs every step below).
- Global game law (structural activatability, the Damage Step rule) is hardcoded directly in `rules_engine` — fixed-size, does not grow with card count.
- Per-card data (the Damage Step category tag, usage-limit text) is derived at **ingestion time** through `effect_parser` and gated by `review_agent`'s confidence threshold — never parsed at answer-time inside the engine.
- The rulebook ingestion source is the **live current Konami rulebook page** (`https://www.yugioh-card.com/eu/play/tcg-rulebook/`), not a frozen PDF snapshot.
- Once-per-turn / usage-limit text is parsed and stored for reference only — it is **never** wired into any legality check (the project tracks no live game state).
- **Out of scope for this plan** (per spec Non-goals/Out of scope): Component 3's `get_confirmed_effects` (plural) fix and the effect-recognition matcher, and Component 4b's condition-satisfaction matching algorithm. Both are explicitly deferred to a follow-up design pass. Do not implement them here even if a task below seems to invite it.
- DB-dependent tests use the existing project pattern: `pytestmark = pytest.mark.skipif("DATABASE_URL" not in os.environ, reason="requires a running Postgres instance")` at module level, plus a `setup_function` that calls `run_migrations()` and truncates the tables the test touches. Pure-Python tests carry no such marker and must not import anything that opens a DB connection at import time.
- The schema has no `ALTER`-based migration system (`migrate.py` just re-runs `schema.sql`, which uses `CREATE TABLE IF NOT EXISTS`). Any task that changes `schema.sql` requires a fresh DB afterward — drop and recreate the `card_effects_structured`/`rulebook_chunks` tables, or run `docker compose down -v && docker compose up -d db` to get a clean volume, before running its tests.

---

## File Structure

- `src/aijudge/rules_engine/models.py` — **modify**: add `is_activatable()`, add `damage_step_category` field to `Effect`.
- `src/aijudge/rules_engine/priority.py` — **modify**: add `can_activate_during_damage_step()`.
- `src/aijudge/rules_engine/resolve.py` — **modify**: wire both new checks into `resolve_chain`, extend `_build_effect`.
- `src/aijudge/db/schema.sql` — **modify**: two new nullable columns on `card_effects_structured`.
- `src/aijudge/db/effects_repo.py` — **modify**: carry the two new columns through `insert_pending_effect`/`get_confirmed_effect`.
- `src/aijudge/db/cards_repo.py` — **modify**: add `list_card_names()`.
- `src/aijudge/effect_parser/parser.py` — **modify**: add `classify_damage_step_category()`, `extract_usage_limit_text()`.
- `src/aijudge/effect_parser/review_agent.py` — **modify**: `review_parsed_effect()` gains a `damage_step_category` parameter.
- `src/aijudge/ingestion/seed.py` — **modify**: wire the two new parser functions into `seed_card`.
- `src/aijudge/ingestion/rulebook_seed.py` — **create**: `seed_rulebook_file()`.
- `src/aijudge/orchestration/preflight.py` — **create**: `find_mentioned_card_names()`, `find_matched_cards()`, `build_known_facts_context()`.
- `src/aijudge/orchestration/clarify.py` — **modify**: label support for a new `"disambiguate_card"` item kind.
- `src/aijudge/cli.py` — **modify**: wire preflight into `run_cli`.
- Test files mirror each of the above under `tests/`, following the existing 1:1 module-to-test-file convention.

---

### Task 1: Structural activatability (`is_activatable`)

**Files:**
- Modify: `src/aijudge/rules_engine/models.py`
- Modify: `src/aijudge/rules_engine/resolve.py`
- Test: `tests/rules_engine/test_models.py`
- Test: `tests/rules_engine/test_resolve.py`

**Interfaces:**
- Produces: `rules_engine.models.is_activatable(effect_type: EffectType) -> bool`. Used by Task 2 and by `resolve_chain`.
- Produces: a new `Violation.reason` value, `"not_activatable"`, returned by `resolve_chain` on an `"activate"` step whose effect type isn't activatable.

- [ ] **Step 1: Write the failing tests**

Append to `tests/rules_engine/test_models.py`:

```python
def test_is_activatable_returns_false_for_continuous_and_condition():
    assert is_activatable(EffectType.CONTINUOUS) is False
    assert is_activatable(EffectType.CONDITION) is False


def test_is_activatable_returns_true_for_other_effect_types():
    assert is_activatable(EffectType.TRIGGER) is True
    assert is_activatable(EffectType.TRIGGER_LIKE) is True
    assert is_activatable(EffectType.IGNITION) is True
    assert is_activatable(EffectType.QUICK) is True
    assert is_activatable(EffectType.QUICK_LIKE) is True
    assert is_activatable(EffectType.EFFECT) is True
```

Update the top import line to:
```python
from aijudge.rules_engine.models import Effect, EffectType, SpellSpeed, is_activatable, spell_speed_for
```

Append to `tests/rules_engine/test_resolve.py`:

```python
def test_activate_step_with_continuous_effect_type_is_not_activatable():
    scenario = {
        "turn_player": "player_a",
        "steps": [{"kind": "activate", "effect": _effect("Skill Drain", "player_a", effect_type="continuous")}],
    }

    result = resolve_chain(scenario)

    assert result.violation is not None
    assert result.violation.step_index == 0
    assert result.violation.reason == "not_activatable"
    assert result.resolution_order == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/rules_engine/test_models.py tests/rules_engine/test_resolve.py -v`
Expected: FAIL — `ImportError: cannot import name 'is_activatable'` (test_models.py), and the new resolve test fails because no violation is currently produced (`continuous` effects chain successfully today).

- [ ] **Step 3: Implement `is_activatable`**

In `src/aijudge/rules_engine/models.py`, add after `_QUICK_EFFECT_TYPES`:

```python
_NON_ACTIVATABLE_EFFECT_TYPES = {EffectType.CONTINUOUS, EffectType.CONDITION}


def is_activatable(effect_type: EffectType) -> bool:
    """Whether an effect of this type can ever be "activated" at all.

    Continuous and Condition effects are never activated in the game-rules
    sense -- they apply automatically or describe a standing restriction.
    Every other EffectType can be activated. This is independent of
    timing/priority legality, which `can_activate_now` and
    `can_activate_during_damage_step` handle separately.
    """
    return effect_type not in _NON_ACTIVATABLE_EFFECT_TYPES
```

- [ ] **Step 4: Wire into `resolve_chain`**

In `src/aijudge/rules_engine/resolve.py`, update the import line:

```python
from .models import Effect, EffectType, SpellSpeed, is_activatable
```

In `resolve_chain`, inside the `elif kind == "activate":` branch, insert this check immediately after `effect = _build_effect(step["effect"])` and before the existing `if not can_activate_now(...)` block:

```python
            if not is_activatable(effect.effect_type):
                violation = Violation(
                    step_index=step_index,
                    reason="not_activatable",
                    detail=f"{effect.card_name}'s effect type ({effect.effect_type.value}) cannot be activated",
                )
                return ResolutionResult(resolution_order=_order(chain), violation=violation)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/rules_engine/test_models.py tests/rules_engine/test_resolve.py -v`
Expected: PASS, all tests including the two pre-existing files' full suites (no regressions).

- [ ] **Step 6: Commit**

```bash
git add src/aijudge/rules_engine/models.py src/aijudge/rules_engine/resolve.py tests/rules_engine/test_models.py tests/rules_engine/test_resolve.py
git commit -m "feat(rules_engine): reject activation of structurally non-activatable effect types"
```

---

### Task 2: Damage Step legality (`can_activate_during_damage_step`)

**Files:**
- Modify: `src/aijudge/rules_engine/models.py`
- Modify: `src/aijudge/rules_engine/priority.py`
- Modify: `src/aijudge/rules_engine/resolve.py`
- Test: `tests/rules_engine/test_models.py`
- Test: `tests/rules_engine/test_priority.py`
- Test: `tests/rules_engine/test_resolve.py`

**Interfaces:**
- Consumes: `Effect` (Task 1's file), `SpellSpeed` (existing).
- Produces: `Effect.damage_step_category: str | None` field (values: `"atk_def_alter"`, `"negates_activation"`, or `None`).
- Produces: `rules_engine.priority.can_activate_during_damage_step(effect: Effect) -> bool`.
- Produces: a new `Violation.reason` value, `"damage_step_restricted"`, returned by `resolve_chain` when an `"activate"` step sets `"in_damage_step": True` and the effect fails the check.
- Produces: `resolve_chain` scenario steps of kind `"activate"` now accept an optional `"in_damage_step": bool` key (default `False`) alongside the existing `"effect"` key; the effect dict accepts an optional `"damage_step_category"` key.

**Sourced rule (from the spec, Component 5):** during the Damage Step, only three categories of effect may be activated by default: Spell Speed 2 effects that alter ATK/DEF, Spell Speed 2 effects that negate an activation, and Spell Speed 3 (Counter Trap) cards.

- [ ] **Step 1: Write the failing tests**

Append to `tests/rules_engine/test_models.py`:

```python
def test_effect_accepts_damage_step_category():
    effect = Effect(
        card_id="1",
        card_name="Effect Veiler",
        effect_type=EffectType.QUICK,
        controller="player_a",
        spell_speed=SpellSpeed.QUICK,
        damage_step_category="atk_def_alter",
    )
    assert effect.damage_step_category == "atk_def_alter"


def test_effect_damage_step_category_defaults_to_none():
    effect = Effect(card_id="1", card_name="Card A", effect_type=EffectType.IGNITION, controller="player_a")
    assert effect.damage_step_category is None
```

Append to `tests/rules_engine/test_priority.py`:

```python
def test_counter_speed_can_activate_during_damage_step_regardless_of_category():
    effect = Effect(
        card_id="1",
        card_name="Solemn Strike",
        effect_type=EffectType.TRIGGER_LIKE,
        controller="player_a",
        spell_speed=SpellSpeed.COUNTER,
    )
    assert can_activate_during_damage_step(effect) is True


def test_quick_speed_atk_def_alter_can_activate_during_damage_step():
    effect = Effect(
        card_id="1",
        card_name="Effect Veiler",
        effect_type=EffectType.QUICK,
        controller="player_a",
        spell_speed=SpellSpeed.QUICK,
        damage_step_category="atk_def_alter",
    )
    assert can_activate_during_damage_step(effect) is True


def test_quick_speed_negates_activation_can_activate_during_damage_step():
    effect = Effect(
        card_id="1",
        card_name="Some Counter",
        effect_type=EffectType.QUICK,
        controller="player_a",
        spell_speed=SpellSpeed.QUICK,
        damage_step_category="negates_activation",
    )
    assert can_activate_during_damage_step(effect) is True


def test_quick_speed_with_no_damage_step_category_cannot_activate_during_damage_step():
    effect = Effect(
        card_id="1",
        card_name="Called by the Grave",
        effect_type=EffectType.QUICK_LIKE,
        controller="player_a",
        spell_speed=SpellSpeed.QUICK,
    )
    assert can_activate_during_damage_step(effect) is False


def test_normal_speed_cannot_activate_during_damage_step():
    effect = Effect(card_id="1", card_name="Card A", effect_type=EffectType.IGNITION, controller="player_a")
    assert can_activate_during_damage_step(effect) is False
```

Update the top import line of `tests/rules_engine/test_priority.py` to:
```python
from aijudge.rules_engine.priority import can_activate_during_damage_step, can_activate_now
```

Append to `tests/rules_engine/test_resolve.py`:

```python
def test_activate_step_in_damage_step_without_permitted_category_is_restricted():
    scenario = {
        "turn_player": "player_a",
        "steps": [
            {
                "kind": "activate",
                "effect": _effect("Called by the Grave", "player_a", effect_type="quick-like", spell_speed=2),
                "in_damage_step": True,
            }
        ],
    }

    result = resolve_chain(scenario)

    assert result.violation is not None
    assert result.violation.reason == "damage_step_restricted"
    assert result.resolution_order == []


def test_activate_step_in_damage_step_with_atk_def_alter_category_succeeds():
    scenario = {
        "turn_player": "player_a",
        "steps": [
            {
                "kind": "activate",
                "effect": {
                    "card_name": "Effect Veiler",
                    "controller": "player_a",
                    "effect_type": "quick",
                    "spell_speed": 2,
                    "prevents_response": False,
                    "damage_step_category": "atk_def_alter",
                },
                "in_damage_step": True,
            }
        ],
    }

    result = resolve_chain(scenario)

    assert result.violation is None
    assert [link.card_name for link in result.resolution_order] == ["Effect Veiler"]


def test_activate_step_not_in_damage_step_ignores_the_damage_step_check():
    scenario = {
        "turn_player": "player_a",
        "steps": [
            {"kind": "activate", "effect": _effect("Called by the Grave", "player_a", effect_type="quick-like", spell_speed=2)}
        ],
    }

    result = resolve_chain(scenario)

    assert result.violation is None
```

Note: the `_effect()` helper in this file doesn't take a `damage_step_category` kwarg — that's why the two new "succeeds" tests above pass a hand-built effect dict directly (matching the existing style already used for e.g. `SEGOC`/priority tests when extra fields are needed).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/rules_engine/test_models.py tests/rules_engine/test_priority.py tests/rules_engine/test_resolve.py -v`
Expected: FAIL — `TypeError: Effect.__init__() got an unexpected keyword argument 'damage_step_category'` and `ImportError: cannot import name 'can_activate_during_damage_step'`.

- [ ] **Step 3: Add the field to `Effect`**

In `src/aijudge/rules_engine/models.py`, update the `Effect` dataclass:

```python
@dataclass
class Effect:
    card_id: str
    card_name: str
    effect_type: EffectType
    controller: str
    spell_speed: SpellSpeed = SpellSpeed.NORMAL
    prevents_response: bool = False
    damage_step_category: str | None = None
```

- [ ] **Step 4: Implement `can_activate_during_damage_step`**

In `src/aijudge/rules_engine/priority.py`, update the import line and add the function:

```python
from .chain import Chain
from .models import Effect, SpellSpeed

_DAMAGE_STEP_ALLOWED_CATEGORIES = {"atk_def_alter", "negates_activation"}


def can_activate_during_damage_step(effect: Effect) -> bool:
    """Whether `effect` may be activated during the Damage Step.

    Per the current official rulebook, only three categories of
    activation are allowed by default during the Damage Step: Spell
    Speed 2 effects that alter ATK/DEF, Spell Speed 2 effects that
    negate an activation, and Spell Speed 3 (Counter Trap) cards. This
    is independent of `can_activate_now`'s chain-response priority
    check -- both must pass for a Damage Step activation to be legal.
    """
    if effect.spell_speed == SpellSpeed.COUNTER:
        return True
    if effect.spell_speed == SpellSpeed.QUICK:
        return effect.damage_step_category in _DAMAGE_STEP_ALLOWED_CATEGORIES
    return False
```

- [ ] **Step 5: Wire into `resolve_chain`**

In `src/aijudge/rules_engine/resolve.py`:

Update imports:
```python
from .chain import Chain
from .models import Effect, EffectType, SpellSpeed, is_activatable
from .priority import can_activate_during_damage_step, can_activate_now
from .segoc import apply_segoc
```

Update `_build_effect` to carry the new field:

```python
def _build_effect(data: dict) -> Effect:
    return Effect(
        card_id=data["card_name"],
        card_name=data["card_name"],
        effect_type=EffectType(data["effect_type"]),
        controller=data["controller"],
        spell_speed=SpellSpeed(data.get("spell_speed", SpellSpeed.NORMAL.value)),
        prevents_response=data.get("prevents_response", False),
        damage_step_category=data.get("damage_step_category"),
    )
```

In `resolve_chain`, insert this check right after the `is_activatable` check added in Task 1, still before the existing `can_activate_now` check:

```python
            if step.get("in_damage_step", False) and not can_activate_during_damage_step(effect):
                violation = Violation(
                    step_index=step_index,
                    reason="damage_step_restricted",
                    detail=(
                        f"{effect.card_name} cannot be activated during the Damage Step "
                        "(not Speed 3, and not a Speed 2 ATK/DEF-altering or activation-negating effect)"
                    ),
                )
                return ResolutionResult(resolution_order=_order(chain), violation=violation)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/rules_engine/ -v`
Expected: PASS, entire `rules_engine` suite green, no regressions.

- [ ] **Step 7: Commit**

```bash
git add src/aijudge/rules_engine/models.py src/aijudge/rules_engine/priority.py src/aijudge/rules_engine/resolve.py tests/rules_engine/test_models.py tests/rules_engine/test_priority.py tests/rules_engine/test_resolve.py
git commit -m "feat(rules_engine): source Damage Step activation legality from Spell Speed and effect category"
```

---

### Task 3: `card_effects_structured` gains `damage_step_category` and `usage_limit_text`

**Files:**
- Modify: `src/aijudge/db/schema.sql`
- Modify: `src/aijudge/db/effects_repo.py`
- Test: `tests/db/test_effects_repo.py`

**Interfaces:**
- Produces: `effects_repo.insert_pending_effect(..., damage_step_category: str | None = None, usage_limit_text: str | None = None)`.
- Produces: `get_confirmed_effect()` result dicts now include `"damage_step_category"` and `"usage_limit_text"` keys.
- Consumed by: Task 7 (`seed.py`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/db/test_effects_repo.py`:

```python
def test_confirmed_effect_includes_damage_step_category_and_usage_limit_text():
    from aijudge.db.effects_repo import confirm_effect, get_confirmed_effect, insert_pending_effect

    card_id = _make_card_id()
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="quick",
        effect="its ATK becomes 0.",
        damage_step_category="atk_def_alter",
        usage_limit_text='You can only use this effect of "Effect Veiler" once per turn.',
    )

    confirm_effect(effect_id)
    confirmed = get_confirmed_effect(card_id)

    assert confirmed is not None
    assert confirmed["damage_step_category"] == "atk_def_alter"
    assert confirmed["usage_limit_text"] == 'You can only use this effect of "Effect Veiler" once per turn.'


def test_confirmed_effect_damage_step_category_and_usage_limit_text_default_to_none():
    from aijudge.db.effects_repo import confirm_effect, get_confirmed_effect, insert_pending_effect

    card_id = _make_card_id()
    effect_id = insert_pending_effect(card_id=card_id, effect_type="ignition", effect="destroy it.")

    confirm_effect(effect_id)
    confirmed = get_confirmed_effect(card_id)

    assert confirmed["damage_step_category"] is None
    assert confirmed["usage_limit_text"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/db/test_effects_repo.py -v`
Expected: FAIL — `TypeError: insert_pending_effect() got an unexpected keyword argument 'damage_step_category'` (requires `DATABASE_URL` set and `docker compose up -d db` running; if it isn't, this and every other DB task below will show as SKIPPED rather than FAIL/PASS — start the DB first per CLAUDE.md before working through this task).

- [ ] **Step 3: Update the schema**

In `src/aijudge/db/schema.sql`, replace the `card_effects_structured` table definition with:

```sql
CREATE TABLE IF NOT EXISTS card_effects_structured (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    card_id UUID NOT NULL REFERENCES cards (id),
    effect_type TEXT NOT NULL,
    activation_condition TEXT,
    cost TEXT,
    targeting TEXT,
    has_target BOOLEAN NOT NULL DEFAULT FALSE,
    effect TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    confidence_score REAL,
    damage_step_category TEXT,
    usage_limit_text TEXT,
    CHECK (status IN ('pending', 'confirmed')),
    CHECK (damage_step_category IN ('atk_def_alter', 'negates_activation') OR damage_step_category IS NULL)
);
```

Since `CREATE TABLE IF NOT EXISTS` does not alter an already-existing table, drop the table before re-running migrations if you have a local DB from before this task:

```bash
docker compose down -v
docker compose up -d db
```

(`down -v` removes the Postgres data volume — safe here since the project's only persisted data is the 5 hand-picked seeded cards, which `run_seed` can always regenerate.)

- [ ] **Step 4: Update `effects_repo.py`**

In `src/aijudge/db/effects_repo.py`:

```python
from .connection import get_connection

_EFFECT_COLUMNS = [
    "id", "effect_type", "activation_condition", "cost", "targeting", "has_target", "effect",
    "damage_step_category", "usage_limit_text",
]


def insert_pending_effect(
    *,
    card_id: str,
    effect_type: str,
    effect: str,
    activation_condition: str | None = None,
    cost: str | None = None,
    targeting: str | None = None,
    has_target: bool = False,
    confidence_score: float | None = None,
    damage_step_category: str | None = None,
    usage_limit_text: str | None = None,
) -> str:
    with get_connection() as conn:
        row = conn.execute(
            """
            INSERT INTO card_effects_structured (
                card_id, effect_type, activation_condition, cost, targeting,
                has_target, effect, status, confidence_score,
                damage_step_category, usage_limit_text
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s, %s)
            RETURNING id
            """,
            (
                card_id, effect_type, activation_condition, cost, targeting, has_target, effect,
                confidence_score, damage_step_category, usage_limit_text,
            ),
        ).fetchone()
        conn.commit()
        return str(row[0])


def confirm_effect(effect_id: str) -> None:
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE card_effects_structured SET status = 'confirmed' WHERE id = %s",
            (effect_id,),
        )
        if cur.rowcount != 1:
            raise ValueError(f"no card_effects_structured row with id={effect_id!r} to confirm")
        conn.commit()


def get_confirmed_effect(card_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, effect_type, activation_condition, cost, targeting, has_target, effect,
                   damage_step_category, usage_limit_text
            FROM card_effects_structured
            WHERE card_id = %s AND status = 'confirmed'
            """,
            (card_id,),
        ).fetchone()
    if row is None:
        return None
    row_list = list(row)
    row_list[0] = str(row_list[0])
    return dict(zip(_EFFECT_COLUMNS, row_list))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/db/test_effects_repo.py -v`
Expected: PASS, including all pre-existing tests in the file (no regressions).

- [ ] **Step 6: Commit**

```bash
git add src/aijudge/db/schema.sql src/aijudge/db/effects_repo.py tests/db/test_effects_repo.py
git commit -m "feat(db): add damage_step_category and usage_limit_text to card_effects_structured"
```

---

### Task 4: Parser — `classify_damage_step_category`

**Files:**
- Modify: `src/aijudge/effect_parser/parser.py`
- Test: `tests/effect_parser/test_parser.py`

**Interfaces:**
- Produces: `effect_parser.parser.classify_damage_step_category(effect_text: str) -> str | None`. Returns `"negates_activation"`, `"atk_def_alter"`, or `None`. Consumed by Task 6 (`review_agent`) and Task 7 (`seed.py`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/effect_parser/test_parser.py`:

```python
def test_classify_damage_step_category_detects_negates_activation():
    text = "negate the activation of that card or effect, and if you do, destroy it."
    assert classify_damage_step_category(text) == "negates_activation"


def test_classify_damage_step_category_detects_atk_def_alter():
    text = "until the end of this turn, negate the effects of 1 Effect Monster your opponent controls, also its ATK becomes 0."
    assert classify_damage_step_category(text) == "atk_def_alter"


def test_classify_damage_step_category_prefers_negates_activation_when_both_phrases_present():
    text = "negate the activation of that card or effect; also, the ATK of that monster becomes 0."
    assert classify_damage_step_category(text) == "negates_activation"


def test_classify_damage_step_category_returns_none_when_neither_pattern_matches():
    text = "target 1 banished monster; banish it."
    assert classify_damage_step_category(text) is None
```

Update the top import line to:
```python
from aijudge.effect_parser.parser import classify_damage_step_category, classify_effect_type, parse_psct
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/effect_parser/test_parser.py -v`
Expected: FAIL — `ImportError: cannot import name 'classify_damage_step_category'`.

- [ ] **Step 3: Implement `classify_damage_step_category`**

In `src/aijudge/effect_parser/parser.py`, add near the top (after the existing `_CONNECTOR_PATTERN` definition) and at the end of the file:

```python
_NEGATES_ACTIVATION_PATTERN = re.compile(r"negate the activation", re.IGNORECASE)
_ATK_DEF_PATTERN = re.compile(r"\bATK\b|\bDEF\b")
```

```python
def classify_damage_step_category(effect_text: str) -> str | None:
    """Classify which (if any) of the two Spell-Speed-2 Damage-Step-legal
    categories this effect text falls into, per the current official
    rulebook: effects that negate an activation, or effects that alter a
    monster's ATK/DEF. Checked in this order since "negate the activation"
    is the more specific phrase -- an effect can mention ATK/DEF changes
    incidentally while its Damage-Step-relevant behavior is really the
    negation. Returns None when neither pattern is found, rather than
    guessing.
    """
    if _NEGATES_ACTIVATION_PATTERN.search(effect_text):
        return "negates_activation"
    if _ATK_DEF_PATTERN.search(effect_text):
        return "atk_def_alter"
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/effect_parser/test_parser.py -v`
Expected: PASS, entire file green (this test file has no DB dependency and no `DATABASE_URL` requirement).

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/effect_parser/parser.py tests/effect_parser/test_parser.py
git commit -m "feat(effect_parser): classify effect text into Damage-Step-legal categories"
```

---

### Task 5: Parser — `extract_usage_limit_text`

**Files:**
- Modify: `src/aijudge/effect_parser/parser.py`
- Test: `tests/effect_parser/test_parser.py`

**Interfaces:**
- Produces: `effect_parser.parser.extract_usage_limit_text(card_text: str) -> str | None`. Consumed by Task 7 (`seed.py`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/effect_parser/test_parser.py`:

```python
def test_extract_usage_limit_text_finds_a_trailing_once_per_turn_sentence():
    text = (
        "During your opponent's Main Phase (Quick Effect): You can send this "
        "card from your hand to the GY; until the end of this turn, negate "
        "the effects of 1 Effect Monster your opponent controls, also its "
        'ATK becomes 0. You can only use this effect of "Effect Veiler" once '
        "per turn."
    )
    assert extract_usage_limit_text(text) == 'You can only use this effect of "Effect Veiler" once per turn.'


def test_extract_usage_limit_text_finds_a_bare_restriction_sentence():
    text = 'You can only Special Summon "X" Monster(s) from your Extra Deck once per turn.'
    assert extract_usage_limit_text(text) == text


def test_extract_usage_limit_text_returns_none_when_absent():
    text = "You can target 1 banished monster; banish it."
    assert extract_usage_limit_text(text) is None
```

Update the top import line to:
```python
from aijudge.effect_parser.parser import classify_damage_step_category, classify_effect_type, extract_usage_limit_text, parse_psct
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/effect_parser/test_parser.py -v`
Expected: FAIL — `ImportError: cannot import name 'extract_usage_limit_text'`.

- [ ] **Step 3: Implement `extract_usage_limit_text`**

In `src/aijudge/effect_parser/parser.py`, add alongside the other module-level patterns:

```python
_USAGE_LIMIT_PATTERN = re.compile(r"You can only [^.]*\bper turn\.", re.IGNORECASE)
```

```python
def extract_usage_limit_text(card_text: str) -> str | None:
    """Extract a usage-count restriction sentence ("You can only ... per
    turn.") from raw card text, independent of `parse_psct`'s Condition/
    Cost/Effect split -- this kind of clause is a trailing sentence that
    split doesn't decompose (see Effect Veiler: it follows the semicolon-
    delimited effect clause, not inside it). Stored for reference only;
    never enforced, since this project tracks no live game state.
    """
    match = _USAGE_LIMIT_PATTERN.search(card_text)
    return match.group(0) if match else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/effect_parser/test_parser.py -v`
Expected: PASS, entire file green.

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/effect_parser/parser.py tests/effect_parser/test_parser.py
git commit -m "feat(effect_parser): extract once-per-turn usage-limit clauses from card text"
```

---

### Task 6: `review_agent` reviews the Damage Step category guess

**Files:**
- Modify: `src/aijudge/effect_parser/review_agent.py`
- Test: `tests/effect_parser/test_review_agent.py`

**Interfaces:**
- Consumes: nothing new (the caller, Task 7, supplies a `str | None`).
- Produces: `review_parsed_effect(..., damage_step_category: str | None = None)` — the parameter is included in the LLM review prompt. Existing callers that omit it keep working (default `None`), so pre-existing tests need no changes.

- [ ] **Step 1: Write the failing test**

Append to `tests/effect_parser/test_review_agent.py`:

```python
def test_damage_step_category_is_included_in_the_review_prompt():
    llm_client = MockLLMClient()
    llm_client.queue_response("0.9")

    review_parsed_effect(
        llm_client,
        raw_text="its ATK becomes 0.",
        activation_condition=None,
        cost=None,
        targeting=None,
        effect="its ATK becomes 0.",
        damage_step_category="atk_def_alter",
    )

    # MockLLMClient doesn't record the prompt text itself, only system
    # prompts -- so this test drives the call with the new parameter and
    # relies on Step 2 (it currently fails with a TypeError, proving the
    # parameter doesn't exist yet) plus Step 4 passing to confirm the
    # parameter is accepted and threaded through without error.
    assert True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/effect_parser/test_review_agent.py -v`
Expected: FAIL — `TypeError: review_parsed_effect() got an unexpected keyword argument 'damage_step_category'`.

- [ ] **Step 3: Implement**

In `src/aijudge/effect_parser/review_agent.py`:

```python
def review_parsed_effect(
    llm_client: LLMClient,
    *,
    raw_text: str,
    activation_condition: str | None,
    cost: str | None,
    targeting: str | None,
    effect: str,
    damage_step_category: str | None = None,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> ReviewResult:
    prompt = (
        "Score how accurately this structured breakdown captures the raw "
        "card text, from 0.0 to 1.0. Respond with only the number.\n\n"
        f"Raw text: {raw_text}\n\n"
        f"Activation condition: {activation_condition}\n"
        f"Cost: {cost}\n"
        f"Targeting: {targeting}\n"
        f"Effect: {effect}\n"
        f"Damage Step category: {damage_step_category}"
    )
    response = llm_client.complete(prompt)
    confidence = float(response)
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"confidence must be between 0.0 and 1.0, got {confidence!r} (raw response: {response!r})")
    return ReviewResult(confidence=confidence, auto_confirmed=confidence >= threshold)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/effect_parser/test_review_agent.py -v`
Expected: PASS, entire file green including all pre-existing tests (they omit `damage_step_category`, which defaults to `None`).

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/effect_parser/review_agent.py tests/effect_parser/test_review_agent.py
git commit -m "feat(effect_parser): review the Damage Step category guess alongside the rest of the parse"
```

---

### Task 7: Wire the two new parser functions into `seed_card`

**Files:**
- Modify: `src/aijudge/ingestion/seed.py`
- Test: `tests/ingestion/test_seed.py`

**Interfaces:**
- Consumes: `classify_damage_step_category` (Task 4), `extract_usage_limit_text` (Task 5), `review_parsed_effect(..., damage_step_category=...)` (Task 6), `insert_pending_effect(..., damage_step_category=..., usage_limit_text=...)` (Task 3).
- Produces: no new public interface — `seed_card`'s signature is unchanged; this task only changes what it stores.

- [ ] **Step 1: Write the failing test**

Append to `tests/ingestion/test_seed.py`:

```python
def test_seed_card_stores_damage_step_category_and_usage_limit_text():
    from aijudge.db.effects_repo import get_confirmed_effect
    from aijudge.ingestion.seed import seed_card
    from aijudge.llm.client import MockLLMClient

    def fake_fetch_card(name, http_get=None):
        return {
            "id": 95440946,
            "name": name,
            "type": "Effect Monster",
            "desc": (
                "During your opponent's Main Phase (Quick Effect): You can send this "
                "card from your hand to the GY; until the end of this turn, negate "
                "the effects of 1 Effect Monster your opponent controls, also its "
                'ATK becomes 0. You can only use this effect of "Effect Veiler" once '
                "per turn."
            ),
        }

    def fake_fetch_rulings(name, http_get=None):
        return []

    llm_client = MockLLMClient()
    llm_client.queue_response("0.97")

    card_id = seed_card(
        "Effect Veiler",
        llm_client=llm_client,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=fake_fetch_rulings,
    )

    confirmed_effect = get_confirmed_effect(card_id)
    assert confirmed_effect is not None
    assert confirmed_effect["damage_step_category"] == "atk_def_alter"
    assert confirmed_effect["usage_limit_text"] == 'You can only use this effect of "Effect Veiler" once per turn.'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/ingestion/test_seed.py -v`
Expected: FAIL — `assert None == "atk_def_alter"` (the new columns are never populated yet).

- [ ] **Step 3: Wire the new functions into `seed_card`**

In `src/aijudge/ingestion/seed.py`:

```python
from datetime import date, datetime
from typing import Callable

from aijudge.db.cards_repo import insert_card
from aijudge.db.effects_repo import confirm_effect, insert_pending_effect
from aijudge.db.rulings_repo import insert_ruling
from aijudge.effect_parser.parser import classify_damage_step_category, classify_effect_type, extract_usage_limit_text, parse_psct
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
        ygoprodeck_id=str(card_data["id"]),
    )

    for ruling in fetch_rulings_fn(name):
        raw_date = ruling.get("date")
        insert_ruling(
            card_id=card_id,
            ruling_text=ruling["text"],
            source="db.ygoresources",
            ruling_date=date.fromisoformat(raw_date) if raw_date else None,
        )

    effect_type = classify_effect_type(card_text, card_type=card_type)
    parsed = parse_psct(card_text)
    damage_step_category = classify_damage_step_category(parsed.effect)
    usage_limit_text = extract_usage_limit_text(card_text)

    review = review_parsed_effect(
        llm_client,
        raw_text=card_text,
        activation_condition=parsed.activation_condition,
        cost=parsed.cost,
        targeting=parsed.targeting,
        effect=parsed.effect,
        damage_step_category=damage_step_category,
    )

    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type=effect_type.value,
        effect=parsed.effect,
        activation_condition=parsed.activation_condition,
        cost=parsed.cost,
        targeting=parsed.targeting,
        has_target=(parsed.targeting is not None),
        confidence_score=review.confidence,
        damage_step_category=damage_step_category,
        usage_limit_text=usage_limit_text,
    )

    if review.auto_confirmed:
        confirm_effect(effect_id)

    return card_id


def run_seed(llm_client: LLMClient) -> list[str]:
    return [seed_card(name, llm_client=llm_client) for name in HAND_PICKED_CARDS]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/ingestion/test_seed.py -v`
Expected: PASS, entire file green including pre-existing tests (no regressions).

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/ingestion/seed.py tests/ingestion/test_seed.py
git commit -m "feat(ingestion): populate damage_step_category and usage_limit_text during seeding"
```

---

### Task 8: Preflight — `find_mentioned_card_names` (pure, fuzzy)

**Files:**
- Create: `src/aijudge/orchestration/preflight.py`
- Test: `tests/orchestration/test_preflight.py`

**Interfaces:**
- Produces: `orchestration.preflight.find_mentioned_card_names(question: str, known_names: list[str]) -> list[str]`. Pure function, no DB. Consumed by Task 9.

- [ ] **Step 1: Write the failing tests**

Create `tests/orchestration/test_preflight.py`:

```python
from aijudge.orchestration.preflight import find_mentioned_card_names


def test_finds_exact_card_name_mention():
    names = find_mentioned_card_names("Can I activate Effect Veiler here?", ["Effect Veiler", "Solemn Strike"])
    assert names == ["Effect Veiler"]


def test_finds_fuzzy_misspelled_card_name_mention():
    names = find_mentioned_card_names("Can I activate Effect Viler here?", ["Effect Veiler"])
    assert names == ["Effect Veiler"]


def test_no_match_returns_empty_list():
    names = find_mentioned_card_names("Can I attack with my dragon?", ["Effect Veiler", "Solemn Strike"])
    assert names == []


def test_short_name_does_not_false_positive_match_inside_a_longer_word():
    names = find_mentioned_card_names("I control a Gravekeeper's Spy", ["Grave"])
    assert names == []


def test_finds_multiple_mentioned_cards_in_the_order_of_known_names():
    question = "If I chain Effect Veiler to Solemn Strike, what happens?"
    names = find_mentioned_card_names(question, ["Effect Veiler", "Solemn Strike", "Called by the Grave"])
    assert names == ["Effect Veiler", "Solemn Strike"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/orchestration/test_preflight.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aijudge.orchestration.preflight'`.

- [ ] **Step 3: Implement**

Create `src/aijudge/orchestration/preflight.py`:

```python
import difflib
import re

_FUZZY_CUTOFF = 0.75


def find_mentioned_card_names(question: str, known_names: list[str]) -> list[str]:
    """Return every name in `known_names` plausibly mentioned in `question`.

    Matches an exact (case-insensitive, word-boundary) substring first, so
    a card name embedded inside an unrelated longer word never falsely
    matches. Falls back to a fuzzy comparison against every equal-length
    word-window of the question, so a slightly misspelled or incomplete
    name still matches (e.g. "Effect Viler" against "Effect Veiler").
    """
    return [name for name in known_names if _mentions_name(name, question)]


def _mentions_name(name: str, question: str) -> bool:
    pattern = r"\b" + re.escape(name.lower()) + r"\b"
    if re.search(pattern, question.lower()):
        return True
    return _fuzzy_mentions_name(name, question)


def _fuzzy_mentions_name(name: str, question: str) -> bool:
    words = question.lower().split()
    name_lower = name.lower()
    name_word_count = len(name_lower.split())
    windows = (
        " ".join(words[i : i + name_word_count])
        for i in range(len(words) - name_word_count + 1)
    )
    return any(
        difflib.SequenceMatcher(None, window, name_lower).ratio() >= _FUZZY_CUTOFF
        for window in windows
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/orchestration/test_preflight.py -v`
Expected: PASS, entire file green (no `DATABASE_URL` needed for this file).

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/orchestration/preflight.py tests/orchestration/test_preflight.py
git commit -m "feat(orchestration): fuzzy, word-boundary-safe card-name recognition in a question"
```

---

### Task 9: Preflight — `find_matched_cards` and `build_known_facts_context`

**Files:**
- Modify: `src/aijudge/db/cards_repo.py`
- Modify: `src/aijudge/orchestration/preflight.py`
- Test: `tests/db/test_cards_repo.py`
- Test: `tests/orchestration/test_preflight_db.py`

**Interfaces:**
- Consumes: `find_mentioned_card_names` (Task 8), `get_card_by_name`/`get_confirmed_effect` (existing), `is_activatable`/`spell_speed_for` (`rules_engine.models`, existing + Task 1).
- Produces: `cards_repo.list_card_names() -> list[str]`.
- Produces: `preflight.find_matched_cards(question: str) -> list[dict]` (full card dicts, as returned by `get_card_by_name`).
- Produces: `preflight.build_known_facts_context(card: dict) -> str` (empty string if the card has no confirmed effect). Both consumed by Task 10 (`cli.py`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/db/test_cards_repo.py`:

```python
def test_list_card_names_returns_every_inserted_card_name():
    from aijudge.db.cards_repo import insert_card, list_card_names

    insert_card(
        name="Effect Veiler",
        card_text="text",
        card_type="Effect Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="95440946",
    )
    insert_card(
        name="Solemn Strike",
        card_text="text",
        card_type="Counter Trap",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="40605147",
    )

    assert set(list_card_names()) == {"Effect Veiler", "Solemn Strike"}


def test_list_card_names_returns_empty_list_when_no_cards():
    from aijudge.db.cards_repo import list_card_names

    assert list_card_names() == []
```

Create `tests/orchestration/test_preflight_db.py`:

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


_EFFECT_VEILER_TEXT = (
    "During your opponent's Main Phase (Quick Effect): You can send this "
    "card from your hand to the GY; until the end of this turn, negate "
    "the effects of 1 Effect Monster your opponent controls, also its "
    'ATK becomes 0. You can only use this effect of "Effect Veiler" once '
    "per turn."
)


def test_find_matched_cards_returns_full_card_dict_for_a_mentioned_card():
    from aijudge.db.cards_repo import insert_card
    from aijudge.orchestration.preflight import find_matched_cards

    insert_card(
        name="Effect Veiler",
        card_text=_EFFECT_VEILER_TEXT,
        card_type="Effect Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="95440946",
    )

    matches = find_matched_cards("Can I activate Effect Veiler in response?")

    assert len(matches) == 1
    assert matches[0]["name"] == "Effect Veiler"


def test_find_matched_cards_returns_empty_list_when_nothing_mentioned():
    from aijudge.orchestration.preflight import find_matched_cards

    assert find_matched_cards("What happens if I attack with my dragon?") == []


def test_build_known_facts_context_includes_effect_type_and_spell_speed():
    from aijudge.db.cards_repo import get_card_by_name, insert_card
    from aijudge.db.effects_repo import confirm_effect, insert_pending_effect
    from aijudge.orchestration.preflight import build_known_facts_context

    card_id = insert_card(
        name="Effect Veiler",
        card_text=_EFFECT_VEILER_TEXT,
        card_type="Effect Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="95440946",
    )
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="quick",
        effect="negate the effects of 1 Effect Monster your opponent controls, also its ATK becomes 0.",
    )
    confirm_effect(effect_id)

    context = build_known_facts_context(get_card_by_name("Effect Veiler"))

    assert "Effect Veiler" in context
    assert "spell speed 2" in context
    assert "activatable: True" in context


def test_build_known_facts_context_is_empty_when_no_confirmed_effect():
    from aijudge.db.cards_repo import get_card_by_name, insert_card
    from aijudge.orchestration.preflight import build_known_facts_context

    insert_card(
        name="Effect Veiler",
        card_text=_EFFECT_VEILER_TEXT,
        card_type="Effect Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="95440946",
    )

    assert build_known_facts_context(get_card_by_name("Effect Veiler")) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/db/test_cards_repo.py tests/orchestration/test_preflight_db.py -v`
Expected: FAIL — `ImportError: cannot import name 'list_card_names'` and `ImportError: cannot import name 'find_matched_cards'`.

- [ ] **Step 3: Implement `list_card_names`**

In `src/aijudge/db/cards_repo.py`, add:

```python
def list_card_names() -> list[str]:
    with get_connection() as conn:
        rows = conn.execute("SELECT name FROM cards").fetchall()
    return [row[0] for row in rows]
```

- [ ] **Step 4: Implement `find_matched_cards` and `build_known_facts_context`**

Append to `src/aijudge/orchestration/preflight.py`:

```python
from aijudge.db.cards_repo import get_card_by_name, list_card_names
from aijudge.db.effects_repo import get_confirmed_effect
from aijudge.rules_engine.models import EffectType, is_activatable, spell_speed_for


def find_matched_cards(question: str) -> list[dict]:
    """Return the full card dict (as `get_card_by_name` returns it) for
    every card plausibly mentioned in `question`."""
    names = find_mentioned_card_names(question, list_card_names())
    return [get_card_by_name(name) for name in names]


def build_known_facts_context(card: dict) -> str:
    """Render a deterministic "KNOWN FACTS" block for one already-resolved
    card, from its confirmed structured effect. Returns "" if the card has
    no confirmed effect -- callers fall back to unaided LLM reasoning in
    that case, same as when no card is matched at all."""
    confirmed = get_confirmed_effect(card["id"])
    if confirmed is None:
        return ""
    effect_type = EffectType(confirmed["effect_type"])
    speed = spell_speed_for(effect_type, card_type=card["card_type"])
    return (
        "KNOWN FACTS (deterministic -- do not contradict):\n"
        f"- {card['name']}: effect type {effect_type.value}, spell speed {speed.value}, "
        f"activatable: {is_activatable(effect_type)}"
    )
```

(These go at the bottom of the file, after the two functions from Task 8 -- `difflib`/`re` imports from Task 8 stay at the top.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/db/test_cards_repo.py tests/orchestration/test_preflight_db.py tests/orchestration/test_preflight.py -v`
Expected: PASS, all three files green.

- [ ] **Step 6: Commit**

```bash
git add src/aijudge/db/cards_repo.py src/aijudge/orchestration/preflight.py tests/db/test_cards_repo.py tests/orchestration/test_preflight_db.py
git commit -m "feat(orchestration): resolve matched cards to confirmed-effect KNOWN FACTS context"
```

---

### Task 10: Wire preflight into `cli.py`, with disambiguation

**Files:**
- Modify: `src/aijudge/orchestration/clarify.py`
- Modify: `src/aijudge/cli.py`
- Test: `tests/orchestration/test_clarify.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `find_matched_cards`, `build_known_facts_context` (Task 9).
- Produces: `run_cli` gains two injectable keyword parameters, `find_matched_cards_fn` and `build_known_facts_context_fn`, defaulting to the real Task 9 functions -- mirrors the existing `fetch_card_fn`/`fetch_rulings_fn` injection pattern in `ingestion/seed.py`. A new `ClarificationItem` kind, `"disambiguate_card"`, is asked (via the existing `input_fn` prompt loop) whenever more than one card matches.

- [ ] **Step 1: Write the failing tests**

Append to `tests/orchestration/test_clarify.py`:

```python
def test_format_clarification_context_labels_disambiguate_card_items():
    items = [ClarificationItem(kind="disambiguate_card", text="Multiple cards match: Effect Veiler, Effector. Which one?")]
    answers = ["Effect Veiler"]

    context = format_clarification_context(items, answers)

    assert "Card disambiguation - Multiple cards match: Effect Veiler, Effector. Which one?: Effect Veiler" in context
```

In `tests/test_cli.py`, first update the two existing question-asking tests so they keep passing without a DB (they currently call the real, DB-touching `find_matched_cards` as soon as this task's `cli.py` change lands):

```python
def test_run_cli_answers_a_question_with_no_clarification_needed():
    printed = []
    inputs = iter(["What does Card X do?", "quit"])

    llm = MockLLMClient()
    llm.queue_response("PROCEED")
    llm.queue_response("FINAL: It does X. ||CITES: ||")

    run_cli(
        llm,
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: [],
    )

    assert "It does X." in printed


def test_run_cli_asks_clarification_questions_before_answering():
    printed = []
    inputs = iter(["Can I respond to this?", "Blue-Eyes White Dragon", "quit"])

    llm = MockLLMClient()
    llm.queue_response("CLARIFY: Which monster do you control?")
    llm.queue_response("FINAL: Yes, you can respond. ||CITES: ||")

    run_cli(
        llm,
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: [],
    )

    assert "Yes, you can respond." in printed
```

Append two new tests to `tests/test_cli.py`:

```python
def test_run_cli_disambiguates_when_multiple_cards_match():
    printed = []
    inputs = iter(["Can I chain Effect Veiler or Effector here?", "Effect Veiler", "quit"])

    llm = MockLLMClient()
    llm.queue_response("PROCEED")
    llm.queue_response("FINAL: Yes. ||CITES: ||")

    matches = [
        {"id": "1", "name": "Effect Veiler", "card_type": "Effect Monster"},
        {"id": "2", "name": "Effector", "card_type": "Effect Monster"},
    ]

    run_cli(
        llm,
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: matches,
        build_known_facts_context_fn=lambda card: f"KNOWN FACTS: {card['name']}",
    )

    assert "Yes." in printed


def test_run_cli_folds_preflight_facts_in_for_a_single_match():
    printed = []
    inputs = iter(["Can I activate Effect Veiler here?", "quit"])

    llm = MockLLMClient()
    llm.queue_response("PROCEED")
    llm.queue_response("FINAL: Yes. ||CITES: ||")

    card = {"id": "1", "name": "Effect Veiler", "card_type": "Effect Monster"}

    run_cli(
        llm,
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: [card],
        build_known_facts_context_fn=lambda c: f"KNOWN FACTS: {c['name']}",
    )

    assert "Yes." in printed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/orchestration/test_clarify.py tests/test_cli.py -v`
Expected: FAIL — the new `test_clarify.py` test fails on the wrong label ("Continuous effect status" instead of "Card disambiguation"); the `test_cli.py` tests fail with `TypeError: run_cli() got an unexpected keyword argument 'find_matched_cards_fn'`.

- [ ] **Step 3: Update `clarify.py`**

In `src/aijudge/orchestration/clarify.py`, replace `format_clarification_context`:

```python
_LABELS = {
    "clarify": "Clarification",
    "continuous_check": "Continuous effect status",
    "disambiguate_card": "Card disambiguation",
}


def format_clarification_context(items: list[ClarificationItem], answers: list[str]) -> str:
    lines = []
    for item, answer in zip(items, answers):
        label = _LABELS.get(item.kind, "Clarification")
        lines.append(f"{label} - {clarification_prompt_text(item)}: {answer}")
    return "\n".join(lines)
```

- [ ] **Step 4: Wire preflight into `run_cli`**

Replace the contents of `src/aijudge/cli.py`:

```python
from typing import Callable

from aijudge.embeddings.client import EmbeddingClient
from aijudge.llm.client import LLMClient

from .orchestration.clarify import (
    ClarificationItem,
    build_clarification_prompt,
    clarification_prompt_text,
    format_clarification_context,
    parse_clarification_response,
)
from .orchestration.loop import run_loop
from .orchestration.preflight import build_known_facts_context, find_matched_cards
from .orchestration.tools import build_tool_dispatch


def run_cli(
    llm_client: LLMClient,
    embedding_client: EmbeddingClient,
    *,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
    find_matched_cards_fn: Callable[[str], list[dict]] = find_matched_cards,
    build_known_facts_context_fn: Callable[[dict], str] = build_known_facts_context,
) -> None:
    tools = build_tool_dispatch(embedding_client)
    print_fn("AIJudge -- ask a Yu-Gi-Oh! rules question ('exit' or 'quit' to leave).")

    while True:
        try:
            question = input_fn("> ")
        except EOFError:
            break

        stripped = question.strip()
        if stripped.lower() in ("exit", "quit"):
            break
        if not stripped:
            continue

        matches = find_matched_cards_fn(stripped)
        disambiguation_items: list[ClarificationItem] = []
        if len(matches) > 1:
            names = ", ".join(match["name"] for match in matches)
            disambiguation_items.append(
                ClarificationItem(
                    kind="disambiguate_card",
                    text=f"Multiple cards match your question: {names}. Which one do you mean?",
                )
            )

        clarify_response = llm_client.complete(build_clarification_prompt(stripped))
        items = disambiguation_items + parse_clarification_response(clarify_response)
        answers = [input_fn(f"{clarification_prompt_text(item)} ") for item in items]

        preflight_context = ""
        if len(matches) == 1:
            preflight_context = build_known_facts_context_fn(matches[0])
        elif len(matches) > 1 and answers:
            chosen = next((match for match in matches if match["name"] == answers[0].strip()), None)
            if chosen is not None:
                preflight_context = build_known_facts_context_fn(chosen)

        context = format_clarification_context(items, answers)
        if preflight_context:
            context = f"{preflight_context}\n\n{context}" if context else preflight_context

        result = run_loop(stripped, llm_client=llm_client, tools=tools, clarification_context=context)
        print_fn(result.text)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/orchestration/test_clarify.py tests/test_cli.py -v`
Expected: PASS, both files green including all pre-existing tests.

Then run the full suite to confirm no other regressions:
Run: `pytest -v`
Expected: PASS (DB-dependent tests skip if `DATABASE_URL` isn't set, matching the project's normal zero-setup green state).

- [ ] **Step 6: Commit**

```bash
git add src/aijudge/orchestration/clarify.py src/aijudge/cli.py tests/orchestration/test_clarify.py tests/test_cli.py
git commit -m "feat(cli): ground reasoning in preflight-matched card facts, disambiguating on multiple matches"
```

---

### Task 11: Ingest the real rulebook

**Files:**
- Create: `src/aijudge/ingestion/rulebook_seed.py`
- Modify: `.gitignore`
- Test: `tests/ingestion/test_rulebook_seed.py`

**Interfaces:**
- Consumes: `load_rulebook_file` (existing, `ingestion/rulebook_loader.py`), `insert_chunk` (existing, `db/rulebook_repo.py`), `EmbeddingClient` (existing protocol).
- Produces: `ingestion.rulebook_seed.seed_rulebook_file(path: Path, *, embedding_client: EmbeddingClient, source: str) -> list[str]`.

- [ ] **Step 1: Write the failing test**

Create `tests/ingestion/test_rulebook_seed.py`:

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


def test_seed_rulebook_file_chunks_and_stores_every_paragraph(tmp_path):
    from aijudge.db.rulebook_repo import list_chunks
    from aijudge.embeddings.client import MockEmbeddingClient
    from aijudge.ingestion.rulebook_seed import seed_rulebook_file

    rulebook_path = tmp_path / "rulebook.txt"
    rulebook_path.write_text(
        "Priority is the ability of a player to activate a card or effect.\n\n"
        "During the Damage Step, only specific effects may be activated.",
        encoding="utf-8",
    )

    ids = seed_rulebook_file(rulebook_path, embedding_client=MockEmbeddingClient(), source="konami_rulebook")

    assert len(ids) == 1  # both short paragraphs fit under the 800-char default chunk size
    chunks = list_chunks(source="konami_rulebook")
    assert len(chunks) == 1
    assert "Damage Step" in chunks[0]["chunk_text"]


def test_seed_rulebook_file_splits_long_content_into_multiple_chunks(tmp_path):
    from aijudge.db.rulebook_repo import list_chunks
    from aijudge.embeddings.client import MockEmbeddingClient
    from aijudge.ingestion.rulebook_seed import seed_rulebook_file

    rulebook_path = tmp_path / "rulebook.txt"
    rulebook_path.write_text("A" * 500 + "\n\n" + "B" * 500, encoding="utf-8")

    ids = seed_rulebook_file(rulebook_path, embedding_client=MockEmbeddingClient(), source="konami_rulebook")

    assert len(ids) == 2
    assert len(list_chunks(source="konami_rulebook")) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/ingestion/test_rulebook_seed.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aijudge.ingestion.rulebook_seed'`.

- [ ] **Step 3: Implement**

Create `src/aijudge/ingestion/rulebook_seed.py`:

```python
from pathlib import Path

from aijudge.db.rulebook_repo import insert_chunk
from aijudge.embeddings.client import EmbeddingClient
from aijudge.ingestion.rulebook_loader import load_rulebook_file


def seed_rulebook_file(path: Path, *, embedding_client: EmbeddingClient, source: str) -> list[str]:
    chunks = load_rulebook_file(path)
    return [
        insert_chunk(chunk_text=chunk, source=source, embedding=embedding_client.embed(chunk))
        for chunk in chunks
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/ingestion/test_rulebook_seed.py -v`
Expected: PASS, both tests green.

- [ ] **Step 5: Commit the code**

```bash
git add src/aijudge/ingestion/rulebook_seed.py tests/ingestion/test_rulebook_seed.py
git commit -m "feat(ingestion): add seed_rulebook_file to populate rulebook_chunks"
```

- [ ] **Step 6: Ignore local rulebook content**

Konami's rulebook text is third-party copyrighted content and must not be committed to the repository. Append to `.gitignore`:

```
data/
```

```bash
git add .gitignore
git commit -m "chore: ignore local data directory for fetched third-party content"
```

- [ ] **Step 7: Fetch and ingest the real rulebook (manual, one-time — not a repeatable test)**

This step populates your local/dev Postgres instance with real content; it is not code and has no automated test, the same way running `run_seed` to populate the 5 hand-picked cards isn't itself unit-tested.

1. Fetch the current rulebook text from `https://www.yugioh-card.com/eu/play/tcg-rulebook/` (the official site's current-rulebook page — per the spec, prefer this over any frozen PDF snapshot so ingested content tracks current rules). Save the cleaned prose (strip navigation/footer/marketing chrome) to `data/rulebook.txt` in the project root, with a blank line between each logical section so `chunk_text`'s paragraph-based splitting works as intended.
2. Run:

```bash
python -c "
from pathlib import Path
from aijudge.embeddings.client import MockEmbeddingClient
from aijudge.ingestion.rulebook_seed import seed_rulebook_file
from aijudge.db.migrate import run_migrations

run_migrations()
ids = seed_rulebook_file(Path('data/rulebook.txt'), embedding_client=MockEmbeddingClient(), source='konami_rulebook')
print(f'inserted {len(ids)} chunks')
"
```

   Substitute `MockEmbeddingClient()` for `OpenAIEmbeddingClient()`/`OllamaEmbeddingClient()` (see `entrypoint.py`/`__main__.py` for their construction) once a real embedding provider is wired for this — using the mock here only proves ingestion mechanics, not retrieval quality.
3. Verify with a real embedding client that a Damage-Step-related query returns a result:

```python
from aijudge.db.rulebook_repo import search_chunks
results = search_chunks(embedding_client.embed("what can be activated during the Damage Step"), max_distance=0.15)
assert results  # previously always empty -- this is the gap this task closes
```

---

## Self-Review

**1. Spec coverage:**
- Component 1 (rulebook ingestion) → Task 11.
- Component 2 (preflight, fuzzy match, disambiguate) → Tasks 8, 9, 10.
- Component 3 (`get_confirmed_effects` fix, effect recognition) → explicitly out of scope, not implemented (per Global Constraints).
- Component 4a (structural activatability) → Task 1.
- Component 4b (condition-satisfaction matching) → explicitly out of scope, not implemented (per Global Constraints).
- Component 5 (Damage Step global rule + categorical tag) → Tasks 2, 3, 4, 6, 7.
- Component 6 (once-per-turn parsing, unenforced) → Tasks 3, 5, 7.
- Governing architecture principle (global law hardcoded, per-card data through ingestion+review) → reflected in every task's placement (Tasks 1–2 in `rules_engine`, Tasks 3–7 in `effect_parser`/ingestion).

**2. Placeholder scan:** No TBD/TODO markers; every step has literal code or an exact command. Task 11's Step 7 is manual by design (per spec Non-goals, content acquisition isn't a deterministic transform) but gives exact instructions, not a vague placeholder.

**3. Type consistency:** `damage_step_category: str | None` is spelled identically across `Effect` (Task 2), `insert_pending_effect`/`get_confirmed_effect` (Task 3), `classify_damage_step_category`'s return value (Task 4), and `review_parsed_effect` (Task 6). `find_matched_cards`/`build_known_facts_context_fn` signatures in Task 9 match their consumption in Task 10 exactly. `ClarificationItem(kind="disambiguate_card", ...)` is spelled identically in Tasks 10's `clarify.py` and `cli.py` changes.
