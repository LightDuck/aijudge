# Effect Parser Deterministic Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the LLM-driven effect-clause segmentation in `ingestion/seed.py` with deterministic PSCT-grammar rules, add a printing-eligibility gate so pre-PSCT card text never runs through those rules, and add first-class handling for Extra Deck material lines and multi-clause usage-limit restrictions.

**Architecture:** Three new pure-Python modules (`ingestion/printing_eligibility.py`, `effect_parser/sentence_splitter.py`, `effect_parser/usage_limit.py`) sit alongside the existing `effect_parser/parser.py`. `effect_parser/clause_splitter.py`'s `resolve_effect_clauses` is rewritten to call the new deterministic segmentation instead of an LLM call, while still using the LLM for confidence verification and for the one case that's genuinely ambiguous (bare "these effects" scope). `ingestion/seed.py:seed_card` is rewired to call the eligibility gate and material extraction before segmentation, and to fan out resolved usage-limit text across every clause it scopes.

**Tech Stack:** Python 3, pytest, psycopg3 (DB layer only touched for one new column), no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-03-effect-parser-deterministic-rules-design.md`

## Global Constraints

- PSCT cutoff date: `2011-07-08` (exact value from spec §1).
- `DEFAULT_CONFIDENCE_THRESHOLD = 0.75` (existing, `effect_parser/review_agent.py:5` — do not change).
- No backwards-compatibility shims: `clause_splitter.split_effect_clauses` (the LLM-based segmenter) and its helpers are deleted, not deprecated, once nothing calls them (spec §3, "the LLM's role narrows... replacing the LLM as the segmentation engine"). `cards.card_materials` is deleted, not deprecated (per explicit ruling: the old effect-table-row-free mechanism is made unusable, not kept as a dead option).
- Every new grammar rule is tested against real card text, not synthetic examples, reusing the exact fixtures from the spec's "Worked examples" section (Tearlaments Rulkallos, Floowandereeze & Empen, Gem-Knight Pearl, Elemental HERO Mudballman) plus Artmage Power Patron, traced separately during design review.
- TDD throughout: failing test before implementation code, every task.

---

## File Structure

**New files:**
- `src/aijudge/ingestion/printing_eligibility.py` — PSCT cutoff constant, eligibility check, `cardsets.php` fetch.
- `src/aijudge/effect_parser/sentence_splitter.py` — sentence tokenizer, Card Material extraction.
- `src/aijudge/effect_parser/usage_limit.py` — usage-limit selector-form grammar, scope resolution, LLM concurrence for the ambiguous case.
- `tests/ingestion/test_printing_eligibility.py`
- `tests/effect_parser/test_sentence_splitter.py`
- `tests/effect_parser/test_usage_limit.py`

**Modified files:**
- `src/aijudge/rules_engine/models.py` — two new `EffectType` values.
- `src/aijudge/effect_parser/parser.py` — widen `_CARD_MOVED_TRIGGER_PATTERN` self-reference; add Summoning Condition detection to `classify_effect_type`.
- `src/aijudge/effect_parser/clause_splitter.py` — `resolve_effect_clauses` rewritten to use deterministic segmentation; LLM-based `split_effect_clauses`/`_reconstructs`/`_normalize`/`_SPLIT_PROMPT_TEMPLATE` deleted.
- `src/aijudge/effect_parser/review_agent.py` — `review_parsed_effect` gains an optional `other_effects` context parameter.
- `src/aijudge/db/schema.sql` — add `cards.deterministic_parse_eligible`; drop `cards.card_materials`.
- `src/aijudge/db/cards_repo.py` — `insert_card` gains `deterministic_parse_eligible`, loses `card_materials`; all `SELECT`s and `_CARD_COLUMNS` updated accordingly.
- `src/aijudge/orchestration/preflight.py` — `build_known_facts_context` renders `CARD_MATERIAL`/`SUMMONING_CONDITION` rows distinctly.
- `src/aijudge/ingestion/seed.py` — `seed_card` rewired to the new pipeline order.
- `tests/rules_engine/test_models.py`, `tests/effect_parser/test_parser.py`, `tests/effect_parser/test_clause_splitter.py`, `tests/effect_parser/test_review_agent.py`, `tests/db/test_cards_repo.py`, `tests/orchestration/test_preflight.py`, `tests/ingestion/test_seed.py` — extended for the above.

---

### Task 1: `EffectType.CARD_MATERIAL` and `EffectType.SUMMONING_CONDITION`

**Files:**
- Modify: `src/aijudge/rules_engine/models.py`
- Test: `tests/rules_engine/test_models.py`

**Interfaces:**
- Produces: `EffectType.CARD_MATERIAL` (value `"card_material"`), `EffectType.SUMMONING_CONDITION` (value `"summoning_condition"`), both excluded from `is_activatable()`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/rules_engine/test_models.py`:

```python
def test_card_material_is_not_activatable():
    from aijudge.rules_engine.models import EffectType, is_activatable

    assert is_activatable(EffectType.CARD_MATERIAL) is False


def test_summoning_condition_is_not_activatable():
    from aijudge.rules_engine.models import EffectType, is_activatable

    assert is_activatable(EffectType.SUMMONING_CONDITION) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/rules_engine/test_models.py -k "card_material or summoning_condition" -v`
Expected: FAIL with `AttributeError: CARD_MATERIAL`

- [ ] **Step 3: Implement**

In `src/aijudge/rules_engine/models.py`, extend the enum and the non-activatable set:

```python
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
    CARD_MATERIAL = "card_material"
    SUMMONING_CONDITION = "summoning_condition"
```

```python
_NON_ACTIVATABLE_EFFECT_TYPES = {
    EffectType.CONTINUOUS,
    EffectType.CONDITION,
    EffectType.CARD_MATERIAL,
    EffectType.SUMMONING_CONDITION,
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/rules_engine/test_models.py -v`
Expected: PASS, all tests including pre-existing ones.

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/rules_engine/models.py tests/rules_engine/test_models.py
git commit -m "feat(rules_engine): add CARD_MATERIAL and SUMMONING_CONDITION effect types"
```

---

### Task 2: Printing-eligibility check

**Files:**
- Create: `src/aijudge/ingestion/printing_eligibility.py`
- Test: `tests/ingestion/test_printing_eligibility.py`

**Interfaces:**
- Produces: `PSCT_CUTOFF_DATE: date`, `is_deterministic_parse_eligible(card_sets: list[dict], sets_index: dict[str, date]) -> bool`.

- [ ] **Step 1: Write the failing tests**

Create `tests/ingestion/test_printing_eligibility.py`:

```python
from datetime import date


def test_eligible_via_original_printing():
    from aijudge.ingestion.printing_eligibility import is_deterministic_parse_eligible

    card_sets = [{"set_name": "Darkwing Blast"}]
    sets_index = {"Darkwing Blast": date(2022, 10, 20)}

    assert is_deterministic_parse_eligible(card_sets, sets_index) is True


def test_eligible_via_reprint_only():
    """Elemental HERO Mudballman: original 2006 printing predates the
    cutoff, but a 2011-10-04 reprint doesn't."""
    from aijudge.ingestion.printing_eligibility import is_deterministic_parse_eligible

    card_sets = [
        {"set_name": "McDonald's Promotional Cards 2"},
        {"set_name": "Legendary Collection 2"},
        {"set_name": "Ra Yellow Mega Pack"},
    ]
    sets_index = {
        "McDonald's Promotional Cards 2": date(2006, 12, 22),
        "Legendary Collection 2": date(2011, 10, 4),
        "Ra Yellow Mega Pack": date(2012, 2, 17),
    }

    assert is_deterministic_parse_eligible(card_sets, sets_index) is True


def test_ineligible_when_every_printing_predates_cutoff():
    from aijudge.ingestion.printing_eligibility import is_deterministic_parse_eligible

    card_sets = [{"set_name": "Old Set"}]
    sets_index = {"Old Set": date(2005, 1, 1)}

    assert is_deterministic_parse_eligible(card_sets, sets_index) is False


def test_ineligible_at_exact_cutoff_minus_one_day():
    from aijudge.ingestion.printing_eligibility import is_deterministic_parse_eligible

    card_sets = [{"set_name": "Edge Set"}]
    sets_index = {"Edge Set": date(2011, 7, 7)}

    assert is_deterministic_parse_eligible(card_sets, sets_index) is False


def test_eligible_at_exact_cutoff_date():
    from aijudge.ingestion.printing_eligibility import is_deterministic_parse_eligible

    card_sets = [{"set_name": "Cutoff Set"}]
    sets_index = {"Cutoff Set": date(2011, 7, 8)}

    assert is_deterministic_parse_eligible(card_sets, sets_index) is True


def test_ineligible_when_set_missing_from_index():
    from aijudge.ingestion.printing_eligibility import is_deterministic_parse_eligible

    assert is_deterministic_parse_eligible([{"set_name": "Unknown Set"}], {}) is False


def test_ineligible_with_no_card_sets():
    from aijudge.ingestion.printing_eligibility import is_deterministic_parse_eligible

    assert is_deterministic_parse_eligible([], {"Some Set": date(2020, 1, 1)}) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/ingestion/test_printing_eligibility.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aijudge.ingestion.printing_eligibility'`

- [ ] **Step 3: Implement**

Create `src/aijudge/ingestion/printing_eligibility.py`:

```python
from datetime import date

PSCT_CUTOFF_DATE = date(2011, 7, 8)


def is_deterministic_parse_eligible(card_sets: list[dict], sets_index: dict[str, date]) -> bool:
    """Whether any printing of this card is dated on/after PSCT_CUTOFF_DATE.

    Checks every entry in `card_sets` (as returned by YGOPRODeck's
    cardinfo.php), not just the first -- a card's original printing can
    predate PSCT while a later reprint brings its text current (see
    Elemental HERO Mudballman in the design spec's worked examples).
    """
    for card_set in card_sets:
        set_name = card_set.get("set_name")
        if set_name is None:
            continue
        printed_date = sets_index.get(set_name)
        if printed_date is not None and printed_date >= PSCT_CUTOFF_DATE:
            return True
    return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/ingestion/test_printing_eligibility.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/ingestion/printing_eligibility.py tests/ingestion/test_printing_eligibility.py
git commit -m "feat(ingestion): add printing-eligibility check for PSCT cutoff"
```

---

### Task 3: Fetch the sets index from `cardsets.php`

**Files:**
- Modify: `src/aijudge/ingestion/printing_eligibility.py`
- Test: `tests/ingestion/test_printing_eligibility.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `CARDSETS_API_URL: str`, `fetch_sets_index(*, http_get: Callable[..., requests.Response] = requests.get) -> dict[str, date]`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/ingestion/test_printing_eligibility.py`:

```python
class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_fetch_sets_index_builds_name_to_date_map():
    from aijudge.ingestion.printing_eligibility import fetch_sets_index

    payload = [
        {"set_name": "Legendary Collection 2", "set_code": "LCGX", "tcg_date": "2011-10-04"},
        {"set_name": "Ra Yellow Mega Pack", "set_code": "RYMP", "tcg_date": "2012-02-17"},
    ]
    calls = []

    def fake_http_get(url, timeout=None):
        calls.append(url)
        return _FakeResponse(payload)

    index = fetch_sets_index(http_get=fake_http_get)

    assert index == {
        "Legendary Collection 2": date(2011, 10, 4),
        "Ra Yellow Mega Pack": date(2012, 2, 17),
    }
    assert calls == ["https://db.ygoprodeck.com/api/v7/cardsets.php"]


def test_fetch_sets_index_skips_rows_missing_tcg_date():
    from aijudge.ingestion.printing_eligibility import fetch_sets_index

    payload = [
        {"set_name": "OCG-Only Set", "set_code": "OCG1"},
        {"set_name": "Dated Set", "set_code": "DS1", "tcg_date": "2015-05-05"},
    ]

    index = fetch_sets_index(http_get=lambda url, timeout=None: _FakeResponse(payload))

    assert index == {"Dated Set": date(2015, 5, 5)}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/ingestion/test_printing_eligibility.py -k fetch_sets_index -v`
Expected: FAIL with `ImportError: cannot import name 'fetch_sets_index'`

- [ ] **Step 3: Implement**

Add to `src/aijudge/ingestion/printing_eligibility.py`:

```python
from typing import Callable

import requests

CARDSETS_API_URL = "https://db.ygoprodeck.com/api/v7/cardsets.php"


def fetch_sets_index(*, http_get: Callable[..., "requests.Response"] = requests.get) -> dict[str, date]:
    """Fetch YGOPRODeck's full set catalog once and index it by set_name ->
    tcg_date. Meant to be called once per ingestion run (not once per card)
    and reused, since this is a large, slowly-changing catalog."""
    response = http_get(CARDSETS_API_URL, timeout=10)
    response.raise_for_status()
    index: dict[str, date] = {}
    for row in response.json():
        set_name = row.get("set_name")
        tcg_date = row.get("tcg_date")
        if set_name and tcg_date:
            index[set_name] = date.fromisoformat(tcg_date)
    return index
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/ingestion/test_printing_eligibility.py -v`
Expected: PASS, 9 tests.

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/ingestion/printing_eligibility.py tests/ingestion/test_printing_eligibility.py
git commit -m "feat(ingestion): fetch YGOPRODeck cardsets.php into a set-date index"
```

---

### Task 4: Sentence tokenizer

**Files:**
- Create: `src/aijudge/effect_parser/sentence_splitter.py`
- Test: `tests/effect_parser/test_sentence_splitter.py`

**Interfaces:**
- Produces: `split_sentences(text: str) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/effect_parser/test_sentence_splitter.py`. Fixtures are real card text traced during design.

```python
def test_splits_four_sentences_tearlaments_rulkallos_remainder():
    from aijudge.effect_parser.sentence_splitter import split_sentences

    text = (
        'Other Aqua monsters you control cannot be destroyed by battle. You can only use '
        'each of the following effects of "Tearlaments Rulkallos" once per turn. When your '
        'opponent activates a card or effect that includes an effect that Special Summons a '
        'monster(s) (Quick Effect): You can negate the activation, and if you do, destroy '
        'it, then, send 1 "Tearlaments" card from your hand or face-up field to the GY. If '
        'this Fusion Summoned card is sent to the GY by a card effect: You can Special '
        'Summon this card.'
    )

    sentences = split_sentences(text)

    assert len(sentences) == 4
    assert sentences[0] == "Other Aqua monsters you control cannot be destroyed by battle."
    assert sentences[1] == (
        'You can only use each of the following effects of "Tearlaments Rulkallos" once per turn.'
    )
    assert sentences[2].startswith("When your opponent activates")
    assert sentences[2].endswith("to the GY.")
    assert sentences[3] == (
        "If this Fusion Summoned card is sent to the GY by a card effect: "
        "You can Special Summon this card."
    )


def test_splits_three_sentences_floowandereeze_empen():
    from aijudge.effect_parser.sentence_splitter import split_sentences

    text = (
        'If this card is Tribute Summoned: You can add 1 "Floowandereeze" Spell/Trap from '
        'your Deck to your hand, then immediately after this effect resolves, you can Normal '
        'Summon 1 monster. While this Tribute Summoned card is in the Monster Zone, your '
        'opponent cannot activate the effects of Special Summoned monsters they control in '
        'Attack Position. Once per battle, during damage calculation, if this card battles '
        "an opponent's monster (Quick Effect): You can banish 1 card from your hand; that "
        "opponent's monster's current ATK/DEF become halved until the end of this turn."
    )

    sentences = split_sentences(text)

    assert len(sentences) == 3
    assert sentences[0].startswith("If this card is Tribute Summoned")
    assert sentences[1].startswith("While this Tribute Summoned card")
    assert sentences[2].startswith("Once per battle")


def test_single_sentence_mudballman_remainder():
    from aijudge.effect_parser.sentence_splitter import split_sentences

    text = "Must be Fusion Summoned and cannot be Special Summoned by other ways."

    assert split_sentences(text) == [text]


def test_empty_text_returns_empty_list():
    from aijudge.effect_parser.sentence_splitter import split_sentences

    assert split_sentences("") == []
    assert split_sentences("   ") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/effect_parser/test_sentence_splitter.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

Create `src/aijudge/effect_parser/sentence_splitter.py`:

```python
import re

# A sentence boundary is a period followed by whitespace and the start of
# the next sentence -- a capital letter, or an opening quote around a
# quoted card name. The whitespace itself is consumed by the split (and
# each part is stripped), matching the existing project convention of
# normalizing whitespace rather than preserving it verbatim (see
# clause_splitter._normalize, which this replaces the LLM-facing half of).
_SENTENCE_BOUNDARY = re.compile(r'(?<=[.])\s+(?=[A-Z"])')


def split_sentences(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    return [part.strip() for part in _SENTENCE_BOUNDARY.split(text) if part.strip()]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/effect_parser/test_sentence_splitter.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/effect_parser/sentence_splitter.py tests/effect_parser/test_sentence_splitter.py
git commit -m "feat(effect_parser): add deterministic sentence tokenizer"
```

---

### Task 5: Card Material extraction

**Files:**
- Modify: `src/aijudge/effect_parser/sentence_splitter.py`
- Test: `tests/effect_parser/test_sentence_splitter.py`

**Interfaces:**
- Produces: `extract_card_material(card_text: str, *, card_type: str) -> tuple[str | None, str]`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/effect_parser/test_sentence_splitter.py`:

```python
def test_extracts_material_for_fusion_monster_tearlaments_rulkallos():
    from aijudge.effect_parser.sentence_splitter import extract_card_material

    card_text = (
        '"Tearlaments Kitkallos" + 1 "Tearlaments" monster\r\n'
        'Other Aqua monsters you control cannot be destroyed by battle.'
    )

    material, remainder = extract_card_material(card_text, card_type="Fusion Monster")

    assert material == '"Tearlaments Kitkallos" + 1 "Tearlaments" monster'
    assert remainder == "Other Aqua monsters you control cannot be destroyed by battle."


def test_extracts_material_case_insensitively_for_xyz_monster():
    """YGOPRODeck's real `type` field for Xyz monsters is 'XYZ Monster'
    (all-caps XYZ), not 'Xyz Monster' -- this must match either way."""
    from aijudge.effect_parser.sentence_splitter import extract_card_material

    material, remainder = extract_card_material("2 Level 4 monsters", card_type="XYZ Monster")

    assert material == "2 Level 4 monsters"
    assert remainder == ""


def test_vanilla_extra_deck_monster_has_empty_remainder():
    """Gem-Knight Pearl: has_effect=0, the entire card_text is the
    materials line."""
    from aijudge.effect_parser.sentence_splitter import extract_card_material

    material, remainder = extract_card_material("2 Level 4 monsters", card_type="XYZ Monster")

    assert material == "2 Level 4 monsters"
    assert remainder == ""


def test_no_material_for_non_extra_deck_monster():
    from aijudge.effect_parser.sentence_splitter import extract_card_material

    card_text = "If this card is Tribute Summoned: You can add 1 card to your hand."

    material, remainder = extract_card_material(card_text, card_type="Effect Monster")

    assert material is None
    assert remainder == card_text


def test_synchro_and_link_also_match():
    from aijudge.effect_parser.sentence_splitter import extract_card_material

    assert extract_card_material("1 Tuner + 1+ non-Tuner monsters", card_type="Synchro Monster")[0] is not None
    assert extract_card_material("2 monsters, including a Tuner", card_type="Link Monster")[0] is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/effect_parser/test_sentence_splitter.py -k material -v`
Expected: FAIL with `ImportError: cannot import name 'extract_card_material'`

- [ ] **Step 3: Implement**

Add to `src/aijudge/effect_parser/sentence_splitter.py`:

```python
_EXTRA_DECK_TYPE_MARKERS = ("fusion", "synchro", "xyz", "link")


def extract_card_material(card_text: str, *, card_type: str) -> tuple[str | None, str]:
    """For Fusion/Synchro/Xyz/Link monsters, split the materials line (the
    first line of card_text) from the rest. Matching is case-insensitive --
    YGOPRODeck's real `type` field renders Xyz monsters as "XYZ Monster"
    (all-caps), not "Xyz Monster".

    Returns (None, card_text) for every other card_type: no material line
    to extract. For an Extra Deck monster whose entire text *is* the
    materials line (a vanilla monster with no effect at all -- see
    Gem-Knight Pearl), remainder is "".
    """
    lowered_type = card_type.lower()
    if not any(marker in lowered_type for marker in _EXTRA_DECK_TYPE_MARKERS):
        return None, card_text

    normalized = card_text.replace("\r\n", "\n")
    lines = normalized.split("\n", 1)
    material = lines[0].strip()
    remainder = lines[1].strip() if len(lines) > 1 else ""
    return material, remainder
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/effect_parser/test_sentence_splitter.py -v`
Expected: PASS, 9 tests total.

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/effect_parser/sentence_splitter.py tests/effect_parser/test_sentence_splitter.py
git commit -m "feat(effect_parser): extract Card Material line for Extra Deck monsters"
```

---

### Task 6: Widen `card_moved_trigger` self-reference matching

**Files:**
- Modify: `src/aijudge/effect_parser/parser.py:44-60`
- Test: `tests/effect_parser/test_parser.py`

**Interfaces:**
- No signature changes -- `classify_damage_step_category` behavior only.

- [ ] **Step 1: Write the failing test**

Add to `tests/effect_parser/test_parser.py`:

```python
def test_card_moved_trigger_matches_fusion_summoned_card_self_reference():
    """Tearlaments Rulkallos: 'If this Fusion Summoned card is sent to the
    GY by a card effect' -- Extra Deck monsters commonly self-refer via
    their summon-mechanic name instead of bare 'this card'."""
    from aijudge.effect_parser.parser import classify_damage_step_category
    from aijudge.rules_engine.models import EffectType

    result = classify_damage_step_category(
        "You can Special Summon this card.",
        activation_condition="If this Fusion Summoned card is sent to the GY by a card effect",
        effect_type=EffectType.TRIGGER,
    )

    assert result == "card_moved_trigger"


def test_card_moved_trigger_matches_xyz_monster_self_reference():
    from aijudge.effect_parser.parser import classify_damage_step_category
    from aijudge.rules_engine.models import EffectType

    result = classify_damage_step_category(
        "You can Special Summon this card from your GY.",
        activation_condition="If this Xyz Monster is destroyed by battle",
        effect_type=EffectType.TRIGGER,
    )

    assert result == "card_moved_trigger"


def test_card_moved_trigger_still_matches_bare_this_card():
    """Regression: the existing literal 'this card' match must keep working."""
    from aijudge.effect_parser.parser import classify_damage_step_category
    from aijudge.rules_engine.models import EffectType

    result = classify_damage_step_category(
        "You can add 1 card to your hand.",
        activation_condition="If this card is Tribute Summoned",
        effect_type=EffectType.TRIGGER,
    )

    assert result == "card_moved_trigger"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/effect_parser/test_parser.py -k card_moved_trigger -v`
Expected: `test_card_moved_trigger_matches_fusion_summoned_card_self_reference` and the Xyz test FAIL (assert `None == "card_moved_trigger"`); the bare-`this card` regression test already PASSes.

- [ ] **Step 3: Implement**

In `src/aijudge/effect_parser/parser.py`, replace lines 44-60:

```python
# A Trigger/Trigger-like/Quick/Quick-like effect whose *own card* undergoes a
# zone-change verb as its activation condition -- e.g. "if this card is
# destroyed by battle" or "if this card is Special Summoned". Deliberately
# requires a self-reference (either bare "this card" or, for Extra Deck
# monsters, "this <Xyz/Synchro/Fusion/Link/Pendulum> Monster"/"this Fusion
# Summoned card" -- these cards routinely self-refer via their summon
# mechanic instead of "this card"); a condition about some *other* card
# moving (e.g. "if a Salamangreat monster... is sent to the GY") is not
# reliably Damage-Step-legal (real cards carve such conditions out
# explicitly), so it is intentionally left unmatched rather than guessed.
# "sent" is the irregular past tense of "send" (e.g. Tearlaments Kitkallos:
# "if this card is sent to the GY by card effect") and needs its own bare
# alternative rather than a "send"-plus-\w* stem match, since \w* after
# "sent" would also swallow unrelated words like "sentence".
_SELF_MOVEMENT_VERBS = r"(?:(?:destroy|banish|send)\w*|sent|(?:return|summon|flip|tribute)\w*)"
_SELF_REFERENCE = r"(?:this card|this (?:Xyz|Synchro|Fusion|Link|Pendulum) Monster|this Fusion Summoned card)"
_CARD_MOVED_TRIGGER_PATTERN = re.compile(
    rf"\b{_SELF_REFERENCE}\b.{{0,40}}?\b{_SELF_MOVEMENT_VERBS}\b"
    rf"|\b{_SELF_MOVEMENT_VERBS}\b.{{0,40}}?\b{_SELF_REFERENCE}\b",
    re.IGNORECASE,
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/effect_parser/test_parser.py -v`
Expected: PASS, all tests including pre-existing ones.

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/effect_parser/parser.py tests/effect_parser/test_parser.py
git commit -m "fix(effect_parser): widen card_moved_trigger self-reference for Extra Deck monsters"
```

---

### Task 7: Summoning Condition classification

**Files:**
- Modify: `src/aijudge/effect_parser/parser.py:139-206`
- Test: `tests/effect_parser/test_parser.py`

**Interfaces:**
- No signature changes -- `classify_effect_type` may now return `EffectType.SUMMONING_CONDITION`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/effect_parser/test_parser.py`:

```python
def test_summoning_condition_classified_for_must_be_fusion_summoned():
    """Elemental HERO Mudballman."""
    from aijudge.effect_parser.parser import classify_effect_type
    from aijudge.rules_engine.models import EffectType

    result = classify_effect_type(
        "Must be Fusion Summoned and cannot be Special Summoned by other ways.",
        card_type="Fusion Monster",
    )

    assert result == EffectType.SUMMONING_CONDITION


def test_summoning_condition_cannot_be_normal_summoned_or_set():
    from aijudge.effect_parser.parser import classify_effect_type
    from aijudge.rules_engine.models import EffectType

    result = classify_effect_type(
        "Cannot be Normal Summoned or Set.",
        card_type="Ritual Effect Monster",
    )

    assert result == EffectType.SUMMONING_CONDITION


def test_active_voice_special_summon_restriction_stays_continuous():
    """Artmage Power Patron: 'You cannot Special Summon from the Extra
    Deck, except Fusion Monsters.' is a field-wide lockdown (active voice),
    not a restriction on how *this card* is summoned (passive voice) --
    must NOT match the Summoning Condition patterns."""
    from aijudge.effect_parser.parser import classify_effect_type
    from aijudge.rules_engine.models import EffectType

    result = classify_effect_type(
        "You cannot Special Summon from the Extra Deck, except Fusion Monsters.",
        card_type="Effect Monster",
    )

    assert result == EffectType.CONTINUOUS


def test_you_can_only_still_wins_over_default_continuous():
    """Regression: existing CONDITION classification unaffected."""
    from aijudge.effect_parser.parser import classify_effect_type
    from aijudge.rules_engine.models import EffectType

    result = classify_effect_type(
        "You can only control 1 face-up.",
        card_type="Effect Monster",
    )

    assert result == EffectType.CONDITION
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/effect_parser/test_parser.py -k summoning_condition -v`
Expected: first two FAIL (`assert EffectType.CONTINUOUS == EffectType.SUMMONING_CONDITION`); the active-voice test already passes (nothing matches yet); the "you can only" regression already passes.

- [ ] **Step 3: Implement**

In `src/aijudge/effect_parser/parser.py`, add the canonical-phrase patterns near the other module-level patterns (after `_USAGE_LIMIT_PATTERN` at line 28):

```python
# Canonical, highly formulaic PSCT boilerplate for how a card may be
# Summoned -- reused near-verbatim across thousands of cards, so precision
# on these specific phrases is expected to be high; anything that doesn't
# match one of them falls through to CONTINUOUS exactly as before, rather
# than guessing (see design spec section 7 for the confidence rationale).
# Deliberately does NOT match active-voice "cannot Special Summon [monsters
# in general]" restrictions (a field-wide lockdown effect, e.g. Artmage
# Power Patron) -- only passive-voice restrictions on how *this card*
# itself may be Summoned.
_SUMMONING_CONDITION_PATTERNS = (
    re.compile(r"must (?:be|first be) .*summoned", re.IGNORECASE),
    re.compile(r"cannot be special summoned except", re.IGNORECASE),
    re.compile(r"cannot be normal summoned or set", re.IGNORECASE),
    re.compile(r"cannot be used as .*material", re.IGNORECASE),
)


def _is_summoning_condition(text: str) -> bool:
    return any(pattern.search(text) for pattern in _SUMMONING_CONDITION_PATTERNS)
```

Then change the no-colon/no-semicolon branch in `classify_effect_type` (lines 188-191):

```python
    if ":" not in text and ";" not in text:
        if _is_summoning_condition(text):
            return EffectType.SUMMONING_CONDITION
        if "you can only" in lowered:
            return EffectType.CONDITION
        return EffectType.CONTINUOUS
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/effect_parser/test_parser.py -v`
Expected: PASS, all tests including pre-existing ones.

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/effect_parser/parser.py tests/effect_parser/test_parser.py
git commit -m "feat(effect_parser): classify Summoning Condition via canonical phrase list"
```

---

### Task 8: Usage-limit selector-form grammar (this is also "clause grouping" — spec §4)

**Note on scope:** the spec's §4 "Clause grouping" describes sentences merging into one clause via structural continuation signals, separately from usage-limit scoping. In every one of the five real cards traced during design (the four in the spec plus Artmage Power Patron), every non-usage-limit sentence was already its own complete clause — no multi-sentence single effect was ever observed. This task therefore implements grouping as: every sentence is its own clause candidate *except* usage-limit sentences, which are removed and scoped separately below. No continuation-merging logic exists yet because no validated real example needs it (matches the spec's own stance: "if [a multi-sentence effect case] turns up during implementation, handle it as a targeted addition, not a reason to fall back to the LLM"). If a future card needs it, add a `_looks_like_continuation(sentence)` check to `resolve_usage_limit_scopes` below with a real card-text test case — don't add it speculatively here.

**Files:**
- Create: `src/aijudge/effect_parser/usage_limit.py`
- Test: `tests/effect_parser/test_usage_limit.py`

**Interfaces:**
- Produces: `UsageLimitScope` dataclass (`text: str`, `applies_to: list[int]`, `ambiguous: bool`), `resolve_usage_limit_scopes(sentences: list[str]) -> tuple[list[str], list[UsageLimitScope]]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/effect_parser/test_usage_limit.py`:

```python
def test_each_of_following_effects_scopes_to_both_trailing_clauses():
    """Tearlaments Rulkallos: 'each of the following effects' (plural) is
    an independently-budgeted positional-plural reference -- scopes to
    every clause after it, not the Continuous clause before it."""
    from aijudge.effect_parser.usage_limit import resolve_usage_limit_scopes

    sentences = [
        "Other Aqua monsters you control cannot be destroyed by battle.",
        'You can only use each of the following effects of "Tearlaments Rulkallos" once per turn.',
        "When your opponent activates a card...(Quick Effect): You can negate the activation.",
        "If this Fusion Summoned card is sent to the GY by a card effect: You can Special Summon this card.",
    ]

    clauses, scopes = resolve_usage_limit_scopes(sentences)

    assert clauses == [sentences[0], sentences[2], sentences[3]]
    assert len(scopes) == 1
    assert scopes[0].applies_to == [1, 2]
    assert scopes[0].ambiguous is False


def test_positional_singular_following_scopes_to_one_clause():
    from aijudge.effect_parser.usage_limit import resolve_usage_limit_scopes

    sentences = [
        "Clause A.",
        "You can only use the following effect of \"Card\" once per turn.",
        "Clause B.",
        "Clause C.",
    ]

    clauses, scopes = resolve_usage_limit_scopes(sentences)

    assert clauses == ["Clause A.", "Clause B.", "Clause C."]
    assert scopes[0].applies_to == [1]  # just "Clause B.", not "Clause C." too


def test_positional_plural_preceding_scopes_to_all_prior_clauses():
    from aijudge.effect_parser.usage_limit import resolve_usage_limit_scopes

    sentences = [
        "Clause A.",
        "Clause B.",
        "You can only use the preceding effects of \"Card\" once per turn.",
        "Clause C.",
    ]

    clauses, scopes = resolve_usage_limit_scopes(sentences)

    assert clauses == ["Clause A.", "Clause B.", "Clause C."]
    assert scopes[0].applies_to == [0, 1]


def test_positional_singular_preceding_scopes_to_immediately_prior_clause():
    from aijudge.effect_parser.usage_limit import resolve_usage_limit_scopes

    sentences = [
        "Clause A.",
        "Clause B.",
        "You can only use the preceding effect of \"Card\" once per turn.",
    ]

    clauses, scopes = resolve_usage_limit_scopes(sentences)

    assert scopes[0].applies_to == [1]


def test_self_scoped_default_attaches_to_immediately_preceding_clause():
    from aijudge.effect_parser.usage_limit import resolve_usage_limit_scopes

    sentences = [
        "Clause A.",
        'You can only use this effect of "Card" once per turn.',
        "Clause B.",
    ]

    clauses, scopes = resolve_usage_limit_scopes(sentences)

    assert clauses == ["Clause A.", "Clause B."]
    assert scopes[0].applies_to == [0]


def test_bare_these_effects_is_ambiguous():
    from aijudge.effect_parser.usage_limit import resolve_usage_limit_scopes

    sentences = [
        "Clause A.",
        "Clause B.",
        'You can only use 1 of these effects of "Card" per turn.',
    ]

    clauses, scopes = resolve_usage_limit_scopes(sentences)

    assert scopes[0].ambiguous is True
    assert scopes[0].applies_to == []


def test_group_select_with_positional_pointer_is_not_ambiguous():
    """'1 of following effect' (singular) collapses to exactly the one
    adjacent clause -- not the bare-'these effects' ambiguous case."""
    from aijudge.effect_parser.usage_limit import resolve_usage_limit_scopes

    sentences = [
        "Clause A.",
        "You can only use 1 of following effect of \"Card\" per turn, and only once that turn.",
        "Clause B.",
    ]

    clauses, scopes = resolve_usage_limit_scopes(sentences)

    assert scopes[0].ambiguous is False
    assert scopes[0].applies_to == [1]


def test_named_card_restriction_without_effect_word_is_not_clause_scoped():
    from aijudge.effect_parser.usage_limit import resolve_usage_limit_scopes

    sentences = [
        "Clause A.",
        'You can only activate 1 "Card Name" per turn.',
        "Clause B.",
    ]

    clauses, scopes = resolve_usage_limit_scopes(sentences)

    assert clauses == ["Clause A.", "Clause B."]
    assert scopes[0].applies_to == []
    assert scopes[0].ambiguous is False


def test_sentence_without_usage_limit_phrase_is_untouched():
    from aijudge.effect_parser.usage_limit import resolve_usage_limit_scopes

    sentences = ["Clause A.", "Clause B."]

    clauses, scopes = resolve_usage_limit_scopes(sentences)

    assert clauses == sentences
    assert scopes == []


def test_extract_verb_width():
    from aijudge.effect_parser.usage_limit import extract_verb_width

    assert extract_verb_width('You can only activate 1 "Card" per turn.') == "narrow"
    assert extract_verb_width('You can only use 1 "Card" per turn.') == "broad"
    assert extract_verb_width("Clause with no restriction.") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/effect_parser/test_usage_limit.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

Create `src/aijudge/effect_parser/usage_limit.py`:

```python
import re
from dataclasses import dataclass, field

_IS_USAGE_LIMIT_SENTENCE = re.compile(r"\byou can only\b", re.IGNORECASE)
_CONTAINS_EFFECT_WORD = re.compile(r"\beffects?\b", re.IGNORECASE)
_POSITIONAL_DIRECTION = re.compile(r"\b(preceding|following)\b", re.IGNORECASE)
_POSITIONAL_SINGULAR = re.compile(r"\b(?:preceding|following) effect\b(?!s)", re.IGNORECASE)
_VERB_WIDTH = re.compile(r"\byou can only (activate|use)\b", re.IGNORECASE)


@dataclass
class UsageLimitScope:
    text: str
    applies_to: list[int] = field(default_factory=list)
    ambiguous: bool = False


def extract_verb_width(sentence: str) -> str | None:
    match = _VERB_WIDTH.search(sentence)
    if not match:
        return None
    return "narrow" if match.group(1).lower() == "activate" else "broad"


def resolve_usage_limit_scopes(sentences: list[str]) -> tuple[list[str], list[UsageLimitScope]]:
    """Split `sentences` into (clause candidates, usage-limit scopes).

    A sentence containing "you can only" is never a clause candidate
    itself -- it's a restriction that scopes to some subset of the
    *other* sentences, resolved by `_resolve_scope` below.
    """
    clauses: list[str] = []
    usage_limit_sentences: list[tuple[str, int]] = []  # (sentence, insertion_point)

    for sentence in sentences:
        if _IS_USAGE_LIMIT_SENTENCE.search(sentence):
            usage_limit_sentences.append((sentence, len(clauses)))
        else:
            clauses.append(sentence)

    scopes = []
    for sentence, insertion_point in usage_limit_sentences:
        num_following = len(clauses) - insertion_point
        applies_to, ambiguous = _resolve_scope(sentence, insertion_point, num_following)
        scopes.append(UsageLimitScope(text=sentence, applies_to=applies_to, ambiguous=ambiguous))

    return clauses, scopes


def _resolve_scope(sentence: str, insertion_point: int, num_following: int) -> tuple[list[int], bool]:
    direction_match = _POSITIONAL_DIRECTION.search(sentence)
    if direction_match:
        direction = direction_match.group(1).lower()
        singular = bool(_POSITIONAL_SINGULAR.search(sentence))
        return _positional_indices(direction, singular, insertion_point, num_following), False

    if not _CONTAINS_EFFECT_WORD.search(sentence):
        # A named-card restriction with no "effect" wording at all (e.g.
        # "You can only activate 1 'Card Name' per turn.") restricts the
        # card by name/copies, not by clause position -- not clause-scoped.
        return [], False

    if "these effects" in sentence.lower():
        # No positional pointer to resolve the set against -- genuinely
        # ambiguous, escalates to LLM concurrence (see resolve_ambiguous_scope).
        return [], True

    # Self-scoped: "this effect" or no reference at all -- attaches to the
    # one clause this sentence trails.
    if insertion_point > 0:
        return [insertion_point - 1], False
    return [], False


def _positional_indices(direction: str, singular: bool, insertion_point: int, num_following: int) -> list[int]:
    if direction == "preceding":
        if singular:
            return [insertion_point - 1] if insertion_point > 0 else []
        return list(range(0, insertion_point))
    # direction == "following"
    if singular:
        return [insertion_point] if num_following > 0 else []
    return list(range(insertion_point, insertion_point + num_following))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/effect_parser/test_usage_limit.py -v`
Expected: PASS, 10 tests.

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/effect_parser/usage_limit.py tests/effect_parser/test_usage_limit.py
git commit -m "feat(effect_parser): usage-limit selector-form scope resolution"
```

---

### Task 9: Ambiguous-scope LLM concurrence

**Files:**
- Modify: `src/aijudge/effect_parser/usage_limit.py`
- Test: `tests/effect_parser/test_usage_limit.py`

**Interfaces:**
- Consumes: `aijudge.llm.client.LLMClient` (existing `Protocol` with `complete(prompt: str) -> str`).
- Produces: `resolve_ambiguous_scope(llm_client: LLMClient, *, usage_limit_text: str, clauses: list[str]) -> list[int]`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/effect_parser/test_usage_limit.py`:

```python
def test_resolve_ambiguous_scope_parses_comma_separated_indices():
    from aijudge.effect_parser.usage_limit import resolve_ambiguous_scope
    from aijudge.llm.client import MockLLMClient

    llm_client = MockLLMClient()
    llm_client.queue_response("1,2")

    result = resolve_ambiguous_scope(
        llm_client,
        usage_limit_text='You can only use 1 of these effects of "Card" per turn.',
        clauses=["Effect A.", "Effect B.", "Effect C."],
    )

    assert result == [0, 1]


def test_resolve_ambiguous_scope_all_means_every_clause():
    from aijudge.effect_parser.usage_limit import resolve_ambiguous_scope
    from aijudge.llm.client import MockLLMClient

    llm_client = MockLLMClient()
    llm_client.queue_response("all")

    result = resolve_ambiguous_scope(
        llm_client,
        usage_limit_text='You can only use 1 of these effects of "Card" per turn.',
        clauses=["Effect A.", "Effect B."],
    )

    assert result == [0, 1]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/effect_parser/test_usage_limit.py -k ambiguous_scope -v`
Expected: FAIL with `ImportError: cannot import name 'resolve_ambiguous_scope'`

- [ ] **Step 3: Implement**

Add to `src/aijudge/effect_parser/usage_limit.py`:

```python
from aijudge.llm.client import LLMClient

_AMBIGUOUS_SCOPE_PROMPT_TEMPLATE = (
    "The following restriction sentence was found on a Yu-Gi-Oh! card, but which "
    "of the card's effects it applies to is not stated by position (no "
    "'preceding'/'following' pointer). Read the card's effects and decide which "
    "ones (by number) the restriction applies to. Respond with only a "
    "comma-separated list of numbers (e.g. '1,2'), or 'all' if it applies to "
    "every effect listed.\n\n"
    "Restriction: {usage_limit_text}\n\n"
    "Card's effects:\n{numbered_effects}"
)


def resolve_ambiguous_scope(llm_client: LLMClient, *, usage_limit_text: str, clauses: list[str]) -> list[int]:
    numbered_effects = "\n".join(f"{i}. {text}" for i, text in enumerate(clauses, start=1))
    prompt = _AMBIGUOUS_SCOPE_PROMPT_TEMPLATE.format(
        usage_limit_text=usage_limit_text, numbered_effects=numbered_effects
    )
    response = llm_client.complete(prompt).strip()
    if response.lower() == "all":
        return list(range(len(clauses)))
    return [int(token.strip()) - 1 for token in response.split(",") if token.strip()]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/effect_parser/test_usage_limit.py -v`
Expected: PASS, 12 tests.

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/effect_parser/usage_limit.py tests/effect_parser/test_usage_limit.py
git commit -m "feat(effect_parser): resolve ambiguous usage-limit scope via LLM concurrence"
```

---

### Task 10: Rewrite `clause_splitter.resolve_effect_clauses`

**Files:**
- Modify: `src/aijudge/effect_parser/clause_splitter.py` (full rewrite)
- Test: `tests/effect_parser/test_clause_splitter.py` (rewrite to match)

**Interfaces:**
- Consumes: `sentence_splitter.split_sentences`, `usage_limit.resolve_usage_limit_scopes`, `usage_limit.UsageLimitScope`.
- Produces: `resolve_effect_clauses(llm_client: LLMClient, card_text: str, *, threshold: float = DEFAULT_CONFIDENCE_THRESHOLD) -> tuple[list[str], list[UsageLimitScope]]` -- **signature change**: now returns a tuple, not a bare `list[str]`. `score_split_confidence` is unchanged and still exported. `split_effect_clauses`, `_reconstructs`, `_normalize`, `_SPLIT_PROMPT_TEMPLATE` are deleted.

- [ ] **Step 1: Read the existing test file to see what's being replaced**

Run: `cat tests/effect_parser/test_clause_splitter.py` and read it fully -- it currently tests `split_effect_clauses`/`resolve_effect_clauses` against `MockLLMClient` queued responses for the old LLM-segmentation behavior. Every test that exercises `split_effect_clauses` directly is being deleted since that function is deleted; every test that exercises `resolve_effect_clauses` needs its assertions updated for the new tuple return type and deterministic (not LLM-produced) candidates.

- [ ] **Step 2: Write the failing tests**

Replace the contents of `tests/effect_parser/test_clause_splitter.py` with:

```python
from aijudge.llm.client import MockLLMClient


def test_resolve_effect_clauses_single_effect_skips_confidence_check():
    from aijudge.effect_parser.clause_splitter import resolve_effect_clauses

    llm_client = MockLLMClient()  # no queued response -- must not be called

    clauses, scopes = resolve_effect_clauses(llm_client, "Must be Fusion Summoned and cannot be Special Summoned by other ways.")

    assert clauses == ["Must be Fusion Summoned and cannot be Special Summoned by other ways."]
    assert scopes == []


def test_resolve_effect_clauses_multi_effect_with_usage_limit_scope():
    """Tearlaments Rulkallos remainder (post-material-extraction)."""
    from aijudge.effect_parser.clause_splitter import resolve_effect_clauses

    card_text = (
        'Other Aqua monsters you control cannot be destroyed by battle. You can only use '
        'each of the following effects of "Tearlaments Rulkallos" once per turn. When your '
        'opponent activates a card or effect that includes an effect that Special Summons a '
        'monster(s) (Quick Effect): You can negate the activation, and if you do, destroy '
        'it, then, send 1 "Tearlaments" card from your hand or face-up field to the GY. If '
        'this Fusion Summoned card is sent to the GY by a card effect: You can Special '
        'Summon this card.'
    )
    llm_client = MockLLMClient()
    llm_client.queue_response("0.95")  # score_split_confidence

    clauses, scopes = resolve_effect_clauses(llm_client, card_text)

    assert len(clauses) == 3
    assert clauses[0].startswith("Other Aqua monsters")
    assert clauses[1].startswith("When your opponent activates")
    assert clauses[2].startswith("If this Fusion Summoned card")
    assert len(scopes) == 1
    assert scopes[0].applies_to == [1, 2]


def test_resolve_effect_clauses_falls_back_below_threshold():
    from aijudge.effect_parser.clause_splitter import resolve_effect_clauses

    card_text = "Clause A. Clause B."
    llm_client = MockLLMClient()
    llm_client.queue_response("0.1")  # below DEFAULT_CONFIDENCE_THRESHOLD

    clauses, scopes = resolve_effect_clauses(llm_client, card_text)

    assert clauses == [card_text]
    assert scopes == []


def test_resolve_effect_clauses_empty_text_returns_nothing():
    from aijudge.effect_parser.clause_splitter import resolve_effect_clauses

    llm_client = MockLLMClient()

    clauses, scopes = resolve_effect_clauses(llm_client, "")

    assert clauses == []
    assert scopes == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/effect_parser/test_clause_splitter.py -v`
Expected: FAIL -- `resolve_effect_clauses` currently returns a plain list, not a tuple, so `clauses, scopes = ...` unpacking fails (or the old implementation errors trying to call the deleted LLM-split flow with an empty `MockLLMClient` queue).

- [ ] **Step 4: Implement**

Replace `src/aijudge/effect_parser/clause_splitter.py` entirely:

```python
from aijudge.effect_parser.review_agent import DEFAULT_CONFIDENCE_THRESHOLD
from aijudge.effect_parser.sentence_splitter import split_sentences
from aijudge.effect_parser.usage_limit import UsageLimitScope, resolve_usage_limit_scopes
from aijudge.llm.client import LLMClient

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
) -> tuple[list[str], list[UsageLimitScope]]:
    """Deterministically segment `card_text` (already stripped of any Card
    Material line by the caller) into effect clauses, resolving usage-limit
    scope, then verify the resulting grouping via one LLM confidence call --
    replacing what used to be an LLM-driven split. See design spec sections
    3-5."""
    sentences = split_sentences(card_text)
    if not sentences:
        return [], []

    clauses, scopes = resolve_usage_limit_scopes(sentences)
    if len(clauses) <= 1:
        return clauses, scopes

    confidence = score_split_confidence(llm_client, card_text=card_text, effect_texts=clauses)
    if confidence < threshold:
        return [card_text], []
    return clauses, scopes
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/effect_parser/test_clause_splitter.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 6: Commit**

```bash
git add src/aijudge/effect_parser/clause_splitter.py tests/effect_parser/test_clause_splitter.py
git commit -m "refactor(effect_parser): replace LLM-driven clause splitting with deterministic segmentation"
```

---

### Task 11: `review_parsed_effect` cross-effect concurrence

**Files:**
- Modify: `src/aijudge/effect_parser/review_agent.py`
- Test: `tests/effect_parser/test_review_agent.py`

**Interfaces:**
- Produces: `review_parsed_effect(..., other_effects: list[str] | None = None, ...)` -- additive, backward-compatible parameter.

- [ ] **Step 1: Write the failing test**

`tests/effect_parser/test_review_agent.py` already has a `test_damage_step_category_is_included_in_the_review_prompt` test that defines a local `_CapturingLLMClient` class (since `MockLLMClient` records `system_prompts` but not the `prompt` text itself) — reuse that exact pattern:

```python
def test_review_parsed_effect_includes_other_effects_in_prompt_when_provided():
    from aijudge.effect_parser.review_agent import review_parsed_effect

    captured = {}

    class _CapturingLLMClient:
        def complete(self, prompt, *, system=None):
            captured["prompt"] = prompt
            return "0.9"

    review_parsed_effect(
        _CapturingLLMClient(),
        raw_text="Effect A text.",
        activation_condition=None,
        cost=None,
        targeting=None,
        effect="Effect A text.",
        other_effects=["Effect B text."],
    )

    assert "Effect B text." in captured["prompt"]
    assert "shares a usage-limit restriction" in captured["prompt"]


def test_review_parsed_effect_omits_other_effects_section_when_none():
    from aijudge.effect_parser.review_agent import review_parsed_effect

    captured = {}

    class _CapturingLLMClient:
        def complete(self, prompt, *, system=None):
            captured["prompt"] = prompt
            return "0.9"

    review_parsed_effect(
        _CapturingLLMClient(),
        raw_text="Effect A text.",
        activation_condition=None,
        cost=None,
        targeting=None,
        effect="Effect A text.",
    )

    assert "shares a usage-limit restriction" not in captured["prompt"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/effect_parser/test_review_agent.py -k other_effects -v`
Expected: FAIL with `TypeError: review_parsed_effect() got an unexpected keyword argument 'other_effects'`

- [ ] **Step 3: Implement**

Replace `src/aijudge/effect_parser/review_agent.py`'s `review_parsed_effect`:

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
    other_effects: list[str] | None = None,
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
    if other_effects:
        numbered = "\n".join(f"{i}. {text}" for i, text in enumerate(other_effects, start=1))
        prompt += (
            "\n\nThis effect shares a usage-limit restriction with other effects on "
            "the same card. Verify the restriction's scope is consistent across all "
            "of them. Other effects on this card:\n" + numbered
        )
    response = llm_client.complete(prompt)
    confidence = float(response)
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"confidence must be between 0.0 and 1.0, got {confidence!r} (raw response: {response!r})")
    return ReviewResult(confidence=confidence, auto_confirmed=confidence >= threshold)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/effect_parser/test_review_agent.py -v`
Expected: PASS, all tests including pre-existing ones.

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/effect_parser/review_agent.py tests/effect_parser/test_review_agent.py
git commit -m "feat(effect_parser): review_parsed_effect accepts cross-effect concurrence context"
```

---

### Task 12: Schema and `cards_repo` -- add eligibility column, drop `card_materials`

**Files:**
- Modify: `src/aijudge/db/schema.sql`
- Modify: `src/aijudge/db/cards_repo.py`
- Test: `tests/db/test_cards_repo.py` (DB-dependent -- requires `DATABASE_URL`; see CLAUDE.md's DB setup steps before running)

**Interfaces:**
- Produces: `insert_card(..., deterministic_parse_eligible: bool, ...)` -- **required parameter, no default**, since every card must have an explicit eligibility determination. `card_materials` parameter removed entirely. `_CARD_COLUMNS` and every `SELECT`-based getter updated to include `deterministic_parse_eligible` in place of `card_materials`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/db/test_cards_repo.py` (matching the file's existing `pytestmark`/`setup_function` pattern shown at its top):

```python
def test_insert_card_requires_and_persists_deterministic_parse_eligible():
    from aijudge.db.cards_repo import get_card_by_name, insert_card

    insert_card(
        name="Eligible Test Card",
        card_text="Some effect text.",
        card_type="Effect Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 1, 1),
        ygoprodeck_id="1",
        deterministic_parse_eligible=True,
    )

    card = get_card_by_name("Eligible Test Card")

    assert card["deterministic_parse_eligible"] is True


def test_insert_card_no_longer_accepts_card_materials():
    from aijudge.db.cards_repo import insert_card

    with pytest.raises(TypeError):
        insert_card(
            name="Should Fail",
            card_text="text",
            card_type="Effect Monster",
            source="ygoprodeck",
            fetched_at=date(2026, 1, 1),
            ygoprodeck_id="2",
            deterministic_parse_eligible=True,
            card_materials="should not be accepted",
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/db/test_cards_repo.py -k deterministic_parse_eligible -v`
Expected: FAIL -- `insert_card` doesn't accept `deterministic_parse_eligible` yet (`TypeError: unexpected keyword argument`), and the "no longer accepts" test currently passes for the wrong reason (it *does* still accept `card_materials`, so it won't raise -- this flips to a real regression guard once Step 3 lands).

- [ ] **Step 3: Implement**

In `src/aijudge/db/schema.sql`, replace `card_materials TEXT,` (line 22) with the new column, and add the migration block for existing databases (following this file's established `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` pattern used for `race`, lines 32-45):

```sql
    has_errata BOOLEAN NOT NULL DEFAULT FALSE,
    deterministic_parse_eligible BOOLEAN NOT NULL DEFAULT TRUE,
```

(drop the `card_materials TEXT,` line and the closing `CHECK (race IN (...))` stays where it is, unaffected)

Then, immediately after the existing `race` migration block (after line 45, before `CREATE TABLE IF NOT EXISTS card_errata_versions`):

```sql
-- Same rationale as the race migration above: applied separately for
-- pre-existing databases. card_materials is dropped outright, not kept
-- for backwards compatibility -- nothing ever populated or read it (see
-- design spec's Data model changes section).
ALTER TABLE cards ADD COLUMN IF NOT EXISTS deterministic_parse_eligible BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE cards DROP COLUMN IF EXISTS card_materials;
```

In `src/aijudge/db/cards_repo.py`:

1. Update `_CARD_COLUMNS` (line 5-9), replacing nothing (this list mirrors `SELECT` order, which doesn't include `card_materials` or `deterministic_parse_eligible` today) -- add `deterministic_parse_eligible` at the end:

```python
_CARD_COLUMNS = [
    "id", "name", "card_text", "card_type", "race", "attribute", "monster_type",
    "level", "rank", "link_rating", "archetype", "atk", "def", "has_errata",
    "ygoprodeck_id", "ygoresources_id", "deterministic_parse_eligible",
]
```

2. Update `insert_card`'s signature: remove `card_materials: str | None = None`, add `deterministic_parse_eligible: bool` as a required keyword-only parameter (placed with the other required parameters, before the optional ones):

```python
def insert_card(
    *,
    name: str,
    card_text: str,
    card_type: str,
    source: str,
    fetched_at: date,
    ygoprodeck_id: str,
    deterministic_parse_eligible: bool,
    race: str | None = None,
    attribute: str | None = None,
    monster_type: str | None = None,
    level: int | None = None,
    rank: int | None = None,
    link_rating: int | None = None,
    archetype: str | None = None,
    atk: int | None = None,
    def_: int | None = None,
    ygoresources_id: str | None = None,
) -> str:
    with get_connection() as conn:
        row = conn.execute(
            """
            INSERT INTO cards (
                name, card_text, card_type, race, attribute, monster_type,
                level, rank, link_rating, archetype, atk, def,
                ygoprodeck_id, ygoresources_id, source, fetched_at, deterministic_parse_eligible
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                name, card_text, card_type, race, attribute, monster_type,
                level, rank, link_rating, archetype, atk, def_,
                ygoprodeck_id, ygoresources_id, source, fetched_at, deterministic_parse_eligible,
            ),
        ).fetchone()
        conn.commit()
        return str(row[0])
```

3. Add `deterministic_parse_eligible` to the `SELECT` column list in `get_card_by_name`, `get_card_by_id`, `get_cards_by_fname`, `get_cards_by_archetype`, `get_card_by_ygoprodeck_id`, `get_card_by_ygoresources_id` -- each currently ends its column list with `"ygoprodeck_id, ygoresources_id "`; append `, deterministic_parse_eligible` to that same string in all six places.

- [ ] **Step 4: Run tests to verify they pass**

Set up the DB first per CLAUDE.md (`docker compose up -d db`, `.env` present, then `python -c "from aijudge.db.migrate import run_migrations; run_migrations()"`).

Run: `pytest tests/db/test_cards_repo.py -v`
Expected: PASS, all tests including pre-existing ones. If `DATABASE_URL` isn't set, these are auto-skipped -- verify at minimum that `pytest tests/db/ -v` shows the new tests as `SKIPPED`, not `ERROR`, so a broken import doesn't hide behind the skip.

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/db/schema.sql src/aijudge/db/cards_repo.py tests/db/test_cards_repo.py
git commit -m "feat(db): add cards.deterministic_parse_eligible, drop unused card_materials"
```

---

### Task 13: `preflight.build_known_facts_context` renders new effect types distinctly

**Files:**
- Modify: `src/aijudge/orchestration/preflight.py:53-89`
- Test: `tests/orchestration/test_preflight_db.py` (DB-dependent — `build_known_facts_context` is tested here, not in `test_preflight.py`, which only covers `find_mentioned_card_names`)

**Interfaces:**
- No signature change to `build_known_facts_context(card: dict) -> str`.

- [ ] **Step 1: Write the failing tests**

`tests/orchestration/test_preflight_db.py` follows a consistent pattern: `pytestmark = pytest.mark.skipif("DATABASE_URL" not in os.environ, ...)`, a `setup_function` that runs migrations and truncates `cards`, and each test does a real `insert_card`/`insert_pending_effect`/`confirm_effect` then calls `build_known_facts_context(get_card_by_name(...))`. **Every `insert_card` call in this file must now also pass `deterministic_parse_eligible=True`** (Task 12 made it a required parameter) — when editing this file, add that argument to the six existing `insert_card` calls too, or they'll fail with `TypeError` once Task 12 lands.

Add to `tests/orchestration/test_preflight_db.py`:

```python
def test_build_known_facts_context_renders_card_material_distinctly():
    from aijudge.db.cards_repo import get_card_by_name, insert_card
    from aijudge.db.effects_repo import confirm_effect, insert_pending_effect
    from aijudge.orchestration.preflight import build_known_facts_context

    card_id = insert_card(
        name="Tearlaments Rulkallos",
        card_text='"Tearlaments Kitkallos" + 1 "Tearlaments" monster\nOther Aqua monsters...',
        card_type="Fusion Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="84330567",
        deterministic_parse_eligible=True,
    )
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="card_material",
        effect='"Tearlaments Kitkallos" + 1 "Tearlaments" monster',
    )
    confirm_effect(effect_id)

    context = build_known_facts_context(get_card_by_name("Tearlaments Rulkallos"))

    assert 'Card Material: "\\"Tearlaments Kitkallos\\" + 1 \\"Tearlaments\\" monster"' in context or (
        "Card Material:" in context and '"Tearlaments Kitkallos" + 1 "Tearlaments" monster' in context
    )
    assert "spell speed" not in context
    assert "activatable:" not in context


def test_build_known_facts_context_renders_summoning_condition_distinctly():
    from aijudge.db.cards_repo import get_card_by_name, insert_card
    from aijudge.db.effects_repo import confirm_effect, insert_pending_effect
    from aijudge.orchestration.preflight import build_known_facts_context

    card_id = insert_card(
        name="Elemental HERO Mudballman",
        card_text='"Elemental HERO Bubbleman" + "Elemental HERO Clayman"\nMust be Fusion Summoned...',
        card_type="Fusion Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="52031567",
        deterministic_parse_eligible=True,
    )
    effect_id = insert_pending_effect(
        card_id=card_id,
        effect_type="summoning_condition",
        effect="Must be Fusion Summoned and cannot be Special Summoned by other ways.",
    )
    confirm_effect(effect_id)

    context = build_known_facts_context(get_card_by_name("Elemental HERO Mudballman"))

    assert "Summoning Condition:" in context
    assert "Must be Fusion Summoned and cannot be Special Summoned by other ways." in context
    assert "spell speed" not in context
    assert "activatable:" not in context


def test_build_known_facts_context_mixes_card_material_with_normal_effects():
    from aijudge.db.cards_repo import get_card_by_name, insert_card
    from aijudge.db.effects_repo import confirm_effect, insert_pending_effect
    from aijudge.orchestration.preflight import build_known_facts_context

    card_id = insert_card(
        name="Tearlaments Rulkallos",
        card_text="...",
        card_type="Fusion Monster",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="84330567",
        deterministic_parse_eligible=True,
    )
    material_id = insert_pending_effect(
        card_id=card_id,
        effect_type="card_material",
        effect='"Tearlaments Kitkallos" + 1 "Tearlaments" monster',
    )
    confirm_effect(material_id)
    quick_id = insert_pending_effect(
        card_id=card_id,
        effect_type="quick",
        effect="You can negate the activation, and if you do, destroy it.",
        activation_condition="When your opponent activates a card or effect... (Quick Effect)",
    )
    confirm_effect(quick_id)

    context = build_known_facts_context(get_card_by_name("Tearlaments Rulkallos"))
    lines = context.splitlines()

    assert len(lines) == 3  # header + material line + quick effect line
    assert "Card Material:" in lines[1]
    assert "effect type quick" in lines[2]
```

- [ ] **Step 2: Run tests to verify they fail**

Bring up the DB first (`docker compose up -d db`, ensure `.env` is present, `DATABASE_URL` exported).
Run: `pytest tests/orchestration/test_preflight_db.py -k "card_material or summoning_condition" -v`
Expected: FAIL — current code calls `spell_speed_for`/`can_activate_during_damage_step` unconditionally for every effect type, so the rendered line looks like a normal effect line (contains "spell speed"/"activatable:") rather than the distinct label these tests require.

- [ ] **Step 3: Implement**

In `src/aijudge/orchestration/preflight.py`, modify the loop inside `build_known_facts_context` (lines 65-88) to branch on the new non-activatable types before computing spell speed / damage-step legality, which are meaningless for them:

```python
    lines = ["KNOWN FACTS (deterministic -- do not contradict):"]
    for index, confirmed in enumerate(confirmed_effects, start=1):
        effect_type = EffectType(confirmed["effect_type"])

        if effect_type == EffectType.CARD_MATERIAL:
            lines.append(f"- {card['name']}: Card Material: \"{confirmed['effect']}\"")
            continue
        if effect_type == EffectType.SUMMONING_CONDITION:
            lines.append(f"- {card['name']}: Summoning Condition: \"{confirmed['effect']}\"")
            continue

        speed = spell_speed_for(effect_type, race=card["race"])
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

Also add `EffectType.CARD_MATERIAL` and `EffectType.SUMMONING_CONDITION` to the existing `from aijudge.rules_engine.models import ...` import at the top of the file (line 42) -- `EffectType` is already imported, so only the usage above needs it, no import line change required.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/orchestration/test_preflight_db.py -v`
Expected: PASS, all tests including the six pre-existing ones (now updated with `deterministic_parse_eligible=True`).

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/orchestration/preflight.py tests/orchestration/test_preflight_db.py
git commit -m "feat(orchestration): render Card Material and Summoning Condition distinctly in KNOWN FACTS"
```

---

### Task 14: Rewire `seed_card` to the new pipeline

**Files:**
- Modify: `src/aijudge/ingestion/seed.py` (full rewrite of `seed_card`)
- Test: `tests/ingestion/test_seed.py`

**Interfaces:**
- Consumes: everything built in Tasks 1-13.
- No change to `seed_card`'s public signature except adding `fetch_sets_index_fn` (injectable, defaults to the real `printing_eligibility.fetch_sets_index`) for testability, matching the existing `fetch_card_fn`/`fetch_rulings_fn` injection pattern.

- [ ] **Step 1: Update every pre-existing test's fixtures for the new eligibility gate**

`tests/ingestion/test_seed.py` currently has 9 tests, none of whose `fake_fetch_card` functions return a `card_sets` key, and none of which pass a `fetch_sets_index_fn` override. Once Task 14's implementation lands, `seed_card` calls `fetch_sets_index_fn()` (defaulting to the real `printing_eligibility.fetch_sets_index`, which makes a live HTTP call) and treats a card with no qualifying `card_sets` entry as ineligible. Left unfixed, every existing test would either make a real network call or silently start hitting the "insert one UNCLASSIFIED row" branch instead of exercising the parsing pipeline they're meant to test.

For **every** existing `fake_fetch_card` in this file, add a `"card_sets"` key, e.g.:

```python
    def fake_fetch_card(name, http_get=None):
        return {
            "id": 47355498,
            "name": name,
            "type": "Quick-Play Spell",
            "desc": desc,
            "card_sets": [{"set_name": "Some Set"}],
        }
```

And pass a matching `fetch_sets_index_fn` into every `seed_card(...)` call in the file:

```python
    card_id = seed_card(
        "Called by the Grave",
        llm_client=llm_client,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=fake_fetch_rulings,
        fetch_sets_index_fn=lambda: {"Some Set": date(2020, 1, 1)},
    )
```

Apply this to all 9 existing tests: `test_seed_card_stores_card_ruling_and_confirms_a_high_confidence_effect`, `test_seed_card_passes_konami_id_from_misc_info_to_fetch_rulings`, `test_seed_card_continues_when_fetching_rulings_fails`, `test_seed_card_leaves_low_confidence_effect_pending`, `test_seed_card_classifies_a_tuner_monster_subtype_as_a_monster_effect`, `test_seed_card_stores_damage_step_category_and_usage_limit_text`, `test_seed_card_uses_race_field_for_a_quick_play_spell`, `test_seed_card_uses_race_field_for_a_counter_trap`, `test_seed_card_creates_one_row_per_effect_for_a_multi_effect_card`.

**Second, fix the LLM response queues.** `resolve_effect_clauses` no longer makes an LLM call to *produce* the split (that was `split_effect_clauses`, deleted in Task 10) — it only calls `score_split_confidence`, and only when sentence-splitting produces more than one clause. Every one of the first 8 tests above has a `desc` that sentence-splits into exactly one clause (a single sentence, or — for Effect Veiler — two sentences where the second is a usage-limit sentence that gets removed, leaving one real clause), so `score_split_confidence` is never called for them either. **Delete the first `llm_client.queue_response(desc)` line from each of those 8 tests** — each needs only the review-confidence response(s) it already queues after that line.

For `test_seed_card_creates_one_row_per_effect_for_a_multi_effect_card` (Baronne de Fleur), the sentence splitter produces 4 sentences: `effect_1`, `effect_2`'s actual Quick Effect text, the trailing `'You can only use the previous effect of "Baronne de Fleur" once per turn.'` sentence (a usage-limit sentence — no "preceding"/"following" pointer, but it does contain the word "effect" and isn't "these effects", so it falls to the self-scope default and attaches to the clause immediately before it), and `effect_3`. Removing the usage-limit sentence leaves exactly 3 real clauses — matching the test's existing `len(rows) == 3` assertion — so `score_split_confidence` *is* still called once. Replace this test's queue:

```python
    llm_client = MockLLMClient()
    llm_client.queue_response("0.95")  # split-quality confidence
    llm_client.queue_response("0.97")  # review confidence for effect 1
    llm_client.queue_response("0.97")  # review confidence for effect 2
    llm_client.queue_response("0.97")  # review confidence for effect 3
```

(this drops only the old first line, `llm_client.queue_response(f"{effect_1}\n---\n{effect_2}\n---\n{effect_3}")` — the four responses that follow are unchanged.)

Also add to this test's assertions (the usage-limit scope resolution is new behavior worth locking in given this card is the design's own multi-effect stress case):

```python
    from aijudge.db.effects_repo import get_confirmed_effects

    effects = get_confirmed_effects(card_id)
    quick_effect = next(e for e in effects if e["effect_type"] == "quick")
    assert quick_effect["usage_limit_text"] == 'You can only use the previous effect of "Baronne de Fleur" once per turn.'
```

- [ ] **Step 2: Write the new tests**

Add to `tests/ingestion/test_seed.py`:

```python
def test_seed_card_ineligible_card_gets_single_unclassified_row():
    from aijudge.db.cards_repo import get_card_by_name
    from aijudge.db.effects_repo import get_confirmed_effects
    from aijudge.ingestion.seed import seed_card
    from aijudge.llm.client import MockLLMClient

    desc = "Must be Fusion Summoned and cannot be Special Summoned by other ways."

    def fake_fetch_card(name, http_get=None):
        return {
            "id": 1,
            "name": name,
            "type": "Fusion Monster",
            "desc": desc,
            "card_sets": [{"set_name": "Old Set"}],
        }

    def fake_fetch_rulings(name, http_get=None):
        return []

    llm_client = MockLLMClient()  # no queued responses -- must never be called

    card_id = seed_card(
        "Pre-PSCT Card",
        llm_client=llm_client,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=fake_fetch_rulings,
        fetch_sets_index_fn=lambda: {"Old Set": date(2005, 1, 1)},
    )

    card = get_card_by_name("Pre-PSCT Card")
    assert card["deterministic_parse_eligible"] is False
    assert get_confirmed_effects(card_id) == []

    from aijudge.db.connection import get_connection

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT effect_type, effect, status, confidence_score FROM card_effects_structured WHERE card_id = %s",
            (card_id,),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "unclassified"
    assert rows[0][1] == desc
    assert rows[0][2] == "pending"
    assert rows[0][3] == 0.0


def test_seed_card_extracts_card_material_for_extra_deck_monster():
    from aijudge.db.connection import get_connection
    from aijudge.ingestion.seed import seed_card
    from aijudge.llm.client import MockLLMClient

    desc = (
        '"Tearlaments Kitkallos" + 1 "Tearlaments" monster\n'
        "Other Aqua monsters you control cannot be destroyed by battle."
    )

    def fake_fetch_card(name, http_get=None):
        return {
            "id": 84330567,
            "name": name,
            "type": "Fusion Monster",
            "race": "Aqua",
            "desc": desc,
            "card_sets": [{"set_name": "Darkwing Blast"}],
        }

    def fake_fetch_rulings(name, http_get=None):
        return []

    llm_client = MockLLMClient()
    llm_client.queue_response("0.97")  # review confidence for the one remaining clause

    card_id = seed_card(
        "Tearlaments Rulkallos",
        llm_client=llm_client,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=fake_fetch_rulings,
        fetch_sets_index_fn=lambda: {"Darkwing Blast": date(2022, 10, 20)},
    )

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT effect_type, effect FROM card_effects_structured WHERE card_id = %s ORDER BY effect_type",
            (card_id,),
        ).fetchall()

    material_rows = [row for row in rows if row[0] == "card_material"]
    assert len(material_rows) == 1
    assert material_rows[0][1] == '"Tearlaments Kitkallos" + 1 "Tearlaments" monster'


def test_seed_card_vanilla_extra_deck_monster_inserts_only_material_row():
    from aijudge.db.connection import get_connection
    from aijudge.ingestion.seed import seed_card
    from aijudge.llm.client import MockLLMClient

    def fake_fetch_card(name, http_get=None):
        return {
            "id": 71594310,
            "name": name,
            "type": "XYZ Monster",
            "race": "Rock",
            "desc": "2 Level 4 monsters",
            "card_sets": [{"set_name": "Wing Raiders"}],
        }

    def fake_fetch_rulings(name, http_get=None):
        return []

    llm_client = MockLLMClient()  # no queued responses -- must never be called

    card_id = seed_card(
        "Gem-Knight Pearl",
        llm_client=llm_client,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=fake_fetch_rulings,
        fetch_sets_index_fn=lambda: {"Wing Raiders": date(2015, 1, 9)},
    )

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT effect_type FROM card_effects_structured WHERE card_id = %s",
            (card_id,),
        ).fetchall()

    assert len(rows) == 1
    assert rows[0][0] == "card_material"


def test_seed_card_duplicates_usage_limit_text_across_scoped_clauses():
    from aijudge.db.effects_repo import get_confirmed_effects
    from aijudge.ingestion.seed import seed_card
    from aijudge.llm.client import MockLLMClient

    desc = (
        '"Tearlaments Kitkallos" + 1 "Tearlaments" monster\n'
        "Other Aqua monsters you control cannot be destroyed by battle. You can only use "
        'each of the following effects of "Tearlaments Rulkallos" once per turn. When your '
        "opponent activates a card or effect that includes an effect that Special Summons a "
        "monster(s) (Quick Effect): You can negate the activation, and if you do, destroy "
        'it, then, send 1 "Tearlaments" card from your hand or face-up field to the GY. If '
        "this Fusion Summoned card is sent to the GY by a card effect: You can Special "
        "Summon this card."
    )

    def fake_fetch_card(name, http_get=None):
        return {
            "id": 84330567,
            "name": name,
            "type": "Fusion Monster",
            "race": "Aqua",
            "desc": desc,
            "card_sets": [{"set_name": "Darkwing Blast"}],
        }

    def fake_fetch_rulings(name, http_get=None):
        return []

    llm_client = MockLLMClient()
    llm_client.queue_response("0.95")  # score_split_confidence for the 3 post-material clauses
    llm_client.queue_response("0.97")  # review: Continuous clause
    llm_client.queue_response("0.97")  # review: Quick clause
    llm_client.queue_response("0.97")  # review: Trigger clause

    card_id = seed_card(
        "Tearlaments Rulkallos",
        llm_client=llm_client,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=fake_fetch_rulings,
        fetch_sets_index_fn=lambda: {"Darkwing Blast": date(2022, 10, 20)},
    )

    effects = get_confirmed_effects(card_id)
    by_type = {e["effect_type"]: e for e in effects}

    expected_usage_limit = 'You can only use each of the following effects of "Tearlaments Rulkallos" once per turn.'
    assert by_type["continuous"]["usage_limit_text"] is None
    assert by_type["quick"]["usage_limit_text"] == expected_usage_limit
    assert by_type["trigger"]["usage_limit_text"] == expected_usage_limit
```

- [ ] **Step 3: Run tests to verify they fail**

Bring up the DB first (`docker compose up -d db`, `.env` present, `DATABASE_URL` exported).
Run: `pytest tests/ingestion/test_seed.py -v`
Expected: FAIL — current `seed_card` doesn't call the eligibility gate or material extraction, and `resolve_effect_clauses` still returns a plain list (not a tuple), so `clauses, scopes = resolve_effect_clauses(...)` raises `ValueError: too many values to unpack` for every test, new and pre-existing alike, until Step 4 lands.

- [ ] **Step 4: Implement**

Replace `src/aijudge/ingestion/seed.py`:

```python
from datetime import date, datetime, timezone
from typing import Callable

from aijudge.db.cards_repo import insert_card
from aijudge.db.effects_repo import confirm_effect, insert_pending_effect
from aijudge.db.rulings_repo import insert_ruling
from aijudge.effect_parser.clause_splitter import resolve_effect_clauses
from aijudge.effect_parser.parser import classify_damage_step_category, classify_effect_type, parse_psct
from aijudge.effect_parser.review_agent import review_parsed_effect
from aijudge.effect_parser.sentence_splitter import extract_card_material
from aijudge.effect_parser.usage_limit import resolve_ambiguous_scope
from aijudge.ingestion.printing_eligibility import fetch_sets_index, is_deterministic_parse_eligible
from aijudge.ingestion.ygoprodeck_client import fetch_card
from aijudge.ingestion.ygoresources_client import fetch_rulings
from aijudge.llm.client import LLMClient
from aijudge.rules_engine.models import EffectType

HAND_PICKED_CARDS: list[str] = [
    "Ash Blossom & Joyous Spring",
    "Called by the Grave",
    "Infinite Impermanence",
    "Effect Veiler",
    "Solemn Strike",
    "Baronne de Fleur",
    "Borreload Dragon",
]


def seed_card(
    name: str,
    *,
    llm_client: LLMClient,
    fetch_card_fn: Callable[..., dict] = fetch_card,
    fetch_rulings_fn: Callable[..., list[dict]] = fetch_rulings,
    fetch_sets_index_fn: Callable[..., dict] = fetch_sets_index,
    field: str | None = None,
) -> str:
    card_data = fetch_card_fn(name, field=field) if field is not None else fetch_card_fn(name)
    card_type = card_data["type"]
    race = card_data.get("race")
    card_text = card_data["desc"]
    card_sets = card_data.get("card_sets") or []

    sets_index = fetch_sets_index_fn()
    eligible = is_deterministic_parse_eligible(card_sets, sets_index)

    card_id = insert_card(
        name=card_data["name"],
        card_text=card_text,
        card_type=card_type,
        race=race,
        source="ygoprodeck",
        fetched_at=datetime.now(timezone.utc).date(),
        ygoprodeck_id=str(card_data["id"]),
        deterministic_parse_eligible=eligible,
    )

    misc_info = card_data.get("misc_info") or [{}]
    konami_id = misc_info[0].get("konami_id")

    try:
        rulings = fetch_rulings_fn(konami_id)
    except Exception:
        rulings = []

    for ruling in rulings:
        raw_date = ruling.get("date")
        insert_ruling(
            card_id=card_id,
            ruling_text=ruling["text"],
            source="db.ygoresources",
            ruling_date=date.fromisoformat(raw_date) if raw_date else None,
        )

    if not eligible:
        _insert_unclassified(card_id, card_text)
        return card_id

    material_text, remainder = extract_card_material(card_text, card_type=card_type)
    if material_text is not None:
        insert_pending_effect(
            card_id=card_id,
            effect_type=EffectType.CARD_MATERIAL.value,
            effect=material_text,
            confidence_score=1.0,
        )
        if not remainder:
            return card_id
    else:
        remainder = card_text

    clauses, scopes = resolve_effect_clauses(llm_client, remainder)

    usage_limit_by_clause: dict[int, str] = {}
    for scope in scopes:
        indices = (
            resolve_ambiguous_scope(llm_client, usage_limit_text=scope.text, clauses=clauses)
            if scope.ambiguous
            else scope.applies_to
        )
        for index in indices:
            usage_limit_by_clause[index] = scope.text

    for index, effect_text in enumerate(clauses):
        _insert_parsed_clause(
            llm_client,
            card_id=card_id,
            card_type=card_type,
            race=race,
            effect_text=effect_text,
            usage_limit_text=usage_limit_by_clause.get(index),
            clauses=clauses,
            usage_limit_by_clause=usage_limit_by_clause,
            index=index,
        )

    return card_id


def _insert_unclassified(card_id: str, card_text: str) -> None:
    insert_pending_effect(
        card_id=card_id,
        effect_type=EffectType.UNCLASSIFIED.value,
        effect=card_text,
        confidence_score=0.0,
    )


def _insert_parsed_clause(
    llm_client: LLMClient,
    *,
    card_id: str,
    card_type: str,
    race: str | None,
    effect_text: str,
    usage_limit_text: str | None,
    clauses: list[str],
    usage_limit_by_clause: dict[int, str],
    index: int,
) -> None:
    effect_type = classify_effect_type(effect_text, card_type=card_type, race=race)
    parsed = parse_psct(effect_text)
    damage_step_category = classify_damage_step_category(
        parsed.effect,
        activation_condition=parsed.activation_condition,
        effect_type=effect_type,
    )

    other_effects = None
    if usage_limit_text is not None:
        other_effects = [
            text
            for i, text in enumerate(clauses)
            if i != index and usage_limit_by_clause.get(i) == usage_limit_text
        ]

    review = review_parsed_effect(
        llm_client,
        raw_text=effect_text,
        activation_condition=parsed.activation_condition,
        cost=parsed.cost,
        targeting=parsed.targeting,
        effect=parsed.effect,
        damage_step_category=damage_step_category,
        other_effects=other_effects,
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


def run_seed(llm_client: LLMClient) -> list[str]:
    return [seed_card(name, llm_client=llm_client) for name in HAND_PICKED_CARDS]
```

Note: `_insert_parsed_clause` takes `clauses`/`usage_limit_by_clause`/`index` only to compute `other_effects` -- if this reads as too many parameters once written, inline the `other_effects` computation back into the `seed_card` loop and pass only the resulting `other_effects: list[str] | None` into a simpler `_insert_parsed_clause`. Either is fine; keep whichever reads more clearly once the real code is in front of you.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/ingestion/test_seed.py -v`
Expected: PASS, all tests including pre-existing ones (pre-existing tests for `Called by the Grave`-style single-effect cards should still pass unchanged, since a single-clause card takes the same code path as before, just via deterministic segmentation instead of an LLM call).

- [ ] **Step 6: Commit**

```bash
git add src/aijudge/ingestion/seed.py tests/ingestion/test_seed.py
git commit -m "refactor(ingestion): rewire seed_card to eligibility gate, Card Material, and deterministic segmentation"
```

---

### Task 15: Full-suite regression check and `HAND_PICKED_CARDS` integration smoke test

**Files:**
- Test only, no new source changes expected. If this task surfaces a gap, fix it in the relevant file from Tasks 1-14 rather than adding new logic here.

**Interfaces:**
- None new.

- [ ] **Step 1: Run the full test suite**

Run: `pytest -v`
Expected: All tests pass (DB-dependent tests skip if `DATABASE_URL` isn't set, per CLAUDE.md's documented behavior -- verify the skip count matches expectations, not an error count).

- [ ] **Step 2: Targeted trace against Baronne de Fleur and Borreload Dragon**

These are two of the seven `HAND_PICKED_CARDS` and are both Link Monsters whose material lines the *old* pipeline swept into effect text unhandled (see spec's Testing approach section). Write a one-off manual check (not a permanent test file) to confirm the new pipeline now extracts their materials correctly:

```python
from aijudge.effect_parser.sentence_splitter import extract_card_material
from aijudge.ingestion.ygoprodeck_client import fetch_card

for name in ("Baronne de Fleur", "Borreload Dragon"):
    card = fetch_card(name)
    material, remainder = extract_card_material(card["desc"], card_type=card["type"])
    print(name, "->", repr(material))
    assert material is not None, f"{name} should have extracted materials as a Link Monster"
```

Run this as a throwaway script (`python -c "..."` or a temp file), not committed. Expected: both print a non-`None` materials string.

- [ ] **Step 3: If Step 2 reveals a gap, fix and re-run Step 1**

If either card's material extraction is empty/wrong, the most likely cause is a card_type string variant not covered by `_EXTRA_DECK_TYPE_MARKERS` (Task 5) -- check the actual `card["type"]` value printed and extend the marker tuple if needed, with a matching test added to `tests/effect_parser/test_sentence_splitter.py`.

- [ ] **Step 4: No commit for this task**

This task is verification only (a dry-run check via `extract_card_material`, not a real seed). If Step 3 required a fix, that fix gets its own commit under the task it belongs to (amend the relevant task's commit message context, or add a small follow-up commit referencing which task's module it fixes).

---

### Task 16: Re-seed Baronne de Fleur and Borreload Dragon with the new pipeline

**This is a data operation against the local dev database, not a code change** — no new source files, no git commit of source. Decided after the spec's initial approval (see spec's "Explicitly out of scope" section, updated note): these two Link Monsters are the design's own multi-effect/material stress cases, and Task 15's Step 2 only proved `extract_card_material` works in isolation — it never touched the database or exercised the full rewired `seed_card`. This task actually replaces their existing (pre-redesign) rows.

**Prerequisites:** Docker Postgres up (`docker compose up -d db`), migrations run, and a local Ollama server running with the `qwen3:8b` and `all-minilm` models pulled (same setup `python -m aijudge` needs — see CLAUDE.md). This task makes real LLM calls (local, $0 cost via Ollama) and a real YGOPRODeck API call per card — it is not mocked.

**Files:**
- None modified. Verification only confirms the existing Tasks 1-14 implementation behaves correctly against these two real cards.

- [ ] **Step 1: Confirm both cards currently exist from the old pipeline**

```python
from aijudge.db.cards_repo import get_card_by_name

for name in ("Baronne de Fleur", "Borreload Dragon"):
    card = get_card_by_name(name)
    assert card is not None, f"{name} should already be seeded from before this redesign"
    print(name, "existing card_id:", card["id"])
```

- [ ] **Step 2: Delete their existing rows**

No `delete_card` function exists in `cards_repo.py` (nothing in the codebase deletes cards today) — this is a one-off maintenance operation, so use raw SQL directly rather than adding permanent, otherwise-unused deletion API surface to the repo layer:

```python
from aijudge.db.connection import get_connection

with get_connection() as conn:
    for name in ("Baronne de Fleur", "Borreload Dragon"):
        row = conn.execute("SELECT id FROM cards WHERE name = %s", (name,)).fetchone()
        if row is None:
            continue
        card_id = row[0]
        conn.execute("DELETE FROM card_effects_structured WHERE card_id = %s", (card_id,))
        conn.execute("DELETE FROM rulings WHERE card_id = %s", (card_id,))
        conn.execute("DELETE FROM card_errata_versions WHERE card_id = %s", (card_id,))
        conn.execute("DELETE FROM cards WHERE id = %s", (card_id,))
    conn.commit()
```

(deleted in FK-dependency order — `cards.id` is referenced by all three other tables with no `ON DELETE CASCADE`, so deleting `cards` first would fail with a foreign key violation)

- [ ] **Step 3: Re-seed both cards with the real pipeline**

```python
from aijudge.ingestion.seed import seed_card
from aijudge.llm.client import OllamaLLMClient

llm_client = OllamaLLMClient()
for name in ("Baronne de Fleur", "Borreload Dragon"):
    card_id = seed_card(name, llm_client=llm_client)
    print(name, "-> new card_id:", card_id)
```

- [ ] **Step 4: Verify the new rows look right**

```python
from aijudge.db.cards_repo import get_card_by_name
from aijudge.db.effects_repo import get_confirmed_effects

for name in ("Baronne de Fleur", "Borreload Dragon"):
    card = get_card_by_name(name)
    assert card["deterministic_parse_eligible"] is True

    from aijudge.db.connection import get_connection
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT effect_type, status FROM card_effects_structured WHERE card_id = %s",
            (card["id"],),
        ).fetchall()

    material_rows = [r for r in rows if r[0] == "card_material"]
    assert len(material_rows) == 1, f"{name} should have exactly one Card Material row"
    print(name, "rows:", rows)
    print(name, "confirmed effects:", get_confirmed_effects(card["id"]))
```

Manually inspect the printed output: both cards should show one `card_material` row plus their real effect rows (Baronne de Fleur: 3 effects per CLAUDE.md's description of it as the clause-splitter's stress case; Borreload Dragon: whatever its real PSCT text decomposes into). Any row left `pending` (not auto-confirmed) is not a failure — it just means that clause's review confidence came in under `DEFAULT_CONFIDENCE_THRESHOLD` (0.75) and needs eventual human review, same as any other seeded card.

- [ ] **Step 5: No git commit for this task**

Nothing here is a source change. If Step 4 reveals a real bug (wrong classification, missing material extraction, wrong usage-limit scope), fix it in the relevant Task 1-14 file, add a regression test there, commit that fix under its own task, then re-run Steps 2-4 of this task.

---

## Notes for the executor

- `HAND_PICKED_CARDS` as a whole is not re-seeded as part of this plan — only Baronne de Fleur and Borreload Dragon (Task 16), per the spec's updated "Explicitly out of scope" note. The other 5 cards' existing rows are untouched.
- Every DB-touching test (`tests/db/*`, `tests/orchestration/test_preflight_db.py`) auto-skips without `DATABASE_URL` set — bring up `docker compose up -d db` and run migrations before Task 12 if you want those to actually execute rather than skip.
- Tasks 1-11 are pure-Python and require no DB; Tasks 12-14 need a running DB to fully verify (though 13-14's non-DB logic can still be unit-tested with faked repo functions per each existing test file's established pattern). Task 16 additionally needs a running local Ollama server, and is the only task in this plan that isn't a code change.
