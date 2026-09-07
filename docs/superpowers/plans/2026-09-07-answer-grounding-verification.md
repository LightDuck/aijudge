# Answer Grounding Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `run_loop` from returning a `FinalAnswer` whose prose contradicts the stored, verbatim effect text of a cited card that has confirmed structured effects.

**Architecture:** After a `FinalAnswer` clears the existing `compute_confidence` gate, a new structured-grounding verification step makes one extra LLM call — only when the answer cites a card with confirmed structured effects — asking a strict yes/no question about whether the drafted prose matches the stored effect text. A "no" feeds corrective context back into the conversation and lets the LLM redraft `FINAL`, bounded by a small retry budget; exhausting the budget escalates to a human judge, exactly like a low confidence score does today.

**Tech Stack:** Python 3.14, pytest, the existing `LLMClient` protocol (`src/aijudge/llm/client.py`) and its `MockLLMClient` test double — no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-07-answer-grounding-verification-design.md`

## Global Constraints

- Scope is structured-effect cards only — `get_rulings`/`search_rulebook` citations are not verified (per spec's Scope section).
- The verifier LLM call must use its own minimal system prompt, never `protocol.build_system_prompt()` (per spec's Component 2).
- `parse_verification_response` is fail-closed: only an exact `"YES"` (case-insensitive, trimmed) is a pass; anything else is a failure (per spec's Component 2).
- No new dependency, no feature flag to disable the gate (per spec's "Out of scope / deferred").
- `MAX_VERIFICATION_RETRIES` is a separate budget from `MAX_MALFORMED_RETRIES` — do not share or reuse that counter (per spec's Component 3).

---

## Task 1: Track structured effects per cited id in `SignalState`

**Files:**
- Modify: `src/aijudge/orchestration/confidence.py`
- Test: `tests/orchestration/test_confidence.py`

**Interfaces:**
- Produces: `SignalState.structured_effects: dict[str, list[dict]]` — maps a known citation id (`"card:<id>"` and, when present, `"card:<ygoprodeck_id>"`) to that card's `confirmed_effects` list, exactly as passed into `update_signals`. A card with no confirmed effects has no entry (not an empty list) — callers must use `.get(id, [])` or check membership, never assume every known card id has a key.

- [ ] **Step 1: Write the failing tests**

Add to `tests/orchestration/test_confidence.py` (after the existing `test_update_signals_registers_ygoprodeck_id_as_citable_alias_for_card` test, around line 138):

```python
def test_update_signals_tracks_structured_effects_for_card():
    state = SignalState()
    effects = [{"effect": "Target 1 Effect Monster your opponent controls; negate its effects."}]
    update_signals(state, "lookup_card", {"found": True, "id": "abc", "confirmed_effects": effects})
    assert state.structured_effects["card:abc"] == effects


def test_update_signals_tracks_structured_effects_under_passcode_alias_too():
    state = SignalState()
    effects = [{"effect": "..."}]
    update_signals(
        state,
        "lookup_card",
        {"found": True, "id": "abc", "ygoprodeck_id": "32896829", "confirmed_effects": effects},
    )
    assert state.structured_effects["card:abc"] == effects
    assert state.structured_effects["card:32896829"] == effects


def test_update_signals_does_not_add_structured_effects_entry_when_missing():
    state = SignalState()
    update_signals(state, "lookup_card", {"found": True, "id": "abc", "confirmed_effects": []})
    assert "card:abc" not in state.structured_effects
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/orchestration/test_confidence.py -k structured_effects -v`
Expected: FAIL — `AttributeError`-shaped failure via `KeyError`/`AssertionError` since `SignalState` has no `structured_effects` field yet (accessing `state.structured_effects` raises `AttributeError`).

- [ ] **Step 3: Add the field and populate it**

In `src/aijudge/orchestration/confidence.py`, add the new field to `SignalState`:

```python
@dataclass
class SignalState:
    known_ids: set[str] = field(default_factory=set)
    citation_index: dict[str, dict] = field(default_factory=dict)
    structured_effects: dict[str, list[dict]] = field(default_factory=dict)
    missing_structured_effect: bool = False
    retrieval_gap: bool = False
```

Replace the `lookup_card` branch of `update_signals` (currently):

```python
    if tool_name == "lookup_card":
        if result.get("found"):
            card_id = f"card:{result['id']}"
            citation = {
                "label": result.get("name", ""),
                "text": result.get("card_text", ""),
            }
            state.known_ids.add(card_id)
            state.citation_index[card_id] = citation
            ygoprodeck_id = result.get("ygoprodeck_id")
            if ygoprodeck_id:
                # The LLM sometimes cites a card by its real-world passcode
                # instead of (or alongside) the internal id lookup_card
                # returned -- both identify the same already-grounded card,
                # so both must count as known rather than one looking
                # fabricated next to the other.
                passcode_id = f"card:{ygoprodeck_id}"
                state.known_ids.add(passcode_id)
                state.citation_index[passcode_id] = citation
            if not result.get("confirmed_effects"):
                state.missing_structured_effect = True
```

with:

```python
    if tool_name == "lookup_card":
        if result.get("found"):
            card_id = f"card:{result['id']}"
            citation = {
                "label": result.get("name", ""),
                "text": result.get("card_text", ""),
            }
            state.known_ids.add(card_id)
            state.citation_index[card_id] = citation
            confirmed_effects = result.get("confirmed_effects")
            if confirmed_effects:
                state.structured_effects[card_id] = confirmed_effects
            else:
                state.missing_structured_effect = True
            ygoprodeck_id = result.get("ygoprodeck_id")
            if ygoprodeck_id:
                # The LLM sometimes cites a card by its real-world passcode
                # instead of (or alongside) the internal id lookup_card
                # returned -- both identify the same already-grounded card,
                # so both must count as known rather than one looking
                # fabricated next to the other.
                passcode_id = f"card:{ygoprodeck_id}"
                state.known_ids.add(passcode_id)
                state.citation_index[passcode_id] = citation
                if confirmed_effects:
                    state.structured_effects[passcode_id] = confirmed_effects
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/orchestration/test_confidence.py -v`
Expected: PASS — all tests in the file, including the pre-existing ones (this change is additive/reordering only, no existing assertion changes).

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/orchestration/confidence.py tests/orchestration/test_confidence.py
git commit -m "feat(orchestration): track structured effects per cited id in SignalState"
```

---

## Task 2: `orchestration/verify.py` — the verification primitives

**Files:**
- Create: `src/aijudge/orchestration/verify.py`
- Test: `tests/orchestration/test_verify.py`

**Interfaces:**
- Consumes: `SignalState.structured_effects: dict[str, list[dict]]` (Task 1). `LLMClient.complete(prompt: str, *, system: str | None = None) -> str` (`src/aijudge/llm/client.py`).
- Produces:
  - `VerificationResult` dataclass: `ok: bool`, `mismatches: list[dict]` (each `{"card_id": str, "effect_text": str}`).
  - `VERIFIER_SYSTEM_PROMPT: str` — module-level constant, the verifier's fixed system prompt (public, not underscore-prefixed, because Task 3's loop test asserts on it directly).
  - `build_verification_prompt(answer_text: str, structured_effects: list[dict]) -> str`
  - `parse_verification_response(response: str) -> bool`
  - `verify_structured_grounding(answer_text: str, cited_ids: set[str], state: SignalState, llm_client: LLMClient) -> VerificationResult`

- [ ] **Step 1: Write the failing tests**

Create `tests/orchestration/test_verify.py`:

```python
from aijudge.llm.client import MockLLMClient
from aijudge.orchestration.confidence import SignalState
from aijudge.orchestration.verify import (
    VerificationResult,
    build_verification_prompt,
    parse_verification_response,
    verify_structured_grounding,
)


def test_build_verification_prompt_includes_effect_text_and_answer():
    prompt = build_verification_prompt(
        "It negates the effect of a spell or trap card.",
        [{"effect": "Target 1 Effect Monster your opponent controls; negate its effects."}],
    )
    assert "Target 1 Effect Monster your opponent controls; negate its effects." in prompt
    assert "It negates the effect of a spell or trap card." in prompt


def test_parse_verification_response_accepts_yes_variants():
    assert parse_verification_response("YES") is True
    assert parse_verification_response("yes") is True
    assert parse_verification_response("  Yes  ") is True


def test_parse_verification_response_rejects_anything_else():
    assert parse_verification_response("NO") is False
    assert parse_verification_response("") is False
    assert parse_verification_response("I think so") is False


def test_verify_structured_grounding_skips_when_nothing_to_check():
    llm = MockLLMClient()  # empty queue -- would raise AssertionError if complete() were called
    state = SignalState()

    result = verify_structured_grounding("Some answer.", {"card:abc"}, state, llm)

    assert result == VerificationResult(ok=True, mismatches=[])


def test_verify_structured_grounding_passes_on_yes():
    llm = MockLLMClient()
    llm.queue_response("YES")
    state = SignalState()
    state.structured_effects["card:abc"] = [{"effect": "Target 1 Effect Monster; negate its effects."}]

    result = verify_structured_grounding("It negates a targeted Effect Monster.", {"card:abc"}, state, llm)

    assert result.ok is True
    assert result.mismatches == []


def test_verify_structured_grounding_flags_mismatch_on_no():
    llm = MockLLMClient()
    llm.queue_response("NO")
    state = SignalState()
    state.structured_effects["card:abc"] = [{"effect": "Target 1 Effect Monster; negate its effects."}]

    result = verify_structured_grounding("It negates a targeted spell or trap card.", {"card:abc"}, state, llm)

    assert result.ok is False
    assert result.mismatches == [
        {"card_id": "card:abc", "effect_text": "Target 1 Effect Monster; negate its effects."}
    ]


def test_verify_structured_grounding_dedupes_id_and_passcode_alias_for_same_card():
    # card:abc and card:32896829 are the SAME card cited under two aliases --
    # state.structured_effects stores the identical list object under both
    # keys (see Task 1), so this must not double-count into two LLM calls
    # or two mismatch entries.
    llm = MockLLMClient()
    llm.queue_response("YES")
    state = SignalState()
    effects = [{"effect": "Target 1 Effect Monster; negate its effects."}]
    state.structured_effects["card:abc"] = effects
    state.structured_effects["card:32896829"] = effects

    result = verify_structured_grounding("Answer.", {"card:abc", "card:32896829"}, state, llm)

    assert result.ok is True


def test_verify_structured_grounding_uses_the_verifier_system_prompt():
    from aijudge.orchestration.verify import VERIFIER_SYSTEM_PROMPT

    llm = MockLLMClient()
    llm.queue_response("YES")
    state = SignalState()
    state.structured_effects["card:abc"] = [{"effect": "..."}]

    verify_structured_grounding("Answer.", {"card:abc"}, state, llm)

    assert llm.system_prompts == [VERIFIER_SYSTEM_PROMPT]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/orchestration/test_verify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aijudge.orchestration.verify'`.

- [ ] **Step 3: Implement `src/aijudge/orchestration/verify.py`**

```python
from dataclasses import dataclass, field

from aijudge.llm.client import LLMClient

from .confidence import SignalState

VERIFIER_SYSTEM_PROMPT = (
    "You are a strict fact-checker for a Yu-Gi-Oh! TCG rules assistant. You "
    "are given the verbatim stored text of one or more card effects and a "
    "drafted answer that describes them. Check whether the drafted answer "
    "accurately restates each effect -- the same targets, the same actions, "
    "nothing invented or swapped for something else. Respond with exactly "
    "one word: YES if the answer is accurate, NO if it misstates any of the "
    "effects."
)


@dataclass
class VerificationResult:
    ok: bool
    mismatches: list[dict] = field(default_factory=list)


def build_verification_prompt(answer_text: str, structured_effects: list[dict]) -> str:
    effect_lines = "\n".join(f"- {effect['effect']}" for effect in structured_effects)
    return (
        "STORED EFFECT TEXT (verbatim, ground truth):\n"
        f"{effect_lines}\n\n"
        "DRAFTED ANSWER:\n"
        f"{answer_text}\n\n"
        "Does the drafted answer accurately restate the stored effect text above? "
        "Respond with exactly YES or NO."
    )


def parse_verification_response(response: str) -> bool:
    return response.strip().upper() == "YES"


def verify_structured_grounding(
    answer_text: str,
    cited_ids: set[str],
    state: SignalState,
    llm_client: LLMClient,
) -> VerificationResult:
    # Dedupe by list identity, not by cited id or effect text: the same card
    # cited under both its internal id and passcode alias points to the same
    # `confirmed_effects` list object (see Task 1), and must be counted once.
    # Two different cards that happen to share identical effect text must
    # NOT be collapsed, so identity (not text equality) is the dedup key.
    seen_list_ids: set[int] = set()
    matched: list[dict] = []
    for cited_id in cited_ids:
        effects = state.structured_effects.get(cited_id)
        if not effects or id(effects) in seen_list_ids:
            continue
        seen_list_ids.add(id(effects))
        for effect in effects:
            matched.append({"card_id": cited_id, "effect_text": effect["effect"]})

    if not matched:
        return VerificationResult(ok=True)

    prompt = build_verification_prompt(
        answer_text, [{"effect": m["effect_text"]} for m in matched]
    )
    response = llm_client.complete(prompt, system=VERIFIER_SYSTEM_PROMPT)
    ok = parse_verification_response(response)
    return VerificationResult(ok=ok, mismatches=[] if ok else matched)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/orchestration/test_verify.py -v`
Expected: PASS — all 8 tests.

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/orchestration/verify.py tests/orchestration/test_verify.py
git commit -m "feat(orchestration): add structured-effect grounding verification"
```

---

## Task 3: Wire the verification gate into `run_loop`

**Files:**
- Modify: `src/aijudge/orchestration/loop.py`
- Modify: `tests/orchestration/test_loop.py`

**Interfaces:**
- Consumes: `verify_structured_grounding(answer_text, cited_ids, state, llm_client) -> VerificationResult` and `VERIFIER_SYSTEM_PROMPT` (Task 2); `SignalState.structured_effects` (Task 1).
- Produces: no new public interface — `run_loop`'s signature and `LoopResult` are unchanged. Behavior changes only for `FinalAnswer`s that cite a card with confirmed structured effects.

- [ ] **Step 1: Write the failing tests**

Add these two imports to the top of `tests/orchestration/test_loop.py`, alongside the existing imports:

```python
from aijudge.orchestration.loop import MAX_VERIFICATION_RETRIES
from aijudge.orchestration.verify import VERIFIER_SYSTEM_PROMPT
```

Then add these two new tests at the end of the file:

```python
def test_structured_grounding_mismatch_retries_then_succeeds():
    llm = MockLLMClient()
    llm.queue_response('TOOL: lookup_card {"name": "Tearlaments Sulliek"}')
    llm.queue_response("FINAL: It negates the effect of the target spell or trap card. ||CITES: card:abc123||")
    llm.queue_response("NO")
    llm.queue_response("FINAL: It negates the effects of the targeted Effect Monster. ||CITES: card:abc123||")
    llm.queue_response("YES")

    tools = {
        "lookup_card": lambda args: {
            "found": True,
            "id": "abc123",
            "name": "Tearlaments Sulliek",
            "card_text": "...",
            "confirmed_effects": [
                {"effect": "Target 1 Effect Monster your opponent controls; negate its effects."}
            ],
        }
    }

    result = run_loop("What does Tearlaments Sulliek's first effect do?", llm_client=llm, tools=tools)

    assert result.kind == "answer"
    assert result.text == "It negates the effects of the targeted Effect Monster."


def test_structured_grounding_mismatch_exhausts_retries_and_escalates():
    llm = MockLLMClient()
    llm.queue_response('TOOL: lookup_card {"name": "Tearlaments Sulliek"}')
    for _ in range(MAX_VERIFICATION_RETRIES + 1):
        llm.queue_response("FINAL: It negates the effect of the target spell or trap card. ||CITES: card:abc123||")
        llm.queue_response("NO")

    tools = {
        "lookup_card": lambda args: {
            "found": True,
            "id": "abc123",
            "confirmed_effects": [
                {"effect": "Target 1 Effect Monster your opponent controls; negate its effects."}
            ],
        }
    }

    result = run_loop("What does Tearlaments Sulliek's first effect do?", llm_client=llm, tools=tools)

    assert result.kind == "escalate"
```

Then update the 6 existing tests that supply non-empty `confirmed_effects` and reach a `FinalAnswer`, so their queued responses account for the new verifier call:

1. `test_tool_call_then_final_answer_cites_the_returned_id` — after the existing `llm.queue_response("FINAL: It negates the effect. ||CITES: card:abc123||")` line, add:
   ```python
   llm.queue_response("YES")
   ```

2. `test_malformed_tool_arguments_are_recoverable` — after its `FINAL:` queue line, add:
   ```python
   llm.queue_response("YES")
   ```

3. `test_tool_call_then_final_answer_includes_citation_text` — after its `FINAL:` queue line, add:
   ```python
   llm.queue_response("YES")
   ```

4. `test_multiple_citations_are_sorted_by_id` — after its `FINAL:` queue line, add:
   ```python
   llm.queue_response("YES")
   ```
   (Both cited cards' effects are checked in a single batched verifier call, so exactly one extra `"YES"` is needed even though two cards are cited.)

5. `test_grounded_cards_preseed_known_ids_so_direct_final_answer_is_not_fabricated` — after its `FINAL:` queue line, add:
   ```python
   llm.queue_response("YES")
   ```

6. `test_run_loop_passes_the_system_prompt_on_every_llm_call` — this test asserts the exact list of system prompts seen. After its `FINAL:` queue line, add:
   ```python
   llm.queue_response("YES")
   ```
   and change the final assertion from:
   ```python
   assert llm.system_prompts == [build_system_prompt(), build_system_prompt()]
   ```
   to:
   ```python
   assert llm.system_prompts == [build_system_prompt(), build_system_prompt(), VERIFIER_SYSTEM_PROMPT]
   ```
   (`VERIFIER_SYSTEM_PROMPT` is already imported at the top of the file per the instruction above.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/orchestration/test_loop.py -v`
Expected: FAIL — `ImportError: cannot import name 'MAX_VERIFICATION_RETRIES' from 'aijudge.orchestration.loop'` for the two new tests; the 6 modified tests fail with `MockLLMClient.complete called with no queued response` is NOT what happens yet (the gate doesn't exist), so instead they fail because the extra queued `"YES"` is simply never consumed — MockLLMClient doesn't error on leftover queue items, so those 6 will actually still PASS at this point on their original assertions. Confirm this by running just the two new tests to see the expected `ImportError`:

Run: `pytest tests/orchestration/test_loop.py -k structured_grounding_mismatch -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement the gate in `src/aijudge/orchestration/loop.py`**

Add the import (alongside the existing relative imports):

```python
from .verify import verify_structured_grounding
```

Add the constant, alongside the existing two:

```python
MAX_MALFORMED_RETRIES = 3
MAX_TOOL_CALLS = 10
MAX_VERIFICATION_RETRIES = 2
```

Initialize the counter alongside the existing ones in `run_loop`:

```python
    malformed_count = 0
    tool_call_count = 0
    verification_retry_count = 0
```

Replace the final block (currently):

```python
        assert isinstance(parsed, FinalAnswer)
        score = compute_confidence(parsed.cited_ids, state)
        logger.debug(
            "FinalAnswer cited_ids=%s known_ids=%s retrieval_gap=%s missing_structured_effect=%s score=%.2f threshold=%.2f",
            parsed.cited_ids, state.known_ids, state.retrieval_gap, state.missing_structured_effect, score, threshold,
        )
        if score < threshold:
            return LoopResult(kind="escalate", text=ESCALATE_MESSAGE)
        citations = [state.citation_index[cid] for cid in sorted(parsed.cited_ids)]
        return LoopResult(kind="answer", text=parsed.text, citations=citations)
```

with:

```python
        assert isinstance(parsed, FinalAnswer)
        score = compute_confidence(parsed.cited_ids, state)
        logger.debug(
            "FinalAnswer cited_ids=%s known_ids=%s retrieval_gap=%s missing_structured_effect=%s score=%.2f threshold=%.2f",
            parsed.cited_ids, state.known_ids, state.retrieval_gap, state.missing_structured_effect, score, threshold,
        )
        if score < threshold:
            return LoopResult(kind="escalate", text=ESCALATE_MESSAGE)

        verification = verify_structured_grounding(parsed.text, parsed.cited_ids, state, llm_client)
        if not verification.ok:
            verification_retry_count += 1
            logger.debug(
                "structured grounding verification failed (retry_count=%d): %s",
                verification_retry_count, verification.mismatches,
            )
            if verification_retry_count > MAX_VERIFICATION_RETRIES:
                logger.debug("verification retry budget exceeded -> escalate")
                return LoopResult(kind="escalate", text=ESCALATE_MESSAGE)
            mismatch_lines = "\n".join(
                f"- {m['card_id']}: \"{m['effect_text']}\"" for m in verification.mismatches
            )
            conversation += (
                "\n\nVERIFICATION_FAILED: your answer's description doesn't match the "
                "stored effect text below. Revise your FINAL answer to accurately "
                f"reflect it.\n{mismatch_lines}"
            )
            continue

        citations = [state.citation_index[cid] for cid in sorted(parsed.cited_ids)]
        return LoopResult(kind="answer", text=parsed.text, citations=citations)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/orchestration/test_loop.py -v`
Expected: PASS — all tests, including the 6 modified ones and the 2 new ones.

- [ ] **Step 5: Run the full test suite**

Run: `pytest`
Expected: PASS. (DB-dependent tests auto-skip without `DATABASE_URL` set, per CLAUDE.md — that's expected, not a failure.)

- [ ] **Step 6: Commit**

```bash
git add src/aijudge/orchestration/loop.py tests/orchestration/test_loop.py
git commit -m "feat(orchestration): retry or escalate on structured grounding mismatch"
```
