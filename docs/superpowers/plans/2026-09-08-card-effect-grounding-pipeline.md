# Card-Effect Grounding Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make card lookup mandatory and deterministic for every card-effect question (instead of an LLM-discretionary `TOOL: lookup_card` call), so the LLM can no longer answer from its own memory ungrounded — closing the structural gap where a lone `FINAL:` with zero tool calls and empty citations scored a perfect confidence of `1.0`.

**Architecture:** New modules (`extraction.py`, `card_resolution.py`, `card_effect_pipeline.py`) implement local-match-first, LLM-extraction-on-miss card resolution, feeding a restricted answering turn (`run_loop` called with `tools={}` and a new no-fabrication system prompt) for every card-effect question — local matches and freshly-extracted ones alike. A hardened `compute_confidence` rule makes citing nothing while grounding data exists an automatic `0.0`.

**Tech Stack:** Python, pytest, `MockLLMClient`/`MockEmbeddingClient` test doubles, existing `psycopg`-backed `db/` repos (untouched by this plan).

**Spec:** `docs/superpowers/specs/2026-09-08-card-effect-grounding-pipeline-design.md`

## Global Constraints

- TDD throughout: a failing test precedes every implementation change (project convention, CLAUDE.md).
- Branch off `dev` for this implementation work (per CLAUDE.md git workflow) — this plan itself and its spec are already committed to `dev`; the *code* changes below happen on a new branch/worktree.
- Every existing test that breaks as a *direct, deliberate* consequence of a task's change must be fixed in that same task — never left red for a later task.
- No behavior described here touches `resolve_chain`, `search_rulebook`, or `get_rulings` — those stay wired exactly as they are today, just unused by the restricted answering turn (per spec Scope: suspended, not deleted).

---

## Task 1: Card-name extraction (`extraction.py`)

**Files:**
- Create: `src/aijudge/orchestration/extraction.py`
- Test: `tests/orchestration/test_extraction.py`

**Interfaces:**
- Produces: `EXTRACTION_SYSTEM_PROMPT: str`, `build_extraction_prompt(question: str) -> str`, `parse_extraction_response(response: str) -> list[str]`, `extract_card_names(question: str, *, llm_client: LLMClient) -> list[str]`. Later tasks (Task 6) call `extract_card_names`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/orchestration/test_extraction.py
from aijudge.llm.client import MockLLMClient
from aijudge.orchestration.extraction import (
    EXTRACTION_SYSTEM_PROMPT,
    build_extraction_prompt,
    extract_card_names,
    parse_extraction_response,
)


def test_build_extraction_prompt_includes_the_question():
    prompt = build_extraction_prompt("What does Tearlaments Scream do?")
    assert "What does Tearlaments Scream do?" in prompt


def test_parse_extraction_response_returns_empty_list_for_none():
    assert parse_extraction_response("NONE") == []


def test_parse_extraction_response_tolerates_trailing_punctuation_and_case():
    assert parse_extraction_response("none.") == []
    assert parse_extraction_response("None!") == []


def test_parse_extraction_response_returns_empty_list_for_blank_response():
    assert parse_extraction_response("") == []
    assert parse_extraction_response("   ") == []


def test_parse_extraction_response_returns_single_name():
    assert parse_extraction_response("Tearlaments Scream") == ["Tearlaments Scream"]


def test_parse_extraction_response_returns_multiple_names_one_per_line():
    assert parse_extraction_response("Tearlaments Scream\nTearlaments Sulliek") == [
        "Tearlaments Scream",
        "Tearlaments Sulliek",
    ]


def test_parse_extraction_response_strips_bullet_markers():
    assert parse_extraction_response("- Tearlaments Scream\n- Tearlaments Sulliek") == [
        "Tearlaments Scream",
        "Tearlaments Sulliek",
    ]


def test_parse_extraction_response_strips_numbered_list_markers():
    assert parse_extraction_response("1. Tearlaments Scream\n2) Tearlaments Sulliek") == [
        "Tearlaments Scream",
        "Tearlaments Sulliek",
    ]


def test_parse_extraction_response_strips_surrounding_quotes():
    assert parse_extraction_response('"Tearlaments Scream"') == ["Tearlaments Scream"]


def test_extract_card_names_calls_llm_with_extraction_system_prompt():
    llm = MockLLMClient()
    llm.queue_response("Tearlaments Scream")

    names = extract_card_names("What does Tearlaments Scream do?", llm_client=llm)

    assert names == ["Tearlaments Scream"]
    assert llm.system_prompts == [EXTRACTION_SYSTEM_PROMPT]


def test_extract_card_names_returns_empty_list_when_llm_says_none():
    llm = MockLLMClient()
    llm.queue_response("NONE")

    names = extract_card_names("What is the SEGOC rule?", llm_client=llm)

    assert names == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/orchestration/test_extraction.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aijudge.orchestration.extraction'`

- [ ] **Step 3: Write the implementation**

```python
# src/aijudge/orchestration/extraction.py
import re

from aijudge.llm.client import LLMClient

EXTRACTION_SYSTEM_PROMPT = (
    "You extract Yu-Gi-Oh! TCG card names from a user's question. List "
    "every card name the question references, complete or partial, one "
    "per line, and nothing else. If the question does not reference any "
    "card by name, respond with exactly NONE."
)

_BULLET_RE = re.compile(r"^[\s\-\*]*(?:\d+[.\)]\s*)?")


def build_extraction_prompt(question: str) -> str:
    return f"Question: {question}"


def parse_extraction_response(response: str) -> list[str]:
    lines = [line.strip() for line in response.strip().splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return []
    if len(lines) == 1 and lines[0].strip(".! \t").upper() == "NONE":
        return []
    names = []
    for line in lines:
        cleaned = _BULLET_RE.sub("", line).strip().strip("\"'")
        if cleaned and cleaned.upper() != "NONE":
            names.append(cleaned)
    return names


def extract_card_names(question: str, *, llm_client: LLMClient) -> list[str]:
    response = llm_client.complete(build_extraction_prompt(question), system=EXTRACTION_SYSTEM_PROMPT)
    return parse_extraction_response(response)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/orchestration/test_extraction.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/orchestration/extraction.py tests/orchestration/test_extraction.py
git commit -m "feat: add card-name extraction for the mandatory grounding pipeline"
```

---

## Task 2: Deterministic per-name card resolution (`card_resolution.py`)

**Files:**
- Create: `src/aijudge/orchestration/card_resolution.py`
- Test: `tests/orchestration/test_card_resolution.py`

**Interfaces:**
- Consumes: `aijudge.db.cards_repo.get_card_by_id(card_id: str) -> dict | None`, `aijudge.orchestration.tools.lookup_card(args, *, llm_client, online_ingest_enabled=False, ..., on_ingest_start=None) -> dict`.
- Produces: `CardResolution(name: str, status: str, card: dict | None = None)` dataclass — `status` is `"resolved" | "not_found" | "ambiguous"`; `card` is the **raw card row** (as `get_card_by_id` returns it — includes `race`), never `lookup_card`'s trimmed result, because `preflight.build_known_facts_context` reads `card["race"]` for correct spell-speed classification and `lookup_card`'s own return shape omits it. `resolve_named_cards(names: list[str], *, llm_client, online_ingest_enabled=True, on_ingest_start=None, lookup_card_fn=lookup_card, get_card_by_id_fn=get_card_by_id) -> list[CardResolution]`. Task 6 consumes both.

- [ ] **Step 1: Write the failing tests**

```python
# tests/orchestration/test_card_resolution.py
from aijudge.orchestration.card_resolution import CardResolution, resolve_named_cards


def test_resolve_named_cards_marks_found_card_as_resolved_and_refetches_raw_row():
    # The raw row must come from get_card_by_id, not lookup_card's own
    # trimmed result -- lookup_card's shape lacks `race`, which
    # build_known_facts_context needs for correct spell-speed
    # classification (see CLAUDE.md's cards.race notes).
    raw_row = {"id": "abc", "name": "Tearlaments Scream", "card_text": "...", "race": None}

    def fake_lookup_card(args, **kwargs):
        return {"found": True, "id": "abc", "name": "Tearlaments Scream"}

    def fake_get_card_by_id(card_id):
        assert card_id == "abc"
        return raw_row

    resolutions = resolve_named_cards(
        ["Tearlaments Scream"],
        llm_client=None,
        lookup_card_fn=fake_lookup_card,
        get_card_by_id_fn=fake_get_card_by_id,
    )

    assert resolutions == [CardResolution(name="Tearlaments Scream", status="resolved", card=raw_row)]


def test_resolve_named_cards_marks_missing_card_as_not_found():
    resolutions = resolve_named_cards(
        ["Nonexistent Card"],
        llm_client=None,
        lookup_card_fn=lambda args, **kwargs: {"found": False},
        get_card_by_id_fn=lambda card_id: None,
    )

    assert resolutions == [CardResolution(name="Nonexistent Card", status="not_found")]


def test_resolve_named_cards_marks_ambiguous_match_as_ambiguous():
    resolutions = resolve_named_cards(
        ["Tearlaments"],
        llm_client=None,
        lookup_card_fn=lambda args, **kwargs: {"found": False, "ambiguous": True},
        get_card_by_id_fn=lambda card_id: None,
    )

    assert resolutions == [CardResolution(name="Tearlaments", status="ambiguous")]


def test_resolve_named_cards_resolves_each_name_independently():
    def fake_lookup_card(args, **kwargs):
        if args["name"] == "Tearlaments Scream":
            return {"found": True, "id": "abc", "name": "Tearlaments Scream"}
        return {"found": False}

    resolutions = resolve_named_cards(
        ["Tearlaments Scream", "Tearlaments Scrimm"],
        llm_client=None,
        lookup_card_fn=fake_lookup_card,
        get_card_by_id_fn=lambda card_id: {"id": "abc", "name": "Tearlaments Scream"},
    )

    assert [r.status for r in resolutions] == ["resolved", "not_found"]


def test_resolve_named_cards_threads_online_ingest_enabled_and_on_ingest_start_to_lookup_card():
    captured = {}

    def fake_lookup_card(args, *, llm_client, online_ingest_enabled, on_ingest_start):
        captured["online_ingest_enabled"] = online_ingest_enabled
        captured["on_ingest_start"] = on_ingest_start
        return {"found": False}

    def on_ingest_start(name):
        return None

    resolve_named_cards(
        ["Some Card"],
        llm_client=None,
        online_ingest_enabled=False,
        on_ingest_start=on_ingest_start,
        lookup_card_fn=fake_lookup_card,
        get_card_by_id_fn=lambda card_id: None,
    )

    assert captured["online_ingest_enabled"] is False
    assert captured["on_ingest_start"] is on_ingest_start
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/orchestration/test_card_resolution.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aijudge.orchestration.card_resolution'`

- [ ] **Step 3: Write the implementation**

```python
# src/aijudge/orchestration/card_resolution.py
from dataclasses import dataclass
from typing import Callable

from aijudge.db.cards_repo import get_card_by_id
from aijudge.llm.client import LLMClient
from aijudge.orchestration.tools import lookup_card


@dataclass
class CardResolution:
    name: str
    status: str  # "resolved" | "not_found" | "ambiguous"
    card: dict | None = None  # raw card row (get_card_by_id shape), only when status == "resolved"


def resolve_named_cards(
    names: list[str],
    *,
    llm_client: LLMClient,
    online_ingest_enabled: bool = True,
    on_ingest_start: Callable[[str], None] | None = None,
    lookup_card_fn: Callable[..., dict] = lookup_card,
    get_card_by_id_fn: Callable[[str], dict | None] = get_card_by_id,
) -> list[CardResolution]:
    resolutions = []
    for name in names:
        result = lookup_card_fn(
            {"name": name},
            llm_client=llm_client,
            online_ingest_enabled=online_ingest_enabled,
            on_ingest_start=on_ingest_start,
        )
        if result.get("ambiguous"):
            resolutions.append(CardResolution(name=name, status="ambiguous"))
        elif result.get("found"):
            resolutions.append(
                CardResolution(name=name, status="resolved", card=get_card_by_id_fn(result["id"]))
            )
        else:
            resolutions.append(CardResolution(name=name, status="not_found"))
    return resolutions
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/orchestration/test_card_resolution.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/orchestration/card_resolution.py tests/orchestration/test_card_resolution.py
git commit -m "feat: add deterministic per-name card resolution"
```

---

## Task 3: Restricted answering-turn system prompt (`protocol.py`)

**Files:**
- Modify: `src/aijudge/orchestration/protocol.py`
- Test: `tests/orchestration/test_protocol.py`

**Interfaces:**
- Produces: `build_answering_system_prompt() -> str`. Task 7 and Task 8 pass this to `run_loop`'s new `system_prompt` parameter (Task 4).

- [ ] **Step 1: Write the failing tests**

Append to `tests/orchestration/test_protocol.py`:

```python
def test_build_answering_system_prompt_forbids_tool_calls():
    prompt = build_answering_system_prompt()
    assert "TOOL" in prompt
    assert "no tools" in prompt.lower() or "do not attempt" in prompt.lower()


def test_build_answering_system_prompt_forbids_describing_unresolved_cards_from_memory():
    prompt = build_answering_system_prompt()
    assert "memory" in prompt.lower()
    assert "LOOKUP FAILURES" in prompt


def test_build_answering_system_prompt_still_documents_final_and_refuse():
    prompt = build_answering_system_prompt()
    assert "FINAL:" in prompt
    assert "REFUSE:" in prompt
    assert "||CITES:" in prompt
```

And add `build_answering_system_prompt` to the existing `from aijudge.orchestration.protocol import (...)` block at the top of the file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/orchestration/test_protocol.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_answering_system_prompt'`

- [ ] **Step 3: Write the implementation**

Add to `src/aijudge/orchestration/protocol.py`, after `build_system_prompt`:

```python
def build_answering_system_prompt() -> str:
    return (
        "You are a Yu-Gi-Oh! TCG rules-adjudication assistant. You have "
        "already been given complete, verified information about every "
        "card this question could concern, below -- you have NO tools "
        "available in this turn. Do not attempt a 'TOOL:' line under any "
        "circumstances; it will not work. For any card listed under "
        "LOOKUP FAILURES, tell the user it was not found (a spelling "
        "check is a reasonable thing to suggest) and do NOT describe "
        "what that card might do from your own memory -- treat your own "
        "memory of what a specific card does as unreliable and never "
        "state it as fact. Respond with a line starting with 'FINAL:' "
        "followed by your answer text, then '||CITES: id1, id2||' "
        "listing every source id (card:<id>) your answer relies on -- "
        "use '||CITES: ||' if none apply. If the question is not about "
        "Yu-Gi-Oh! TCG rules or card interactions at all, respond with a "
        "line starting with 'REFUSE:' followed by a brief explanation "
        "instead. When speaking to the user about a card's 8-digit "
        "numeric identifier, always call it its 'passcode' -- never "
        "'id' or 'ygoprodeck_id', which are internal names only."
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/orchestration/test_protocol.py -v`
Expected: PASS (all tests, including the 3 new ones)

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/orchestration/protocol.py tests/orchestration/test_protocol.py
git commit -m "feat: add no-fabrication system prompt for the restricted answering turn"
```

---

## Task 4: `run_loop` accepts a `system_prompt` override (`loop.py`)

**Files:**
- Modify: `src/aijudge/orchestration/loop.py:48-57`
- Test: `tests/orchestration/test_loop.py`

**Interfaces:**
- Produces: `run_loop(..., system_prompt: str | None = None)` — `None` preserves today's default (`build_system_prompt()`) for every existing caller. Task 7/8 pass `build_answering_system_prompt()` explicitly.

- [ ] **Step 1: Write the failing tests**

Append to `tests/orchestration/test_loop.py`:

```python
def test_run_loop_uses_default_system_prompt_when_none_given():
    llm = MockLLMClient()
    llm.queue_response("FINAL: ok. ||CITES: ||")

    run_loop("A question", llm_client=llm, tools={})

    assert llm.system_prompts == [build_system_prompt()]


def test_run_loop_uses_provided_system_prompt_override():
    llm = MockLLMClient()
    llm.queue_response("FINAL: ok. ||CITES: ||")

    run_loop("A question", llm_client=llm, tools={}, system_prompt="CUSTOM PROMPT")

    assert llm.system_prompts == ["CUSTOM PROMPT"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/orchestration/test_loop.py -v -k system_prompt`
Expected: FAIL — `test_run_loop_uses_provided_system_prompt_override` fails with `TypeError: run_loop() got an unexpected keyword argument 'system_prompt'`

- [ ] **Step 3: Write the implementation**

In `src/aijudge/orchestration/loop.py`, change:

```python
def run_loop(
    question: str,
    *,
    llm_client: LLMClient,
    tools: dict[str, Callable[[dict], dict]],
    clarification_context: str = "",
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    grounded_cards: list[dict] | None = None,
) -> LoopResult:
    system_prompt = build_system_prompt()
```

to:

```python
def run_loop(
    question: str,
    *,
    llm_client: LLMClient,
    tools: dict[str, Callable[[dict], dict]],
    clarification_context: str = "",
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    grounded_cards: list[dict] | None = None,
    system_prompt: str | None = None,
) -> LoopResult:
    system_prompt = system_prompt if system_prompt is not None else build_system_prompt()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/orchestration/test_loop.py -v`
Expected: PASS (all tests, no regressions — every other test omits `system_prompt` and gets today's default)

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/orchestration/loop.py tests/orchestration/test_loop.py
git commit -m "feat: let run_loop accept a system_prompt override"
```

---

## Task 5: Harden `compute_confidence` against citing nothing when grounding exists (`confidence.py`)

**Files:**
- Modify: `src/aijudge/orchestration/confidence.py:68-77`
- Test: `tests/orchestration/test_confidence.py`, `tests/orchestration/test_loop.py`

**Interfaces:**
- Changes `compute_confidence`'s behavior only — no signature change.

This task has a real, deliberate behavior-change ripple: once `known_ids` is non-empty, an answer citing nothing now scores `0.0` instead of `1.0`/penalized-but-nonzero. One existing test in `test_loop.py` currently proves the *opposite* behavior (a citation-dropping redraft gets a second chance via `verify_structured_grounding`'s bypass-detection path) and must be rewritten, not just left broken.

- [ ] **Step 1: Write the failing tests**

Append to `tests/orchestration/test_confidence.py`:

```python
def test_compute_confidence_zero_when_known_ids_populated_but_nothing_cited():
    state = SignalState(known_ids={"card:abc"})
    assert compute_confidence(set(), state) == 0.0


def test_compute_confidence_unaffected_when_known_ids_empty_and_nothing_cited():
    state = SignalState()
    assert compute_confidence(set(), state) == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/orchestration/test_confidence.py -v -k known_ids_populated`
Expected: FAIL — `assert 1.0 == 0.0`

- [ ] **Step 3: Write the implementation**

In `src/aijudge/orchestration/confidence.py`, change:

```python
def compute_confidence(cited_ids: set[str], state: SignalState) -> float:
    if cited_ids - state.known_ids:
        return 0.0

    score = 1.0
```

to:

```python
def compute_confidence(cited_ids: set[str], state: SignalState) -> float:
    if cited_ids - state.known_ids:
        return 0.0
    if state.known_ids and not cited_ids:
        return 0.0

    score = 1.0
```

- [ ] **Step 4: Run the full confidence test file, then the full loop test file**

Run: `pytest tests/orchestration/test_confidence.py -v`
Expected: PASS (all tests, including the 2 new ones)

Run: `pytest tests/orchestration/test_loop.py -v`
Expected: FAIL — exactly one test,
`test_redraft_dropping_flagged_citation_is_treated_as_another_verification_failure_then_recovers`, now fails
because the scenario it tests (citation-dropping redraft recovers via a third draft) is no longer reachable: the
second draft's `||CITES: ||` now hard-fails at the confidence gate before `verify_structured_grounding`'s
bypass-detection logic gets a chance to offer a third attempt.

- [ ] **Step 5: Replace the now-invalid test with one proving the new behavior**

In `tests/orchestration/test_loop.py`, replace the entire
`test_redraft_dropping_flagged_citation_is_treated_as_another_verification_failure_then_recovers` function
(currently lines 357-387) with:

```python
def test_redraft_dropping_citation_entirely_after_verification_failure_escalates_immediately():
    # Behavior change from the hardened compute_confidence rule (Task 5):
    # previously a redraft that dropped the flagged citation entirely
    # (||CITES: ||) got one more chance via the verify_structured_grounding
    # bypass-detection path below (it trivially "passes" verification when
    # there's nothing cited to check, and the loop used to treat that as
    # another correctable verification failure). Now that compute_confidence
    # hard-fails any answer citing nothing while known_ids is populated
    # (closing the "cite nothing to dodge grounding checks" gap for good),
    # that citation-drop is caught earlier, at the confidence gate itself --
    # before verification, and its bypass-detection recovery, ever runs
    # again.
    llm = MockLLMClient()
    llm.queue_response('TOOL: lookup_card {"name": "Tearlaments Sulliek"}')
    llm.queue_response("FINAL: It negates the effect of the target spell or trap card. ||CITES: card:abc123||")
    llm.queue_response("NO")
    llm.queue_response("FINAL: It negates something, not sure what. ||CITES: ||")

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

    assert result.kind == "escalate"
```

Then update the comment on the neighboring `test_redraft_dropping_flagged_citation_repeatedly_exhausts_budget_and_escalates` test (its assertion, `result.kind == "escalate"`, still passes unchanged — it now escalates via the confidence gate on the very first empty-citation redraft rather than after exhausting `MAX_VERIFICATION_RETRIES`, but the outcome is the same). Change its leading comment from:

```python
    # Companion to the above: if the redraft keeps dropping the flagged
    # citation rather than ever re-citing it, the bypass-detection must
    # still respect MAX_VERIFICATION_RETRIES and escalate rather than loop
    # forever or silently return an ungrounded answer.
```

to:

```python
    # Companion to the above: repeatedly dropping the citation still ends
    # in escalate -- now via the hardened compute_confidence rule firing on
    # the very first empty-citation redraft (Task 5), rather than via
    # MAX_VERIFICATION_RETRIES exhaustion as before. The assertion is
    # unchanged; only *why* it escalates changed.
```

- [ ] **Step 6: Run the full loop test file again**

Run: `pytest tests/orchestration/test_loop.py -v`
Expected: PASS (all tests)

- [ ] **Step 7: Commit**

```bash
git add src/aijudge/orchestration/confidence.py tests/orchestration/test_confidence.py tests/orchestration/test_loop.py
git commit -m "fix: treat citing nothing as fabrication when grounding data exists"
```

---

## Task 6: The card-effect pipeline (`card_effect_pipeline.py`)

**Files:**
- Create: `src/aijudge/orchestration/card_effect_pipeline.py`
- Test: `tests/orchestration/test_card_effect_pipeline.py`

**Interfaces:**
- Consumes: `extract_card_names` (Task 1), `CardResolution`/`resolve_named_cards` (Task 2), `preflight.build_known_facts_context`/`preflight.build_grounded_result` (existing, unchanged).
- Produces: `PipelineResolution(supported: bool, context: str = "", grounded_cards: list[dict] = [])`, `build_pipeline_context(resolutions: list[CardResolution]) -> str`, `resolve_card_effect_question(question, *, llm_client, online_ingest_enabled=True, on_ingest_start=None, extract_card_names_fn=extract_card_names, resolve_named_cards_fn=resolve_named_cards, build_pipeline_context_fn=build_pipeline_context, build_grounded_result_fn=build_grounded_result) -> PipelineResolution`. Task 7 and Task 8 call `resolve_card_effect_question` (only for the 0-local-matches branch — see spec Component 7).

- [ ] **Step 1: Write the failing tests**

```python
# tests/orchestration/test_card_effect_pipeline.py
from aijudge.llm.client import MockLLMClient
from aijudge.orchestration.card_effect_pipeline import (
    PipelineResolution,
    build_pipeline_context,
    resolve_card_effect_question,
)
from aijudge.orchestration.card_resolution import CardResolution


def test_build_pipeline_context_renders_known_facts_for_resolved_cards():
    resolutions = [
        CardResolution(
            name="Tearlaments Scream",
            status="resolved",
            card={"id": "abc", "name": "Tearlaments Scream", "race": None},
        )
    ]

    context = build_pipeline_context(resolutions)

    assert "Tearlaments Scream" in context
    assert "LOOKUP FAILURES" not in context


def test_build_pipeline_context_renders_failures_block_for_unresolved_names():
    resolutions = [
        CardResolution(name="Tearlaments Scrimm", status="not_found"),
        CardResolution(name="Tearlaments", status="ambiguous"),
    ]

    context = build_pipeline_context(resolutions)

    assert (
        "LOOKUP FAILURES (deterministic -- report these to the user, do not guess their effects):"
        in context
    )
    assert '- "Tearlaments Scrimm": not_found' in context
    assert '- "Tearlaments": ambiguous' in context


def test_build_pipeline_context_omits_failures_block_when_everything_resolved():
    resolutions = [
        CardResolution(
            name="Tearlaments Scream",
            status="resolved",
            card={"id": "abc", "name": "Tearlaments Scream", "race": None},
        )
    ]

    assert "LOOKUP FAILURES" not in build_pipeline_context(resolutions)


def test_build_pipeline_context_returns_empty_string_for_no_resolutions():
    assert build_pipeline_context([]) == ""


def test_resolve_card_effect_question_returns_unsupported_when_no_names_extracted():
    llm = MockLLMClient()
    llm.queue_response("NONE")

    resolution = resolve_card_effect_question("What is the SEGOC rule?", llm_client=llm)

    assert resolution == PipelineResolution(supported=False)


def test_resolve_card_effect_question_resolves_extracted_card_and_builds_context():
    llm = MockLLMClient()
    llm.queue_response("Tearlaments Scream")

    def fake_resolve_named_cards(names, *, llm_client, online_ingest_enabled, on_ingest_start):
        assert names == ["Tearlaments Scream"]
        return [CardResolution(name="Tearlaments Scream", status="resolved", card={"id": "abc"})]

    resolution = resolve_card_effect_question(
        "What does Tearlaments Scream do?",
        llm_client=llm,
        resolve_named_cards_fn=fake_resolve_named_cards,
        build_pipeline_context_fn=lambda resolutions: "KNOWN FACTS: Tearlaments Scream",
        build_grounded_result_fn=lambda card: {"found": True, "id": card["id"], "confirmed_effects": []},
    )

    assert resolution == PipelineResolution(
        supported=True,
        context="KNOWN FACTS: Tearlaments Scream",
        grounded_cards=[{"found": True, "id": "abc", "confirmed_effects": []}],
    )


def test_resolve_card_effect_question_only_grounds_resolved_names():
    llm = MockLLMClient()
    llm.queue_response("Tearlaments Scream\nTearlaments Scrimm")

    def fake_resolve_named_cards(names, *, llm_client, online_ingest_enabled, on_ingest_start):
        return [
            CardResolution(name="Tearlaments Scream", status="resolved", card={"id": "abc"}),
            CardResolution(name="Tearlaments Scrimm", status="not_found"),
        ]

    resolution = resolve_card_effect_question(
        "Do Tearlaments Scream and Tearlaments Scrimm interact?",
        llm_client=llm,
        resolve_named_cards_fn=fake_resolve_named_cards,
        build_pipeline_context_fn=lambda resolutions: "context",
        build_grounded_result_fn=lambda card: {"found": True, "id": card["id"], "confirmed_effects": []},
    )

    assert resolution.grounded_cards == [{"found": True, "id": "abc", "confirmed_effects": []}]


def test_resolve_card_effect_question_threads_online_ingest_enabled_and_on_ingest_start():
    captured = {}

    def fake_resolve_named_cards(names, *, llm_client, online_ingest_enabled, on_ingest_start):
        captured["online_ingest_enabled"] = online_ingest_enabled
        captured["on_ingest_start"] = on_ingest_start
        return []

    def on_ingest_start(name):
        return None

    llm = MockLLMClient()
    llm.queue_response("Some Card")

    resolve_card_effect_question(
        "What does Some Card do?",
        llm_client=llm,
        online_ingest_enabled=False,
        on_ingest_start=on_ingest_start,
        resolve_named_cards_fn=fake_resolve_named_cards,
        build_pipeline_context_fn=lambda resolutions: "",
    )

    assert captured["online_ingest_enabled"] is False
    assert captured["on_ingest_start"] is on_ingest_start
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/orchestration/test_card_effect_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aijudge.orchestration.card_effect_pipeline'`

- [ ] **Step 3: Write the implementation**

```python
# src/aijudge/orchestration/card_effect_pipeline.py
from dataclasses import dataclass, field
from typing import Callable

from aijudge.llm.client import LLMClient
from aijudge.orchestration.card_resolution import CardResolution, resolve_named_cards
from aijudge.orchestration.extraction import extract_card_names
from aijudge.orchestration.preflight import build_grounded_result, build_known_facts_context


@dataclass
class PipelineResolution:
    supported: bool
    context: str = ""
    grounded_cards: list[dict] = field(default_factory=list)


def build_pipeline_context(resolutions: list[CardResolution]) -> str:
    known_facts_blocks = []
    for resolution in resolutions:
        if resolution.status == "resolved":
            block = build_known_facts_context(resolution.card)
            if block:
                known_facts_blocks.append(block)

    failures = [r for r in resolutions if r.status != "resolved"]
    parts = list(known_facts_blocks)
    if failures:
        failure_lines = [
            "LOOKUP FAILURES (deterministic -- report these to the user, do not guess their effects):"
        ]
        for r in failures:
            failure_lines.append(f'- "{r.name}": {r.status}')
        parts.append("\n".join(failure_lines))
    return "\n\n".join(parts)


def resolve_card_effect_question(
    question: str,
    *,
    llm_client: LLMClient,
    online_ingest_enabled: bool = True,
    on_ingest_start: Callable[[str], None] | None = None,
    extract_card_names_fn: Callable[..., list[str]] = extract_card_names,
    resolve_named_cards_fn: Callable[..., list[CardResolution]] = resolve_named_cards,
    build_pipeline_context_fn: Callable[[list[CardResolution]], str] = build_pipeline_context,
    build_grounded_result_fn: Callable[[dict], dict] = build_grounded_result,
) -> PipelineResolution:
    names = extract_card_names_fn(question, llm_client=llm_client)
    if not names:
        return PipelineResolution(supported=False)

    resolutions = resolve_named_cards_fn(
        names,
        llm_client=llm_client,
        online_ingest_enabled=online_ingest_enabled,
        on_ingest_start=on_ingest_start,
    )
    return PipelineResolution(
        supported=True,
        context=build_pipeline_context_fn(resolutions),
        grounded_cards=[
            build_grounded_result_fn(r.card) for r in resolutions if r.status == "resolved"
        ],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/orchestration/test_card_effect_pipeline.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/orchestration/card_effect_pipeline.py tests/orchestration/test_card_effect_pipeline.py
git commit -m "feat: compose extraction and resolution into the card-effect pipeline"
```

---

## Task 7: Wire the restricted pathway into `cli.py`

**Files:**
- Modify: `src/aijudge/cli.py` (full rewrite of `run_cli`, ~90 lines)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `resolve_card_effect_question` (Task 6), `build_answering_system_prompt` (Task 3), `run_loop`'s `system_prompt` param (Task 4), `NOT_SUPPORTED_MESSAGE` (existing, `loop.py`).
- `run_cli` gains a new injectable `resolve_card_effect_question_fn` parameter, defaulting to the real `resolve_card_effect_question`.
- `build_tool_dispatch` is no longer called by `cli.py` at all: with every `run_loop` call now using `tools={}`, the old tool dispatch (and its `on_ingest_start`/`online_ingest_enabled` wiring) has nothing left to serve. `on_ingest_start`/`online_ingest_enabled` now thread through to `resolve_card_effect_question_fn` instead.

This task changes the *outer* `run_loop` call site for **every** branch (1 local match, disambiguated match, 0 local matches) to use `tools={}` and `build_answering_system_prompt()` — per the spec's Component 7, the restricted pathway applies uniformly, not only to the 0-local-matches case. Only the 0-local-matches branch additionally calls the new pipeline for grounding.

- [ ] **Step 1: Write the failing tests**

In `tests/test_cli.py`:

**1a. Fix existing fixtures that now need a real citation** (the hardened `compute_confidence` rule from Task 5 means a grounded card with an uncited `FINAL:` now escalates instead of answering). In each of the following, change the queued `"...||CITES: ||"` response to cite the grounded card's id (`card:1` in every case below — check each test's `card`/`matches` dict for the id it actually uses, all are `"1"`):

- `test_run_cli_answers_a_question_with_no_clarification_needed` (line 58): `"FINAL: It does X. ||CITES: ||"` → `"FINAL: It does X. ||CITES: card:1||"`
- `test_run_cli_passes_the_system_prompt_to_the_clarification_call` (line 81): same fix (its assertion doesn't depend on it, but keeps the fixture realistic and consistent with every other test here)
- `test_run_cli_asks_clarification_questions_before_answering` (line 104): `"FINAL: Yes, you can respond. ||CITES: ||"` → `"FINAL: Yes, you can respond. ||CITES: card:1||"`
- `test_run_cli_disambiguates_when_multiple_cards_match` (line 146): `"FINAL: Yes. ||CITES: ||"` → `"FINAL: Yes. ||CITES: card:1||"`
- `test_run_cli_disambiguates_with_case_insensitive_fuzzy_match` (line 176): same fix
- `test_run_cli_passes_known_facts_to_the_clarification_call_for_a_single_match` (line 206): same fix
- `test_run_cli_folds_preflight_facts_in_for_a_single_match` (line 256): same fix

(`test_run_cli_prints_a_notice_when_disambiguation_answer_matches_nothing` and
`test_run_cli_direct_final_answer_citing_the_grounded_id_does_not_escalate` are unaffected — the first never
populates `grounded_cards` at all since the disambiguation answer fails to resolve, the second already cites
`card:1`.)

**1b. Rewrite the "no card matches" test** to stub the new pipeline call instead of hitting the real one (which
would otherwise consume the test's only queued LLM response as a bogus extraction call):

Replace the existing `test_run_cli_skips_the_clarification_call_when_no_card_matches` body with:

```python
def test_run_cli_skips_the_clarification_call_when_no_card_matches():
    printed = []
    inputs = iter(["what is tearlaments havnis effect?", "quit"])

    llm = MockLLMClient()
    # Only one response queued -- if the clarify pass ran anyway, it would
    # consume this response itself (leaving run_loop's own call to raise
    # AssertionError on the now-empty queue), so this asserts the skip.
    llm.queue_response("FINAL: It negates a Spell/Trap Card. ||CITES: ||")

    run_cli(
        llm,
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: [],
        resolve_card_effect_question_fn=lambda question, **kwargs: PipelineResolution(supported=True),
    )

    assert "It negates a Spell/Trap Card." in printed
```

**1c. Add a new test for the "not supported" short-circuit:**

```python
def test_run_cli_prints_not_supported_when_pipeline_finds_no_cards():
    printed = []
    inputs = iter(["what is the SEGOC rule?", "quit"])

    run_cli(
        MockLLMClient(),
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: [],
        resolve_card_effect_question_fn=lambda question, **kwargs: PipelineResolution(supported=False),
    )

    assert NOT_SUPPORTED_MESSAGE in printed
```

**1d. Add a new test proving the pipeline's context and grounded_cards actually reach `run_loop`:**

```python
def test_run_cli_uses_pipeline_context_and_grounded_cards_when_no_local_match():
    printed = []
    inputs = iter(["What does Some New Card do?", "quit"])

    llm = _CapturingLLMClient(["FINAL: It does the thing. ||CITES: card:99||", "YES"])

    def fake_resolve(question, **kwargs):
        return PipelineResolution(
            supported=True,
            context="KNOWN FACTS: Some New Card (cite as card:99)",
            grounded_cards=[
                {
                    "found": True,
                    "id": "99",
                    "name": "Some New Card",
                    "card_text": "...",
                    "confirmed_effects": [{"effect": "..."}],
                }
            ],
        )

    run_cli(
        llm,
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: [],
        resolve_card_effect_question_fn=fake_resolve,
    )

    assert "It does the thing." in printed
    assert "KNOWN FACTS: Some New Card" in llm.prompts[0]
```

**1e. Add a new test proving the restricted pathway applies to the ordinary single-local-match case too:**

```python
def test_run_cli_uses_answering_system_prompt_for_the_final_turn():
    inputs = iter(["What does Card X do?", "quit"])
    llm = _CapturingLLMClient(["PROCEED", "FINAL: It does X. ||CITES: card:1||"])
    card = {"id": "1", "name": "Card X", "card_type": "Effect Monster"}

    run_cli(
        llm,
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=lambda _: None,
        find_matched_cards_fn=lambda question: [card],
        build_known_facts_context_fn=lambda c: "",
        build_grounded_result_fn=lambda c: {"found": True, "id": c["id"], "name": c["name"], "confirmed_effects": []},
    )

    assert llm.system_prompts[0] == build_system_prompt()
    assert llm.system_prompts[1] == build_answering_system_prompt()
```

**1f. Rewrite the two ingest-wiring tests** to check the new `resolve_card_effect_question_fn` seam instead of
`build_tool_dispatch` (which `cli.py` no longer calls):

Replace `test_run_cli_wires_on_ingest_start_callback_to_print_fn` and
`test_run_cli_passes_online_ingest_enabled_through_to_tool_dispatch` with:

```python
def test_run_cli_wires_on_ingest_start_callback_and_online_ingest_enabled_to_the_pipeline():
    printed = []
    inputs = iter(["What does Some New Card do?", "quit"])
    captured = {}

    def fake_resolve(question, *, llm_client, online_ingest_enabled, on_ingest_start):
        captured["online_ingest_enabled"] = online_ingest_enabled
        on_ingest_start("Some New Card")
        return PipelineResolution(supported=False)

    run_cli(
        MockLLMClient(),
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=printed.append,
        find_matched_cards_fn=lambda question: [],
        resolve_card_effect_question_fn=fake_resolve,
    )

    assert captured["online_ingest_enabled"] is True
    assert any("Some New Card" in line for line in printed)


def test_run_cli_passes_online_ingest_enabled_false_through_to_the_pipeline():
    inputs = iter(["What does Some New Card do?", "quit"])
    captured = {}

    def fake_resolve(question, *, llm_client, online_ingest_enabled, on_ingest_start):
        captured["online_ingest_enabled"] = online_ingest_enabled
        return PipelineResolution(supported=False)

    run_cli(
        MockLLMClient(),
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=lambda _: None,
        find_matched_cards_fn=lambda question: [],
        resolve_card_effect_question_fn=fake_resolve,
        online_ingest_enabled=False,
    )

    assert captured["online_ingest_enabled"] is False
```

**1g. Update imports** at the top of `tests/test_cli.py` — replace only the existing `from aijudge...` import
block (the file has no other imports to preserve):

```python
from aijudge.cli import run_cli
from aijudge.embeddings.client import MockEmbeddingClient
from aijudge.llm.client import MockLLMClient
from aijudge.orchestration.card_effect_pipeline import PipelineResolution
from aijudge.orchestration.loop import NOT_SUPPORTED_MESSAGE
from aijudge.orchestration.protocol import build_answering_system_prompt, build_system_prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL — the citation-fixture tests fail with `result.kind == "escalate"` (nothing printed matches), the
"no card matches"/ingest tests fail because `resolve_card_effect_question_fn` isn't a real `run_cli` parameter
yet, the new tests fail with `TypeError`/`ImportError`.

- [ ] **Step 3: Write the implementation**

Replace the full contents of `src/aijudge/cli.py`:

```python
from typing import Callable

from aijudge.embeddings.client import EmbeddingClient
from aijudge.llm.client import LLMClient

from .orchestration.card_effect_pipeline import PipelineResolution, resolve_card_effect_question
from .orchestration.clarify import (
    ClarificationItem,
    build_clarification_prompt,
    clarification_prompt_text,
    format_clarification_context,
    parse_clarification_response,
)
from .orchestration.loop import NOT_SUPPORTED_MESSAGE, run_loop
from .orchestration.preflight import (
    build_grounded_result,
    build_known_facts_context,
    find_matched_cards,
    find_mentioned_card_names,
)
from .orchestration.protocol import build_answering_system_prompt, build_system_prompt


def run_cli(
    llm_client: LLMClient,
    embedding_client: EmbeddingClient,
    *,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
    find_matched_cards_fn: Callable[[str], list[dict]] = find_matched_cards,
    build_known_facts_context_fn: Callable[[dict], str] = build_known_facts_context,
    build_grounded_result_fn: Callable[[dict], dict] = build_grounded_result,
    resolve_card_effect_question_fn: Callable[..., PipelineResolution] = resolve_card_effect_question,
    online_ingest_enabled: bool = True,
) -> None:
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
        preflight_context = ""
        grounded_cards: list[dict] = []
        if len(matches) == 1:
            preflight_context = build_known_facts_context_fn(matches[0])
            grounded_cards = [build_grounded_result_fn(matches[0])]
        elif len(matches) > 1:
            names = ", ".join(match["name"] for match in matches)
            disambiguation_items.append(
                ClarificationItem(
                    kind="disambiguate_card",
                    text=f"Multiple cards match your question: {names}. Which one do you mean?",
                )
            )

        if matches:
            clarify_response = llm_client.complete(
                build_clarification_prompt(stripped, known_facts_context=preflight_context),
                system=build_system_prompt(),
            )
            items = disambiguation_items + parse_clarification_response(clarify_response)
        else:
            items = disambiguation_items
        answers = [input_fn(f"{clarification_prompt_text(item)} ") for item in items]

        if len(matches) > 1 and answers:
            candidate_names = [match["name"] for match in matches]
            matched_names = find_mentioned_card_names(answers[0], candidate_names)
            chosen = next((match for match in matches if match["name"] == matched_names[0]), None) if matched_names else None
            if chosen is not None:
                preflight_context = build_known_facts_context_fn(chosen)
                grounded_cards = [build_grounded_result_fn(chosen)]
            else:
                print_fn("Couldn't match your answer to a specific card -- proceeding without that card's confirmed details.")

        if not matches:
            # 0 local matches: try mandatory extraction + deterministic
            # lookup instead of proceeding ungrounded (the original gap).
            resolution = resolve_card_effect_question_fn(
                stripped,
                llm_client=llm_client,
                online_ingest_enabled=online_ingest_enabled,
                on_ingest_start=lambda name: print_fn(f"Looking up {name}, this may take a moment..."),
            )
            if not resolution.supported:
                print_fn(NOT_SUPPORTED_MESSAGE)
                continue
            preflight_context = resolution.context
            grounded_cards = resolution.grounded_cards

        context = format_clarification_context(items, answers)
        if preflight_context:
            context = f"{preflight_context}\n\n{context}" if context else preflight_context

        result = run_loop(
            stripped,
            llm_client=llm_client,
            tools={},
            clarification_context=context,
            grounded_cards=grounded_cards,
            system_prompt=build_answering_system_prompt(),
        )
        print_fn(result.text)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/cli.py tests/test_cli.py
git commit -m "feat: apply the restricted answering pathway to every CLI question"
```

---

## Task 8: Wire the restricted pathway into `api/app.py`

**Files:**
- Modify: `src/aijudge/api/app.py` (full rewrite, both route handlers and `create_app`'s signature)
- Test: `tests/api/test_app.py`

**Interfaces:**
- Consumes: same as Task 7.
- `create_app` gains a new injectable `resolve_card_effect_question_fn` parameter (default: the real
  `resolve_card_effect_question`) and **loses** its `tools` parameter and the `build_tool_dispatch` call — with
  every `run_loop` call now using `tools={}`, that seam has nothing left to serve.

- [ ] **Step 1: Write the failing tests**

In `tests/api/test_app.py`:

**1a. Default the new pipeline seam in the shared `_client` helper**, so every test that doesn't care about
grounding (the majority) needs no per-test change:

```python
def _client(llm: MockLLMClient, **kwargs) -> TestClient:
    kwargs.setdefault("find_matched_cards_fn", lambda question: [])
    kwargs.setdefault(
        "resolve_card_effect_question_fn",
        lambda question, **kw: PipelineResolution(supported=True),
    )
    app = create_app(llm, MockEmbeddingClient(), **kwargs)
    return TestClient(app)
```

**1b. Fix existing fixtures that now need a real citation** (same reasoning as Task 7 Step 1a — a grounded card
with an uncited `FINAL:` now escalates):

- `test_post_questions_returns_answer_when_no_clarification_needed` (line 41): `"FINAL: Ash Blossom negates that effect. ||CITES: ||"` → `"FINAL: Ash Blossom negates that effect. ||CITES: card:1||"`, and its expected response body's `"citations": []` → `"citations": [{"label": "Ash Blossom & Joyous Spring", "text": ""}]` (the test's `build_grounded_result_fn` returns no `card_text`, so the citation text defaults to `""` per `update_signals`)
- `test_post_questions_passes_the_system_prompt_to_the_clarification_call` (line 90): same citation fix (assertion doesn't depend on it, kept for fixture consistency)
- `test_post_questions_folds_known_facts_for_a_single_matched_card_into_the_llm_prompt` (line 210): `"FINAL: Yes. ||CITES: ||"` → `"FINAL: Yes. ||CITES: card:1||"`
- `test_post_questions_passes_known_facts_to_the_clarification_call_for_a_single_match` (line 237): same fix
- `test_post_questions_answer_resolves_disambiguation_answer_to_known_facts` (line 371): same fix
- `test_post_questions_answer_resolves_disambiguation_answer_case_insensitive_fuzzy` (line 409): same fix

(`test_post_questions_answer_proceeds_without_known_facts_when_disambiguation_answer_matches_nothing` and both
`..._direct_final_answer_citing_the_grounded_id_does_not_escalate` tests are unaffected, for the same reasons as
their `test_cli.py` counterparts.)

**1c. Rewrite the citation-serialization test** — it currently drives grounding through a `TOOL: lookup_card`
call via the `tools=` seam, which no longer exists (`run_loop` is always called with `tools={}` now):

Replace `test_post_questions_serializes_citation_content_without_leaking_raw_ids` with:

```python
def test_post_questions_serializes_citation_content_without_leaking_raw_ids():
    # Grounding now comes from the mandatory card-effect pipeline (no local
    # match -- resolve_card_effect_question_fn stands in for extraction +
    # lookup), not a TOOL: lookup_card call: tools are no longer available
    # to the LLM's answering turn at all.
    llm = MockLLMClient()
    llm.queue_response("FINAL: It negates the effect. ||CITES: card:abc123||")
    llm.queue_response("YES")

    def fake_resolve(question, **kwargs):
        return PipelineResolution(
            supported=True,
            context="KNOWN FACTS: Ash Blossom & Joyous Spring (cite as card:abc123)",
            grounded_cards=[
                {
                    "found": True,
                    "id": "abc123",
                    "name": "Ash Blossom & Joyous Spring",
                    "card_text": "You can discard this card...",
                    "confirmed_effects": [{"effect": "..."}],
                }
            ],
        )

    response = _client(llm, resolve_card_effect_question_fn=fake_resolve).post(
        "/questions", json={"question": "What does Ash Blossom do?"}
    )

    assert response.status_code == 200
    assert response.json()["citations"] == [
        {"label": "Ash Blossom & Joyous Spring", "text": "You can discard this card..."}
    ]
    assert "card:" not in response.text
    assert "abc123" not in response.text
```

**1d. Add `resolve_card_effect_question_fn` to the two direct-`create_app`-call tests** that bypass `_client`
and would otherwise hit the real pipeline (consuming their single queued response as a bogus extraction call):

`test_post_questions_answer_threads_clarification_context_into_llm_prompt` (around line 513) — add
`resolve_card_effect_question_fn=lambda question, **kw: PipelineResolution(supported=True)` to its
`create_app(...)` call:

```python
    response = TestClient(
        create_app(
            llm,
            MockEmbeddingClient(),
            find_matched_cards_fn=lambda question: [],
            resolve_card_effect_question_fn=lambda question, **kw: PipelineResolution(supported=True),
        )
    ).post(
```

**1e. Rewrite the two ingest-wiring tests** to check the new seam instead of `build_tool_dispatch`:

Replace `test_create_app_defaults_online_ingest_enabled_to_true` and
`test_create_app_passes_online_ingest_enabled_false_through` with:

```python
def test_create_app_defaults_online_ingest_enabled_to_true():
    captured = {}

    def fake_resolve(question, *, llm_client, online_ingest_enabled, on_ingest_start):
        captured["online_ingest_enabled"] = online_ingest_enabled
        return PipelineResolution(supported=False)

    app = create_app(
        MockLLMClient(),
        MockEmbeddingClient(),
        find_matched_cards_fn=lambda question: [],
        resolve_card_effect_question_fn=fake_resolve,
    )
    TestClient(app).post("/questions", json={"question": "What does Some New Card do?"})

    assert captured["online_ingest_enabled"] is True


def test_create_app_passes_online_ingest_enabled_false_through():
    captured = {}

    def fake_resolve(question, *, llm_client, online_ingest_enabled, on_ingest_start):
        captured["online_ingest_enabled"] = online_ingest_enabled
        return PipelineResolution(supported=False)

    app = create_app(
        MockLLMClient(),
        MockEmbeddingClient(),
        online_ingest_enabled=False,
        find_matched_cards_fn=lambda question: [],
        resolve_card_effect_question_fn=fake_resolve,
    )
    TestClient(app).post("/questions", json={"question": "What does Some New Card do?"})

    assert captured["online_ingest_enabled"] is False
```

**1f. Update imports** at the top of `tests/api/test_app.py` — replace only the existing `from aijudge...`
import block; leave the file's `import logging`, `import traceback`, `import psycopg`, `import requests`, and
`from fastapi.testclient import TestClient` lines untouched:

```python
from aijudge.api.app import create_app
from aijudge.embeddings.client import MockEmbeddingClient
from aijudge.llm.client import MockLLMClient
from aijudge.orchestration.card_effect_pipeline import PipelineResolution
from aijudge.orchestration.protocol import build_system_prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/test_app.py -v`
Expected: FAIL — citation-fixture tests fail on escalate, `tools=stub_tools` call fails with `TypeError` once
`create_app` no longer accepts `tools`, ingest tests fail since `build_tool_dispatch` is no longer monkeypatched
by anything meaningful, new/changed tests fail with `TypeError`/`ImportError`.

- [ ] **Step 3: Write the implementation**

Replace the full contents of `src/aijudge/api/app.py`:

```python
import logging
from typing import Callable

import psycopg
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from aijudge.embeddings.client import EmbeddingClient
from aijudge.llm.client import LLMClient
from aijudge.orchestration.card_effect_pipeline import PipelineResolution, resolve_card_effect_question
from aijudge.orchestration.clarify import (
    ClarificationItem,
    build_clarification_prompt,
    format_clarification_context,
    parse_clarification_response,
)
from aijudge.orchestration.loop import NOT_SUPPORTED_MESSAGE, LoopResult, run_loop
from aijudge.orchestration.preflight import (
    build_grounded_result,
    build_known_facts_context,
    find_matched_cards,
    find_mentioned_card_names,
)
from aijudge.orchestration.protocol import build_answering_system_prompt, build_system_prompt

from .schemas import AnswerRequest, NeedsClarificationResponse, QuestionRequest, ResultResponse

DEFAULT_CORS_ORIGINS = ["http://localhost:3000", "http://localhost:5173"]

logger = logging.getLogger(__name__)


def _result_response(result: LoopResult) -> dict:
    return {
        "status": result.kind,
        "text": result.text,
        "citations": result.citations if result.kind == "answer" else None,
    }


def _resolve_preflight_card(
    matches: list[dict],
    items: list[ClarificationItem],
    answers: list[str],
) -> dict | None:
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        disambiguate_index = next(
            (i for i, item in enumerate(items) if item.kind == "disambiguate_card"), None
        )
        if disambiguate_index is not None and disambiguate_index < len(answers):
            candidate_names = [match["name"] for match in matches]
            matched_names = find_mentioned_card_names(answers[disambiguate_index], candidate_names)
            return next((m for m in matches if m["name"] == matched_names[0]), None) if matched_names else None
    return None


def create_app(
    llm_client: LLMClient,
    embedding_client: EmbeddingClient,
    *,
    cors_origins: list[str] | None = None,
    find_matched_cards_fn: Callable[[str], list[dict]] | None = None,
    build_known_facts_context_fn: Callable[[dict], str] | None = None,
    build_grounded_result_fn: Callable[[dict], dict] | None = None,
    resolve_card_effect_question_fn: Callable[..., PipelineResolution] | None = None,
    online_ingest_enabled: bool = True,
) -> FastAPI:
    app = FastAPI()
    find_matched_cards_fn = find_matched_cards_fn if find_matched_cards_fn is not None else find_matched_cards
    build_known_facts_context_fn = (
        build_known_facts_context_fn if build_known_facts_context_fn is not None else build_known_facts_context
    )
    build_grounded_result_fn = (
        build_grounded_result_fn if build_grounded_result_fn is not None else build_grounded_result
    )
    resolve_card_effect_question_fn = (
        resolve_card_effect_question_fn
        if resolve_card_effect_question_fn is not None
        else resolve_card_effect_question
    )

    def _backend_unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("backend connection error", exc_info=exc)
        return JSONResponse(status_code=503, content={"detail": "backend unavailable"})

    def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error", exc_info=exc)
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

    app.add_exception_handler(requests.exceptions.ConnectionError, _backend_unavailable_handler)
    app.add_exception_handler(psycopg.OperationalError, _backend_unavailable_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins if cors_origins is not None else DEFAULT_CORS_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.post("/questions", response_model=ResultResponse | NeedsClarificationResponse)
    def post_question(body: QuestionRequest) -> dict:
        question = body.question.strip()
        if not question:
            raise HTTPException(status_code=400, detail="question must not be empty")

        matches = find_matched_cards_fn(question)
        disambiguation_items: list[ClarificationItem] = []
        preflight_context = ""
        if len(matches) == 1:
            preflight_context = build_known_facts_context_fn(matches[0])
        elif len(matches) > 1:
            names = ", ".join(match["name"] for match in matches)
            disambiguation_items.append(
                ClarificationItem(
                    kind="disambiguate_card",
                    text=f"Multiple cards match your question: {names}. Which one do you mean?",
                )
            )

        if matches:
            clarify_response = llm_client.complete(
                build_clarification_prompt(question, known_facts_context=preflight_context),
                system=build_system_prompt(),
            )
            items = disambiguation_items + parse_clarification_response(clarify_response)
        else:
            items = disambiguation_items
        if items:
            return {
                "status": "needs_clarification",
                "question": question,
                "items": [{"kind": item.kind, "text": item.text} for item in items],
            }

        grounded_cards = [build_grounded_result_fn(matches[0])] if len(matches) == 1 else []
        if not matches:
            resolution = resolve_card_effect_question_fn(
                question,
                llm_client=llm_client,
                online_ingest_enabled=online_ingest_enabled,
                on_ingest_start=None,
            )
            if not resolution.supported:
                return _result_response(LoopResult(kind="not_supported", text=NOT_SUPPORTED_MESSAGE))
            preflight_context = resolution.context
            grounded_cards = resolution.grounded_cards

        result = run_loop(
            question,
            llm_client=llm_client,
            tools={},
            clarification_context=preflight_context,
            grounded_cards=grounded_cards,
            system_prompt=build_answering_system_prompt(),
        )
        return _result_response(result)

    @app.post("/questions/answer", response_model=ResultResponse)
    def post_answer(body: AnswerRequest) -> dict:
        question = body.question.strip()
        if not question:
            raise HTTPException(status_code=400, detail="question must not be empty")
        if len(body.items) != len(body.answers):
            raise HTTPException(status_code=400, detail="items and answers must be the same length")

        items = [ClarificationItem(kind=item.kind, text=item.text) for item in body.items]
        matches = find_matched_cards_fn(question)
        card = _resolve_preflight_card(matches, items, body.answers)
        preflight_context = build_known_facts_context_fn(card) if card is not None else ""
        grounded_cards = [build_grounded_result_fn(card)] if card is not None else []

        if not matches:
            resolution = resolve_card_effect_question_fn(
                question,
                llm_client=llm_client,
                online_ingest_enabled=online_ingest_enabled,
                on_ingest_start=None,
            )
            if not resolution.supported:
                return _result_response(LoopResult(kind="not_supported", text=NOT_SUPPORTED_MESSAGE))
            preflight_context = resolution.context
            grounded_cards = resolution.grounded_cards

        context = format_clarification_context(items, body.answers)
        if preflight_context:
            context = f"{preflight_context}\n\n{context}" if context else preflight_context

        result = run_loop(
            question,
            llm_client=llm_client,
            tools={},
            clarification_context=context,
            grounded_cards=grounded_cards,
            system_prompt=build_answering_system_prompt(),
        )
        return _result_response(result)

    return app
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/test_app.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/api/app.py tests/api/test_app.py
git commit -m "feat: apply the restricted answering pathway to every API question"
```

---

## Task 9: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the complete test suite**

Run: `pytest -v`
Expected: PASS — every test in the suite (DB-dependent tests auto-skip if `DATABASE_URL` isn't set; run with the
Docker Postgres up, per CLAUDE.md, for full coverage including `tests/db/*` and `tests/orchestration/test_tools_db.py`,
which exercise `card_resolution.py`'s real `get_card_by_id`/`lookup_card` defaults indirectly through integration
paths this plan didn't add DB-level tests for directly).

- [ ] **Step 2: Manually smoke-test the CLI end-to-end** (mirrors the real-app verification done earlier this
session — real Postgres, real Ollama)

Run: `python -m aijudge`, then ask about a card not in the local DB (e.g. a `Tearlaments` card not already
seeded from earlier testing). Confirm: no `TOOL:` calls appear in the flow (none are available), the answer is
grounded in real fetched card text, and a genuinely unknown/misspelled name produces an honest "not found"
message rather than a fabricated description.

- [ ] **Step 3: Commit** (only if Step 2 surfaced a fix; otherwise nothing to commit)

```bash
git status --short
```

If clean, this task is verification-only and needs no commit.
