# Multi-Effect Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let ingestion produce one `card_effects_structured` row per real effect a card has (instead of always
collapsing a card's whole text into one row), and surface every confirmed effect — each annotated with its own
deterministic Damage Step legality — in the `KNOWN FACTS` block the orchestration loop already relies on.

**Architecture:** An LLM-proposed effect-boundary split, gated by a deterministic verbatim-reconstruction check
and an LLM-scored split-quality check (both falling back to today's single-effect behavior on failure), feeds
the *existing, unchanged* per-clause parsing pipeline once per proposed effect. `get_confirmed_effects` (plural)
replaces `get_confirmed_effect` end-to-end (DB → tool → confidence → preflight), and `build_known_facts_context`
renders one line per effect using the rules engine's existing `is_activatable`/`can_activate_during_damage_step`.

**Tech Stack:** Python, psycopg3 + pgvector (Postgres), pytest. No new third-party dependencies.

**Spec:** `docs/superpowers/specs/2026-08-31-multi-effect-ingestion-design.md`

## Global Constraints

- TDD: a failing test precedes implementation code in every task (project-wide convention).
- No schema changes — `card_effects_structured` already allows multiple rows per `card_id`.
- No `rules_engine` changes — `is_activatable`, `can_activate_during_damage_step`, `spell_speed_for` are reused
  exactly as they exist today.
- A bad LLM split (fails either gate) always falls back to `[card_text]` — today's existing single-effect
  behavior — never a fabricated or silently-wrong boundary.
- DB-dependent tests use the existing project pattern: `pytestmark = pytest.mark.skipif("DATABASE_URL" not in
  os.environ, ...)` at module level, plus a `setup_function` that calls `run_migrations()` and truncates the
  tables the test touches.
- Effect recognition (deciding which single effect a question is about) stays out of scope — this plan surfaces
  *all* effects' facts; picking the relevant one(s) is left to the LLM's own final-answer synthesis.

---

## File Structure

- `src/aijudge/db/effects_repo.py` — **modify**: replace `get_confirmed_effect` with `get_confirmed_effects`
  (plural, `.fetchall()`).
- `src/aijudge/effect_parser/clause_splitter.py` — **create**: `split_effect_clauses`,
  `score_split_confidence`, `resolve_effect_clauses`.
- `src/aijudge/ingestion/seed.py` — **modify**: `seed_card` loops `resolve_effect_clauses(...)`'s result through
  the existing per-clause pipeline instead of running it once over the whole `card_text`.
- `src/aijudge/orchestration/tools.py` — **modify**: `lookup_card` returns `confirmed_effects` (list).
- `src/aijudge/orchestration/confidence.py` — **modify**: `update_signals` checks `confirmed_effects` emptiness.
- `src/aijudge/orchestration/preflight.py` — **modify**: `build_known_facts_context` renders one line per
  confirmed effect, including damage-step legality.
- Test files mirror each of the above under `tests/`, following the existing 1:1 module-to-test-file convention.

---

### Task 1: `get_confirmed_effects` (plural) replaces `get_confirmed_effect`

**Files:**
- Modify: `src/aijudge/db/effects_repo.py`
- Test: `tests/db/test_effects_repo.py`

**Interfaces:**
- Produces: `effects_repo.get_confirmed_effects(card_id: str) -> list[dict]`. Consumed by Task 5 (`tools.py`)
  and Task 7 (`preflight.py`).
- Removes: `effects_repo.get_confirmed_effect` (singular) — no other task or existing caller may use it after
  this task.

- [ ] **Step 1: Write the failing tests**

Replace the whole contents of `tests/db/test_effects_repo.py` with:

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
        ygoprodeck_id="10045474",
    )


def test_pending_effect_is_not_returned_as_confirmed():
    from aijudge.db.effects_repo import get_confirmed_effects, insert_pending_effect

    card_id = _make_card_id()
    insert_pending_effect(
        card_id=card_id,
        effect_type="quick-like",
        effect="negate its effects, also, if this card is in the Graveyard...",
        targeting="Target 1 face-up monster on the field",
    )

    assert get_confirmed_effects(card_id) == []


def test_confirm_effect_makes_it_retrievable():
    from aijudge.db.effects_repo import confirm_effect, get_confirmed_effects, insert_pending_effect

    card_id = _make_card_id()
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="quick-like",
        effect="negate its effects.",
        targeting="Target 1 face-up monster on the field",
    )

    confirm_effect(effect_id)
    effects = get_confirmed_effects(card_id)

    assert len(effects) == 1
    assert effects[0]["effect_type"] == "quick-like"
    assert effects[0]["targeting"] == "Target 1 face-up monster on the field"


def test_get_confirmed_effects_returns_id_as_str():
    from aijudge.db.effects_repo import confirm_effect, get_confirmed_effects, insert_pending_effect

    card_id = _make_card_id()
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="quick-like",
        effect="negate its effects.",
        targeting="Target 1 face-up monster on the field",
    )

    confirm_effect(effect_id)
    effects = get_confirmed_effects(card_id)

    assert isinstance(effects[0]["id"], str), f"Expected id to be str, got {type(effects[0]['id'])}"
    assert effects[0]["id"] == effect_id


def test_confirmed_effects_include_has_target():
    from aijudge.db.effects_repo import confirm_effect, get_confirmed_effects, insert_pending_effect

    card_id = _make_card_id()
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="quick-like",
        effect="negate its effects.",
        targeting="Target 1 face-up monster on the field",
        has_target=True,
    )

    confirm_effect(effect_id)
    effects = get_confirmed_effects(card_id)

    assert effects[0]["has_target"] is True


def test_confirm_effect_raises_when_id_does_not_exist():
    from aijudge.db.effects_repo import confirm_effect

    with pytest.raises(ValueError):
        confirm_effect("00000000-0000-0000-0000-000000000000")


def test_confirmed_effects_include_damage_step_category_and_usage_limit_text():
    from aijudge.db.effects_repo import confirm_effect, get_confirmed_effects, insert_pending_effect

    card_id = _make_card_id()
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="quick",
        effect="its ATK becomes 0.",
        damage_step_category="atk_def_alter",
        usage_limit_text='You can only use this effect of "Effect Veiler" once per turn.',
    )

    confirm_effect(effect_id)
    effects = get_confirmed_effects(card_id)

    assert effects[0]["damage_step_category"] == "atk_def_alter"
    assert effects[0]["usage_limit_text"] == 'You can only use this effect of "Effect Veiler" once per turn.'


def test_confirmed_effects_damage_step_category_and_usage_limit_text_default_to_none():
    from aijudge.db.effects_repo import confirm_effect, get_confirmed_effects, insert_pending_effect

    card_id = _make_card_id()
    effect_id = insert_pending_effect(card_id=card_id, effect_type="ignition", effect="destroy it.")

    confirm_effect(effect_id)
    effects = get_confirmed_effects(card_id)

    assert effects[0]["damage_step_category"] is None
    assert effects[0]["usage_limit_text"] is None


def test_get_confirmed_effects_returns_every_confirmed_row_for_a_card():
    from aijudge.db.effects_repo import confirm_effect, get_confirmed_effects, insert_pending_effect

    card_id = _make_card_id()
    first_id = insert_pending_effect(card_id=card_id, effect_type="ignition", effect="destroy it.")
    second_id = insert_pending_effect(card_id=card_id, effect_type="quick", effect="negate the activation.")
    # A pending (unconfirmed) row must never be returned alongside the confirmed ones.
    insert_pending_effect(card_id=card_id, effect_type="trigger", effect="draw 1 card.")
    confirm_effect(first_id)
    confirm_effect(second_id)

    effects = get_confirmed_effects(card_id)

    assert len(effects) == 2
    assert {e["effect_type"] for e in effects} == {"ignition", "quick"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/db/test_effects_repo.py -v`
Expected: FAIL — `ImportError: cannot import name 'get_confirmed_effects'` (requires `DATABASE_URL` set and
`docker compose up -d db` running; if it isn't, every test shows SKIPPED instead — start the DB first).

- [ ] **Step 3: Implement `get_confirmed_effects`**

In `src/aijudge/db/effects_repo.py`, replace the `get_confirmed_effect` function with:

```python
def get_confirmed_effects(card_id: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, effect_type, activation_condition, cost, targeting, has_target, effect,
                   damage_step_category, usage_limit_text
            FROM card_effects_structured
            WHERE card_id = %s AND status = 'confirmed'
            """,
            (card_id,),
        ).fetchall()
    results = []
    for row in rows:
        row_list = list(row)
        row_list[0] = str(row_list[0])
        results.append(dict(zip(_EFFECT_COLUMNS, row_list)))
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/db/test_effects_repo.py -v`
Expected: PASS, all 8 tests green.

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/db/effects_repo.py tests/db/test_effects_repo.py
git commit -m "feat(db): replace get_confirmed_effect with get_confirmed_effects (plural)"
```

---

### Task 2: `clause_splitter.split_effect_clauses` — LLM-proposed split, Gate 1

**Files:**
- Create: `src/aijudge/effect_parser/clause_splitter.py`
- Test: `tests/effect_parser/test_clause_splitter.py`

**Interfaces:**
- Produces: `effect_parser.clause_splitter.split_effect_clauses(llm_client: LLMClient, card_text: str) ->
  list[str]`. Consumed by Task 3.

- [ ] **Step 1: Write the failing tests**

Create `tests/effect_parser/test_clause_splitter.py`:

```python
from aijudge.effect_parser.clause_splitter import split_effect_clauses
from aijudge.llm.client import MockLLMClient


def test_split_effect_clauses_returns_single_chunk_when_llm_echoes_text_unchanged():
    llm = MockLLMClient()
    llm.queue_response("You can target 1 banished monster; banish it.")

    result = split_effect_clauses(llm, "You can target 1 banished monster; banish it.")

    assert result == ["You can target 1 banished monster; banish it."]


def test_split_effect_clauses_parses_multiple_dash_delimited_segments():
    llm = MockLLMClient()
    llm.queue_response("Effect one.\n---\nEffect two.")

    result = split_effect_clauses(llm, "Effect one. Effect two.")

    assert result == ["Effect one.", "Effect two."]


def test_split_effect_clauses_tolerates_whitespace_differences_when_reconstructing():
    llm = MockLLMClient()
    llm.queue_response("Effect one.\n---\n  Effect two.  ")

    result = split_effect_clauses(llm, "Effect one. Effect two.")

    assert result == ["Effect one.", "Effect two."]


def test_split_effect_clauses_falls_back_to_original_text_when_reconstruction_fails():
    llm = MockLLMClient()
    llm.queue_response("Effect one.\n---\nSomething completely different that lost text.")

    result = split_effect_clauses(llm, "Effect one. Effect two.")

    assert result == ["Effect one. Effect two."]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/effect_parser/test_clause_splitter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aijudge.effect_parser.clause_splitter'`.

- [ ] **Step 3: Implement `split_effect_clauses`**

Create `src/aijudge/effect_parser/clause_splitter.py`:

```python
from aijudge.llm.client import LLMClient

_SPLIT_PROMPT_TEMPLATE = (
    "The following is the raw rules text of a Yu-Gi-Oh! Trading Card Game card. "
    "Identify its distinct, independently-activatable effects.\n\n"
    "Rules:\n"
    "- A trailing sentence that only states a usage limit (e.g. 'You can only use this "
    "effect... once per turn.') is NOT its own effect -- keep it attached to the effect "
    "it restricts.\n"
    "- A sentence that only modifies, restricts, or grants an alternate activation method "
    "for an effect already stated (such as an exception allowing activation from the hand) "
    "is NOT its own effect -- keep it attached to that effect.\n"
    "- A bulleted or enumerated list that only clarifies or elaborates a condition, cost, or "
    "effect already stated in the same sentence is NOT a separate effect -- keep it attached "
    "to that sentence.\n"
    "- If the card has only one effect, return the entire text unchanged.\n"
    "- Do not paraphrase, reword, or summarize. Every returned effect must be an exact "
    "verbatim excerpt of the original text.\n\n"
    "Separate each returned effect with a line containing exactly: ---\n\n"
    "Card text:\n{card_text}"
)


def split_effect_clauses(llm_client: LLMClient, card_text: str) -> list[str]:
    prompt = _SPLIT_PROMPT_TEMPLATE.format(card_text=card_text)
    response = llm_client.complete(prompt)
    candidates = [part.strip() for part in response.split("---")]
    candidates = [part for part in candidates if part]
    if candidates and _reconstructs(candidates, card_text):
        return candidates
    return [card_text]


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _reconstructs(candidates: list[str], card_text: str) -> bool:
    return _normalize(" ".join(candidates)) == _normalize(card_text)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/effect_parser/test_clause_splitter.py -v`
Expected: PASS, all 4 tests green (no `DATABASE_URL` needed — pure Python + `MockLLMClient`).

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/effect_parser/clause_splitter.py tests/effect_parser/test_clause_splitter.py
git commit -m "feat(effect_parser): propose effect-clause boundaries via LLM, gated by verbatim reconstruction"
```

---

### Task 3: `score_split_confidence` and `resolve_effect_clauses` — Gate 2

**Files:**
- Modify: `src/aijudge/effect_parser/clause_splitter.py`
- Test: `tests/effect_parser/test_clause_splitter.py`

**Interfaces:**
- Consumes: `split_effect_clauses` (Task 2).
- Produces: `clause_splitter.score_split_confidence(llm_client, *, card_text: str, effect_texts: list[str]) ->
  float`; `clause_splitter.resolve_effect_clauses(llm_client, card_text: str, *, threshold: float =
  review_agent.DEFAULT_CONFIDENCE_THRESHOLD) -> list[str]`. `resolve_effect_clauses` is consumed by Task 4
  (`seed_card`).

- [ ] **Step 1: Write the failing tests**

First, add `import pytest` and `resolve_effect_clauses, score_split_confidence` to the *top* of
`tests/effect_parser/test_clause_splitter.py` (don't leave a mid-file import) — its import block should read:

```python
import pytest

from aijudge.effect_parser.clause_splitter import resolve_effect_clauses, score_split_confidence, split_effect_clauses
from aijudge.llm.client import MockLLMClient
```

Then append the new tests to the bottom of the file:

```python
def test_score_split_confidence_returns_the_llm_score():
    llm = MockLLMClient()
    llm.queue_response("0.95")

    confidence = score_split_confidence(
        llm, card_text="Effect one. Effect two.", effect_texts=["Effect one.", "Effect two."]
    )

    assert confidence == pytest.approx(0.95)


def test_score_split_confidence_rejects_out_of_range_values():
    llm = MockLLMClient()
    llm.queue_response("1.5")

    with pytest.raises(ValueError):
        score_split_confidence(llm, card_text="x", effect_texts=["x"])


def test_resolve_effect_clauses_returns_single_chunk_without_scoring_when_llm_finds_one_effect():
    llm = MockLLMClient()
    llm.queue_response("Just one effect.")  # only one queued response -- scoring must not be called

    result = resolve_effect_clauses(llm, "Just one effect.")

    assert result == ["Just one effect."]


def test_resolve_effect_clauses_keeps_a_high_confidence_multi_effect_split():
    llm = MockLLMClient()
    llm.queue_response("Effect one.\n---\nEffect two.")
    llm.queue_response("0.95")

    result = resolve_effect_clauses(llm, "Effect one. Effect two.")

    assert result == ["Effect one.", "Effect two."]


def test_resolve_effect_clauses_falls_back_to_single_chunk_on_low_split_confidence():
    llm = MockLLMClient()
    llm.queue_response("Effect one.\n---\nEffect two.")
    llm.queue_response("0.4")

    result = resolve_effect_clauses(llm, "Effect one. Effect two.")

    assert result == ["Effect one. Effect two."]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/effect_parser/test_clause_splitter.py -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_effect_clauses'`.

- [ ] **Step 3: Implement `score_split_confidence` and `resolve_effect_clauses`**

Append to `src/aijudge/effect_parser/clause_splitter.py` (add the import at the top of the file):

```python
from aijudge.effect_parser.review_agent import DEFAULT_CONFIDENCE_THRESHOLD
```

```python
_SPLIT_REVIEW_PROMPT_TEMPLATE = (
    "The following is the raw rules text of a Yu-Gi-Oh! Trading Card Game card, followed by "
    "a proposed split of that text into separate, independently-activatable effects. Score "
    "how correctly the split identifies genuinely separate effects -- as opposed to "
    "incorrectly splitting one effect into pieces, or merging two effects into one -- from "
    "0.0 to 1.0. Respond with only the number.\n\n"
    "Card text:\n{card_text}\n\n"
    "Proposed effects:\n{numbered_effects}"
)


def score_split_confidence(llm_client: LLMClient, *, card_text: str, effect_texts: list[str]) -> float:
    numbered_effects = "\n".join(f"{i}. {text}" for i, text in enumerate(effect_texts, start=1))
    prompt = _SPLIT_REVIEW_PROMPT_TEMPLATE.format(card_text=card_text, numbered_effects=numbered_effects)
    response = llm_client.complete(prompt)
    confidence = float(response)
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"confidence must be between 0.0 and 1.0, got {confidence!r} (raw response: {response!r})")
    return confidence


def resolve_effect_clauses(
    llm_client: LLMClient, card_text: str, *, threshold: float = DEFAULT_CONFIDENCE_THRESHOLD
) -> list[str]:
    candidates = split_effect_clauses(llm_client, card_text)
    if len(candidates) <= 1:
        return candidates
    confidence = score_split_confidence(llm_client, card_text=card_text, effect_texts=candidates)
    if confidence < threshold:
        return [card_text]
    return candidates
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/effect_parser/test_clause_splitter.py -v`
Expected: PASS, all 9 tests green.

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/effect_parser/clause_splitter.py tests/effect_parser/test_clause_splitter.py
git commit -m "feat(effect_parser): score split quality and compose the two-gate clause resolver"
```

---

### Task 4: Wire `resolve_effect_clauses` into `seed_card`

**Files:**
- Modify: `src/aijudge/ingestion/seed.py`
- Test: `tests/ingestion/test_seed.py`

**Interfaces:**
- Consumes: `resolve_effect_clauses` (Task 3).
- Produces: no new public interface — `seed_card`'s signature is unchanged; it now inserts one
  `card_effects_structured` row per resolved effect clause instead of always exactly one.

**Important:** `seed_card` now calls `llm_client.complete()` at least once more per card than before (the split
proposal), and once more again for any card whose split isn't a single chunk (the split-quality score) — every
existing test in `tests/ingestion/test_seed.py` that queues exactly one response (`"0.97"`/`"0.3"` for review)
must now queue an additional response *first*: the LLM's split-proposal response should simply echo the card's
`desc` text unchanged, so `resolve_effect_clauses` treats it as a single effect and never calls
`score_split_confidence`.

- [ ] **Step 1: Write the failing tests**

Replace the whole contents of `tests/ingestion/test_seed.py` with:

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
    from aijudge.db.effects_repo import get_confirmed_effects
    from aijudge.db.rulings_repo import get_rulings_for_card
    from aijudge.ingestion.seed import seed_card
    from aijudge.llm.client import MockLLMClient

    desc = "You can target 1 banished monster; banish it."

    def fake_fetch_card(name, http_get=None):
        return {"id": 47355498, "name": name, "type": "Quick-Play Spell", "desc": desc}

    def fake_fetch_rulings(name, http_get=None):
        return [{"text": "Can target monsters banished this turn.", "date": "2021-01-01"}]

    llm_client = MockLLMClient()
    llm_client.queue_response(desc)  # split proposal: one effect, unchanged
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
    assert card["ygoprodeck_id"] == "47355498"

    rulings = get_rulings_for_card(card_id)
    assert len(rulings) == 1

    effects = get_confirmed_effects(card_id)
    assert len(effects) == 1
    assert effects[0]["targeting"] == "target 1 banished monster"
    assert effects[0]["has_target"] is True

    from aijudge.db.connection import get_connection

    with get_connection() as conn:
        row = conn.execute(
            "SELECT confidence_score FROM card_effects_structured WHERE id = %s",
            (effects[0]["id"],),
        ).fetchone()
    assert row[0] == pytest.approx(0.97)


def test_seed_card_leaves_low_confidence_effect_pending():
    from aijudge.db.cards_repo import get_card_by_name
    from aijudge.db.effects_repo import get_confirmed_effects
    from aijudge.ingestion.seed import seed_card
    from aijudge.llm.client import MockLLMClient

    desc = "Target 1 face-up monster; negate its effects."

    def fake_fetch_card(name, http_get=None):
        return {"id": 10045474, "name": name, "type": "Trap Card", "desc": desc}

    def fake_fetch_rulings(name, http_get=None):
        return []

    llm_client = MockLLMClient()
    llm_client.queue_response(desc)  # split proposal: one effect, unchanged
    llm_client.queue_response("0.3")  # deliberately low confidence

    card_id = seed_card(
        "Ambiguous Trap",
        llm_client=llm_client,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=fake_fetch_rulings,
    )

    assert get_card_by_name("Ambiguous Trap")["id"] == card_id
    assert get_confirmed_effects(card_id) == []


def test_seed_card_classifies_a_tuner_monster_subtype_as_a_monster_effect():
    """Real YGOPRODeck 'type' values include many monster subtypes beyond the
    six main Extra/Main Deck types (e.g. 'Tuner Monster', 'Ritual Monster').
    All of these should be treated as monsters, not fall through to
    spell/trap effect-type vocabulary."""
    from aijudge.db.cards_repo import get_card_by_name
    from aijudge.ingestion.seed import seed_card
    from aijudge.llm.client import MockLLMClient

    desc = "If this card is Normal Summoned: You can add 1 card from your Deck to your hand."

    def fake_fetch_card(name, http_get=None):
        return {"id": 97268402, "name": name, "type": "Tuner Monster", "desc": desc}

    def fake_fetch_rulings(name, http_get=None):
        return []

    llm_client = MockLLMClient()
    llm_client.queue_response(desc)  # split proposal: one effect, unchanged
    llm_client.queue_response("0.97")

    card_id = seed_card(
        "Some Tuner",
        llm_client=llm_client,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=fake_fetch_rulings,
    )

    assert get_card_by_name("Some Tuner")["id"] == card_id

    from aijudge.db.connection import get_connection

    with get_connection() as conn:
        row = conn.execute(
            "SELECT effect_type FROM card_effects_structured WHERE card_id = %s",
            (card_id,),
        ).fetchone()
    assert row[0] == "trigger"


def test_seed_card_stores_damage_step_category_and_usage_limit_text():
    from aijudge.db.effects_repo import get_confirmed_effects
    from aijudge.ingestion.seed import seed_card
    from aijudge.llm.client import MockLLMClient

    desc = (
        "During your opponent's Main Phase (Quick Effect): You can send this "
        "card from your hand to the GY; until the end of this turn, negate "
        "the effects of 1 Effect Monster your opponent controls, also its "
        'ATK becomes 0. You can only use this effect of "Effect Veiler" once '
        "per turn."
    )

    def fake_fetch_card(name, http_get=None):
        return {"id": 95440946, "name": name, "type": "Effect Monster", "desc": desc}

    def fake_fetch_rulings(name, http_get=None):
        return []

    llm_client = MockLLMClient()
    llm_client.queue_response(desc)  # split proposal: one effect, unchanged
    llm_client.queue_response("0.97")

    card_id = seed_card(
        "Effect Veiler",
        llm_client=llm_client,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=fake_fetch_rulings,
    )

    effects = get_confirmed_effects(card_id)
    assert len(effects) == 1
    assert effects[0]["damage_step_category"] == "atk_def_alter"
    assert effects[0]["usage_limit_text"] == 'You can only use this effect of "Effect Veiler" once per turn.'


def test_seed_card_creates_one_row_per_effect_for_a_multi_effect_card():
    from aijudge.db.connection import get_connection
    from aijudge.ingestion.seed import seed_card
    from aijudge.llm.client import MockLLMClient

    effect_1 = "Once per turn: You can target 1 card on the field; destroy it."
    effect_2 = (
        'Once while face-up on the field, when a card or effect is activated (Quick Effect): '
        "You can negate the activation, and if you do, destroy that card. "
        'You can only use the previous effect of "Baronne de Fleur" once per turn.'
    )
    effect_3 = (
        "Once per turn, during the Standby Phase: You can target 1 Level 9 or lower monster "
        "in your GY; return this card to the Extra Deck, and if you do, Special Summon that monster."
    )
    desc = f"{effect_1} {effect_2} {effect_3}"

    def fake_fetch_card(name, http_get=None):
        return {"id": 84812061, "name": name, "type": "Synchro Monster", "desc": desc}

    def fake_fetch_rulings(name, http_get=None):
        return []

    llm_client = MockLLMClient()
    llm_client.queue_response(f"{effect_1}\n---\n{effect_2}\n---\n{effect_3}")
    llm_client.queue_response("0.95")  # split-quality confidence
    llm_client.queue_response("0.97")  # review confidence for effect 1
    llm_client.queue_response("0.97")  # review confidence for effect 2
    llm_client.queue_response("0.97")  # review confidence for effect 3

    card_id = seed_card(
        "Baronne de Fleur",
        llm_client=llm_client,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=fake_fetch_rulings,
    )

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT effect_type, damage_step_category, status FROM card_effects_structured WHERE card_id = %s",
            (card_id,),
        ).fetchall()

    assert len(rows) == 3
    assert all(row[2] == "confirmed" for row in rows)
    assert {row[0] for row in rows} == {"ignition", "quick"}
    negates_activation_rows = [row for row in rows if row[1] == "negates_activation"]
    assert len(negates_activation_rows) == 1
    assert negates_activation_rows[0][0] == "quick"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/ingestion/test_seed.py -v`
Expected: FAIL — `AssertionError: MockLLMClient.complete called with no queued response` on the existing tests
(they now need the extra split-proposal response), and the new multi-effect test fails since `seed_card`
doesn't call `resolve_effect_clauses` yet (only one row gets created instead of three).

- [ ] **Step 3: Wire `resolve_effect_clauses` into `seed_card`**

Replace the whole contents of `src/aijudge/ingestion/seed.py` with:

```python
from datetime import date, datetime
from typing import Callable

from aijudge.db.cards_repo import insert_card
from aijudge.db.effects_repo import confirm_effect, insert_pending_effect
from aijudge.db.rulings_repo import insert_ruling
from aijudge.effect_parser.clause_splitter import resolve_effect_clauses
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
    "Baronne de Fleur",
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

    effect_texts = resolve_effect_clauses(llm_client, card_text)

    for effect_text in effect_texts:
        effect_type = classify_effect_type(effect_text, card_type=card_type)
        parsed = parse_psct(effect_text)
        damage_step_category = classify_damage_step_category(
            parsed.effect,
            activation_condition=parsed.activation_condition,
            effect_type=effect_type,
        )
        usage_limit_text = extract_usage_limit_text(effect_text)

        review = review_parsed_effect(
            llm_client,
            raw_text=effect_text,
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
Expected: PASS, all 5 tests green.

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/ingestion/seed.py tests/ingestion/test_seed.py
git commit -m "feat(ingestion): seed one card_effects_structured row per resolved effect clause"
```

---

### Task 5: `tools.lookup_card` returns `confirmed_effects` (plural)

**Files:**
- Modify: `src/aijudge/orchestration/tools.py`
- Test: `tests/orchestration/test_tools_db.py`

**Interfaces:**
- Consumes: `get_confirmed_effects` (Task 1).
- Produces: `lookup_card(args)` result dict now has `"confirmed_effects": list[dict]` instead of
  `"confirmed_effect": dict | None`. Consumed by Task 6 (`confidence.py`).

- [ ] **Step 1: Write the failing tests**

In `tests/orchestration/test_tools_db.py`, replace the two `lookup_card` tests:

```python
def test_lookup_card_returns_card_text_and_not_found_flag():
    from aijudge.db.cards_repo import insert_card
    from aijudge.orchestration.tools import lookup_card

    insert_card(
        name="Ash Blossom & Joyous Spring",
        card_text="You can only use each of the following effects...",
        card_type="Effect Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="14558127",
    )

    result = lookup_card({"name": "Ash Blossom & Joyous Spring"})
    assert result["found"] is True
    assert result["card_text"].startswith("You can only use")
    assert result["confirmed_effects"] == []

    missing = lookup_card({"name": "Nonexistent Card"})
    assert missing == {"found": False}


def test_lookup_card_includes_confirmed_effects_when_present():
    from aijudge.db.cards_repo import insert_card
    from aijudge.db.effects_repo import confirm_effect, insert_pending_effect
    from aijudge.orchestration.tools import lookup_card

    card_id = insert_card(
        name="Effect Veiler",
        card_text="During your opponent's Main Phase (Quick Effect): ...",
        card_type="Effect Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="95440946",
    )
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="quick",
        effect="negate that face-up monster's effects",
        activation_condition="During your opponent's Main Phase",
    )
    confirm_effect(effect_id)

    result = lookup_card({"name": "Effect Veiler"})
    assert len(result["confirmed_effects"]) == 1
    assert result["confirmed_effects"][0]["effect_type"] == "quick"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/orchestration/test_tools_db.py -v`
Expected: FAIL — `KeyError: 'confirmed_effects'` (the tool still returns `confirmed_effect`).

- [ ] **Step 3: Update `lookup_card`**

In `src/aijudge/orchestration/tools.py`, update the import and the function:

```python
from aijudge.db.effects_repo import get_confirmed_effects
```

```python
def lookup_card(args: dict) -> dict:
    card = get_card_by_name(args["name"])
    if card is None:
        return {"found": False}
    confirmed_effects = get_confirmed_effects(card["id"])
    return {
        "found": True,
        "id": card["id"],
        "name": card["name"],
        "card_text": card["card_text"],
        "card_type": card["card_type"],
        "confirmed_effects": confirmed_effects,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/orchestration/test_tools_db.py -v`
Expected: PASS, all 6 tests green.

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/orchestration/tools.py tests/orchestration/test_tools_db.py
git commit -m "feat(orchestration): lookup_card returns confirmed_effects (plural)"
```

---

### Task 6: `confidence.py` adapts to the plural key, sweep test fixtures

**Files:**
- Modify: `src/aijudge/orchestration/confidence.py`
- Test: `tests/orchestration/test_confidence.py`
- Test: `tests/orchestration/test_loop.py`
- Test: `tests/api/test_app.py`

**Interfaces:**
- Consumes: the `confirmed_effects` shape produced by Task 5.
- Produces: no new interface — `update_signals`'s signature is unchanged; only which key/shape it reads from a
  `lookup_card` result changes.

- [ ] **Step 1: Write the failing tests**

In `tests/orchestration/test_confidence.py`, apply these exact replacements:

```python
# was: update_signals(state, "lookup_card", {"found": True, "id": "abc", "confirmed_effect": {"effect": "..."}})
update_signals(state, "lookup_card", {"found": True, "id": "abc", "confirmed_effects": [{"effect": "..."}]})
```
(in `test_update_signals_tracks_found_card_id` and `test_update_signals_indexes_card_citation_label_and_text`
— the latter's dict also keeps its other keys `name`/`card_text` unchanged, only the `confirmed_effect`/
`confirmed_effects` key changes)

```python
# was: update_signals(state, "lookup_card", {"found": True, "id": "abc", "confirmed_effect": None})
update_signals(state, "lookup_card", {"found": True, "id": "abc", "confirmed_effects": []})
```
(in `test_update_signals_flags_missing_structured_effect` and
`test_update_signals_indexes_card_citation_with_missing_optional_fields`)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/orchestration/test_confidence.py -v`
Expected: FAIL — `test_update_signals_tracks_found_card_id` and
`test_update_signals_indexes_card_citation_label_and_text` now fail with
`assert state.missing_structured_effect is False` → `True` (since `update_signals` still reads the old key,
which is now always absent, so it defaults to "missing").

- [ ] **Step 3: Update `update_signals`**

In `src/aijudge/orchestration/confidence.py`, change:

```python
            if result.get("confirmed_effect") is None:
                state.missing_structured_effect = True
```

to:

```python
            if not result.get("confirmed_effects"):
                state.missing_structured_effect = True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/orchestration/test_confidence.py -v`
Expected: PASS, all 11 tests green.

- [ ] **Step 5: Sweep the same key rename through `test_loop.py` and `test_app.py`**

These two files build their own stub `lookup_card` implementations (not the real one Task 5 changed), so they
still use the old key and must be updated by hand, or `run_loop`'s confidence scoring will now see every one of
these stub results as "missing structured effect" and escalate instead of answering.

In `tests/orchestration/test_loop.py`, apply these exact replacements (7 occurrences):

```python
# line ~22 and ~206:
# was: tools = {"lookup_card": lambda args: {"found": True, "id": "abc123", "confirmed_effect": {"effect": "..."}}}
tools = {"lookup_card": lambda args: {"found": True, "id": "abc123", "confirmed_effects": [{"effect": "..."}]}}

# line ~90:
# was: tools = {"lookup_card": lambda args: {"found": True, "id": "abc123", "confirmed_effect": None}}
tools = {"lookup_card": lambda args: {"found": True, "id": "abc123", "confirmed_effects": []}}

# line ~104:
# was: return {"found": True, "id": "abc123", "confirmed_effect": {"effect": "..."}, "name": args["name"]}
return {"found": True, "id": "abc123", "confirmed_effects": [{"effect": "..."}], "name": args["name"]}

# line ~117:
# was: return {"found": True, "id": "abc123", "confirmed_effect": None, "name": args["name"]}
return {"found": True, "id": "abc123", "confirmed_effects": [], "name": args["name"]}

# lines ~135, ~180, ~188 (inside larger lookup_card dicts, e.g. the Ash Blossom / Card Z / Card A fixtures):
# was: "confirmed_effect": {"effect": "..."},
"confirmed_effects": [{"effect": "..."}],
```

In `tests/api/test_app.py`, apply the same replacement (1 occurrence, inside
`test_post_questions_serializes_citation_content_without_leaking_raw_ids`'s `stub_tools["lookup_card"]` dict):

```python
# was: "confirmed_effect": {"effect": "..."},
"confirmed_effects": [{"effect": "..."}],
```

- [ ] **Step 6: Run the full orchestration and API test suites to verify they pass**

Run: `pytest tests/orchestration/test_loop.py tests/api/test_app.py -v`
Expected: PASS, no regressions (these tests were passing before this task only because the old
`"confirmed_effect"` key happened to still exist; verify none of them now fail with
`result.kind == "escalate"` where `"answer"` is expected).

- [ ] **Step 7: Commit**

```bash
git add src/aijudge/orchestration/confidence.py tests/orchestration/test_confidence.py tests/orchestration/test_loop.py tests/api/test_app.py
git commit -m "fix(orchestration): confidence scoring reads confirmed_effects (plural)"
```

---

### Task 7: `preflight.build_known_facts_context` — every effect, with Damage Step legality

**Files:**
- Modify: `src/aijudge/orchestration/preflight.py`
- Test: `tests/orchestration/test_preflight_db.py`

**Interfaces:**
- Consumes: `get_confirmed_effects` (Task 1), `rules_engine.models.Effect`/`EffectType`/`is_activatable`/
  `spell_speed_for` (existing), `rules_engine.priority.can_activate_during_damage_step` (existing).
- Produces: no new public interface — `build_known_facts_context(card)`'s signature is unchanged; it now
  renders one line per confirmed effect instead of at most one.

- [ ] **Step 1: Write the failing test**

Append to `tests/orchestration/test_preflight_db.py`:

```python
def test_build_known_facts_context_covers_every_confirmed_effect_with_damage_step_legality():
    from aijudge.db.cards_repo import get_card_by_name, insert_card
    from aijudge.db.effects_repo import confirm_effect, insert_pending_effect
    from aijudge.orchestration.preflight import build_known_facts_context

    card_id = insert_card(
        name="Baronne de Fleur",
        card_text="Once per turn: ... Once while face-up on the field, when a card or effect is activated (Quick Effect): ...",
        card_type="Synchro Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="84812061",
    )
    ignition_id = insert_pending_effect(
        card_id=card_id,
        effect_type="ignition",
        effect="destroy it.",
        activation_condition="Once per turn",
    )
    confirm_effect(ignition_id)
    quick_id = insert_pending_effect(
        card_id=card_id,
        effect_type="quick",
        effect="You can negate the activation, and if you do, destroy that card.",
        activation_condition="Once while face-up on the field, when a card or effect is activated (Quick Effect)",
        damage_step_category="negates_activation",
    )
    confirm_effect(quick_id)

    context = build_known_facts_context(get_card_by_name("Baronne de Fleur"))
    lines = context.splitlines()

    assert len(lines) == 3  # header + 2 effect lines
    ignition_line = next(line for line in lines if "effect type ignition" in line)
    quick_line = next(line for line in lines if "effect type quick" in line)
    assert "damage-step legal: False" in ignition_line
    assert "damage-step legal: True" in quick_line
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/orchestration/test_preflight_db.py -v`
Expected: FAIL — `StopIteration` (today's `build_known_facts_context` only ever renders one effect line, and
has no `damage-step legal` text at all).

- [ ] **Step 3: Implement**

Replace `build_known_facts_context` (and its imports) in `src/aijudge/orchestration/preflight.py`:

```python
from aijudge.db.cards_repo import get_card_by_name, list_card_names
from aijudge.db.effects_repo import get_confirmed_effects
from aijudge.rules_engine.models import Effect, EffectType, is_activatable, spell_speed_for
from aijudge.rules_engine.priority import can_activate_during_damage_step


def find_matched_cards(question: str) -> list[dict]:
    """Return the full card dict (as `get_card_by_name` returns it) for
    every card plausibly mentioned in `question`."""
    names = find_mentioned_card_names(question, list_card_names())
    return [get_card_by_name(name) for name in names]


def build_known_facts_context(card: dict) -> str:
    """Render a deterministic "KNOWN FACTS" block covering every one of a
    card's confirmed effects -- not just one -- so a question about any of
    them can be grounded. Each line's facts (effect type, spell speed,
    activatable, Damage Step legality) come entirely from existing
    `rules_engine` functions; nothing here interprets the question. Returns
    "" if the card has no confirmed effects at all -- callers fall back to
    unaided LLM reasoning in that case, same as before."""
    confirmed_effects = get_confirmed_effects(card["id"])
    if not confirmed_effects:
        return ""
    lines = ["KNOWN FACTS (deterministic -- do not contradict):"]
    for index, confirmed in enumerate(confirmed_effects, start=1):
        effect_type = EffectType(confirmed["effect_type"])
        speed = spell_speed_for(effect_type, card_type=card["card_type"])
        effect = Effect(
            card_id=card["id"],
            card_name=card["name"],
            effect_type=effect_type,
            controller="unknown",
            spell_speed=speed,
            damage_step_category=confirmed.get("damage_step_category"),
        )
        line = (
            f"- {card['name']}, effect {index}: effect type {effect_type.value}, spell speed {speed.value}, "
            f"activatable: {is_activatable(effect_type)}, "
            f"damage-step legal: {can_activate_during_damage_step(effect)}, "
            f"effect: \"{confirmed['effect']}\""
        )
        if confirmed.get("activation_condition") is not None:
            line += f", activation condition: {confirmed['activation_condition']}"
        if confirmed.get("damage_step_category") is not None:
            line += f", damage step category: {confirmed['damage_step_category']}"
        if confirmed.get("usage_limit_text") is not None:
            line += f", usage limit: {confirmed['usage_limit_text']}"
        lines.append(line)
    return "\n".join(lines)
```

(`find_mentioned_card_names`/`_mentions_name`/`_fuzzy_mentions_name` above this in the file are unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/orchestration/test_preflight_db.py -v`
Expected: PASS, all 6 tests green (the 4 pre-existing single-effect tests still pass unchanged, since each of
them only ever confirms one effect and their assertions are substring checks that still hold against the new
per-effect line format).

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/orchestration/preflight.py tests/orchestration/test_preflight_db.py
git commit -m "feat(orchestration): render every confirmed effect's Damage Step legality in KNOWN FACTS"
```

---

### Task 8: Full-suite verification

**Files:** none (verification only).

- [ ] **Step 1: Run the full test suite**

Run: `pytest -q`
Expected: PASS, all tests green (DB-dependent tests require `DATABASE_URL` set and `docker compose up -d db`
running -- confirm this before treating a SKIPPED-heavy run as a full pass).

- [ ] **Step 2: Update `CLAUDE.md`**

In the `orchestration/` bullet's `preflight.py` description and the `ingestion/` bullet's `seed.py` description,
note that effects are now multi-valued (`get_confirmed_effects`, one row per resolved clause via
`clause_splitter.resolve_effect_clauses`) and that `KNOWN FACTS` includes per-effect Damage Step legality.
Update the `db/` bullet's mention of `get_confirmed_effect` to `get_confirmed_effects`.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document multi-effect ingestion and per-effect KNOWN FACTS"
```
