# LLM Orchestration & CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the agentic tool-use loop and REPL CLI that let AIJudge answer Yu-Gi-Oh! rules questions by calling into the DB and rules engine, gated by deterministic confidence scoring — closing the loop between the already-built data layer, effect parser, and rules engine.

**Architecture:** A text-based tool-call protocol (`TOOL: name {json}` / `FINAL: text ||CITES: ids||`) sits on top of the unmodified `LLMClient.complete(prompt) -> str` interface. Four tool wrappers adapt DB repos, embeddings, and a new composed `resolve_chain` rules-engine function into a uniform `dict -> dict` shape. The orchestration loop tracks which source ids were actually returned by tool calls this session and computes confidence deterministically from that — no second LLM call, no vibes. A plain stdlib REPL drives it.

**Tech Stack:** Python 3.11+, stdlib only for the new code (no new dependencies) — reuses `psycopg`/`pgvector` already in `pyproject.toml`.

**Spec:** `docs/superpowers/specs/2026-08-19-orchestration-and-cli-design.md`

## Global Constraints

- `LLMClient` stays exactly `complete(prompt: str) -> str` — no interface changes (spec §"Tool-call protocol").
- Tool-call wire format: `TOOL: <tool_name> <json_object>` on one line; final answer: `FINAL: <text> ||CITES: id1, id2||` (empty trailer `||CITES: ||` when no citations apply).
- `effect_type` values in any JSON payload are exactly `EffectType`'s existing string values (`"trigger"`, `"ignition"`, `"quick"`, `"continuous"`, `"unclassified"`, `"condition"`, `"effect"`, `"trigger-like"`, `"quick-like"`) — no translation layer.
- Malformed protocol responses are capped at 3 consecutive retries before surfacing "not supported yet, contact dev team" (spec §"Tool-call protocol").
- `UnsupportedScenarioError` from `resolve_chain` is checked before confidence scoring, not folded into it (spec §"Confidence & escalation").
- `DEFAULT_CONFIDENCE_THRESHOLD = 0.9`, matching the naming convention already used in `effect_parser/review_agent.py`.
- DB-dependent tests follow the existing project convention: `pytestmark = pytest.mark.skipif("DATABASE_URL" not in os.environ, ...)` at module top, `setup_function` truncates the tables under test.
- TDD throughout: a failing test precedes implementation code for every task (project-wide convention, restated in the spec's "Testing" section).

---

## File Structure

New files this plan creates:

- `src/aijudge/rules_engine/resolve.py` — `resolve_chain` composition (pure, no DB/LLM).
- `src/aijudge/orchestration/__init__.py` — empty package marker.
- `src/aijudge/orchestration/protocol.py` — tool-call/final-answer text parser + system prompt builder.
- `src/aijudge/orchestration/confidence.py` — deterministic signal tracking + confidence scoring.
- `src/aijudge/orchestration/clarify.py` — upfront clarification-phase parsing/prompting.
- `src/aijudge/orchestration/tools.py` — the four tool wrappers + dispatch registry.
- `src/aijudge/orchestration/loop.py` — the main tool-use loop.
- `src/aijudge/cli.py` — REPL entry point.

Modified:

- `src/aijudge/db/rulebook_repo.py` — add `search_chunks`.

Test files (new):

- `tests/rules_engine/test_resolve.py`
- `tests/orchestration/__init__.py`
- `tests/orchestration/test_protocol.py`
- `tests/orchestration/test_confidence.py`
- `tests/orchestration/test_clarify.py`
- `tests/orchestration/test_tools_db.py`
- `tests/orchestration/test_tools.py`
- `tests/orchestration/test_loop.py`
- `tests/test_cli.py`

Test files (modified):

- `tests/db/test_rulebook_repo.py` — add `search_chunks` cases.

---

### Task 1: `resolve_chain` composition

**Files:**
- Create: `src/aijudge/rules_engine/resolve.py`
- Test: `tests/rules_engine/test_resolve.py`

**Interfaces:**
- Consumes: `Chain` from `rules_engine.chain`; `Effect`, `EffectType`, `SpellSpeed` from `rules_engine.models`; `apply_segoc` from `rules_engine.segoc`; `can_activate_now` from `rules_engine.priority`.
- Produces (used by Task 7): `UnsupportedScenarioError(Exception)`, `ChainLinkResult` (`link_number: int, card_name: str, controller: str`), `Violation` (`step_index: int, reason: str, detail: str`), `ResolutionResult` (`resolution_order: list[ChainLinkResult], violation: Violation | None`), `resolve_chain(scenario: dict) -> ResolutionResult`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/rules_engine/test_resolve.py
import pytest

from aijudge.rules_engine.resolve import UnsupportedScenarioError, resolve_chain


def _effect(card_name, controller, effect_type="ignition", spell_speed=1, prevents_response=False):
    return {
        "card_name": card_name,
        "controller": controller,
        "effect_type": effect_type,
        "spell_speed": spell_speed,
        "prevents_response": prevents_response,
    }


def test_single_activate_step_resolves_alone():
    scenario = {
        "turn_player": "player_a",
        "steps": [{"kind": "activate", "effect": _effect("Card A", "player_a")}],
    }

    result = resolve_chain(scenario)

    assert result.violation is None
    assert [link.card_name for link in result.resolution_order] == ["Card A"]


def test_segoc_batch_then_activate_resolves_lifo():
    scenario = {
        "turn_player": "player_a",
        "steps": [
            {
                "kind": "segoc_batch",
                "effects": [
                    _effect("Turn Player's Trigger", "player_a"),
                    _effect("Opponent's Trigger", "player_b"),
                ],
            },
            {
                "kind": "activate",
                "effect": _effect("Quick Effect Response", "player_b", effect_type="quick", spell_speed=2),
            },
        ],
    }

    result = resolve_chain(scenario)

    assert result.violation is None
    assert [link.card_name for link in result.resolution_order] == [
        "Quick Effect Response",
        "Opponent's Trigger",
        "Turn Player's Trigger",
    ]


def test_illegal_activate_step_produces_violation_and_halts():
    scenario = {
        "turn_player": "player_a",
        "steps": [
            {"kind": "activate", "effect": _effect("Card A", "player_a")},
            {"kind": "activate", "effect": _effect("Card B", "player_b")},
        ],
    }

    result = resolve_chain(scenario)

    assert result.violation is not None
    assert result.violation.step_index == 1
    assert result.violation.reason == "priority_violation"
    assert [link.card_name for link in result.resolution_order] == ["Card A"]


def test_unrecognized_step_kind_raises_unsupported_scenario_error():
    scenario = {"turn_player": "player_a", "steps": [{"kind": "replay"}]}

    with pytest.raises(UnsupportedScenarioError):
        resolve_chain(scenario)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/rules_engine/test_resolve.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aijudge.rules_engine.resolve'`

- [ ] **Step 3: Write the implementation**

```python
# src/aijudge/rules_engine/resolve.py
from dataclasses import dataclass

from .chain import Chain
from .models import Effect, EffectType, SpellSpeed
from .priority import can_activate_now
from .segoc import apply_segoc


class UnsupportedScenarioError(Exception):
    """Raised when a resolve_chain scenario describes a step this engine has no rule for."""


@dataclass
class ChainLinkResult:
    link_number: int
    card_name: str
    controller: str


@dataclass
class Violation:
    step_index: int
    reason: str
    detail: str


@dataclass
class ResolutionResult:
    resolution_order: list[ChainLinkResult]
    violation: Violation | None


def _build_effect(data: dict) -> Effect:
    return Effect(
        card_id=data["card_name"],
        card_name=data["card_name"],
        effect_type=EffectType(data["effect_type"]),
        controller=data["controller"],
        spell_speed=SpellSpeed(data.get("spell_speed", SpellSpeed.NORMAL.value)),
        prevents_response=data.get("prevents_response", False),
    )


def _order(chain: Chain) -> list[ChainLinkResult]:
    return [
        ChainLinkResult(link_number=link.link_number, card_name=link.effect.card_name, controller=link.effect.controller)
        for link in chain.resolution_order()
    ]


def resolve_chain(scenario: dict) -> ResolutionResult:
    turn_player = scenario["turn_player"]
    chain = Chain()

    for step_index, step in enumerate(scenario["steps"]):
        kind = step["kind"]
        if kind == "segoc_batch":
            effects = [_build_effect(e) for e in step["effects"]]
            apply_segoc(chain, turn_player=turn_player, triggered_effects=effects)
        elif kind == "activate":
            effect = _build_effect(step["effect"])
            if not can_activate_now(effect.spell_speed, chain):
                violation = Violation(
                    step_index=step_index,
                    reason="priority_violation",
                    detail=(
                        f"{effect.card_name}'s spell speed {effect.spell_speed.value} "
                        "cannot respond to the current chain"
                    ),
                )
                return ResolutionResult(resolution_order=_order(chain), violation=violation)
            chain.add_link(effect)
        else:
            raise UnsupportedScenarioError(f"unrecognized step kind: {kind!r}")

    return ResolutionResult(resolution_order=_order(chain), violation=None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/rules_engine/test_resolve.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/rules_engine/resolve.py tests/rules_engine/test_resolve.py
git commit -m "feat(rules_engine): compose chain/segoc/priority into resolve_chain"
```

---

### Task 2: Vector search over rulebook chunks

**Files:**
- Modify: `src/aijudge/db/rulebook_repo.py`
- Test: `tests/db/test_rulebook_repo.py`

**Interfaces:**
- Consumes: `get_connection` from `db.connection` (existing pattern in this file).
- Produces (used by Task 6): `search_chunks(query_embedding: list[float], *, max_distance: float, limit: int = 5) -> list[dict]`, each dict shaped `{"id": str, "chunk_text": str, "source": str, "section_reference": str | None}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/db/test_rulebook_repo.py`:

```python
def test_search_chunks_returns_matches_within_threshold():
    from aijudge.db.rulebook_repo import insert_chunk, search_chunks
    from aijudge.embeddings.client import MockEmbeddingClient

    embed = MockEmbeddingClient().embed
    text = "Priority is the ability to activate a card or effect in response to something."
    insert_chunk(chunk_text=text, source="konami_rulebook", embedding=embed(text))

    results = search_chunks(embed(text), max_distance=0.1)

    assert len(results) == 1
    assert results[0]["chunk_text"] == text


def test_search_chunks_excludes_matches_over_threshold():
    from aijudge.db.rulebook_repo import insert_chunk, search_chunks
    from aijudge.embeddings.client import MockEmbeddingClient

    embed = MockEmbeddingClient().embed
    text = "Priority is the ability to activate a card or effect in response to something."
    insert_chunk(chunk_text=text, source="konami_rulebook", embedding=embed(text))

    results = search_chunks(embed("something completely unrelated to card games entirely"), max_distance=0.1)

    assert results == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/db/test_rulebook_repo.py -v` (requires `DATABASE_URL` set and `docker compose up -d db` running — check `docker ps` first)
Expected: FAIL with `ImportError: cannot import name 'search_chunks'`

- [ ] **Step 3: Write the implementation**

Append to `src/aijudge/db/rulebook_repo.py`:

```python
def search_chunks(query_embedding: list[float], *, max_distance: float, limit: int = 5) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, chunk_text, source, section_reference
            FROM rulebook_chunks
            WHERE embedding <=> %s < %s
            ORDER BY embedding <=> %s
            LIMIT %s
            """,
            (query_embedding, max_distance, query_embedding, limit),
        ).fetchall()
    return [
        {"id": str(r[0]), "chunk_text": r[1], "source": r[2], "section_reference": r[3]}
        for r in rows
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/db/test_rulebook_repo.py -v`
Expected: PASS (4 tests total in file)

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/db/rulebook_repo.py tests/db/test_rulebook_repo.py
git commit -m "feat(db): add threshold-filtered vector search over rulebook_chunks"
```

---

### Task 3: Tool-call protocol parser

**Files:**
- Create: `src/aijudge/orchestration/__init__.py` (empty)
- Create: `src/aijudge/orchestration/protocol.py`
- Create: `tests/orchestration/__init__.py` (empty)
- Test: `tests/orchestration/test_protocol.py`

**Interfaces:**
- Consumes: nothing beyond stdlib (`json`, `dataclasses`).
- Produces (used by Task 8): `ToolCall` (`name: str, args: dict`), `FinalAnswer` (`text: str, cited_ids: set[str]`), `ProtocolError(Exception)`, `TOOL_NAMES: set[str]`, `parse_response(response: str) -> ToolCall | FinalAnswer`, `build_system_prompt() -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/orchestration/test_protocol.py
import pytest

from aijudge.orchestration.protocol import FinalAnswer, ProtocolError, ToolCall, build_system_prompt, parse_response


def test_parses_tool_call_line():
    parsed = parse_response('TOOL: lookup_card {"name": "Ash Blossom & Joyous Spring"}')
    assert parsed == ToolCall(name="lookup_card", args={"name": "Ash Blossom & Joyous Spring"})


def test_parses_final_answer_with_citations():
    parsed = parse_response("FINAL: This card negates the effect. ||CITES: card:1, ruling:2||")
    assert parsed == FinalAnswer(text="This card negates the effect.", cited_ids={"card:1", "ruling:2"})


def test_parses_final_answer_with_empty_citations():
    parsed = parse_response("FINAL: Out of scope for this assistant. ||CITES: ||")
    assert parsed == FinalAnswer(text="Out of scope for this assistant.", cited_ids=set())


def test_rejects_unrecognized_tool_name():
    with pytest.raises(ProtocolError):
        parse_response("TOOL: delete_database {}")


def test_rejects_malformed_json_arguments():
    with pytest.raises(ProtocolError):
        parse_response("TOOL: lookup_card {not json}")


def test_rejects_final_answer_missing_cites_trailer():
    with pytest.raises(ProtocolError):
        parse_response("FINAL: This card negates the effect.")


def test_rejects_response_with_no_recognized_prefix():
    with pytest.raises(ProtocolError):
        parse_response("I think the answer is yes.")


def test_build_system_prompt_lists_all_four_tools():
    prompt = build_system_prompt()
    for tool_name in ("lookup_card", "get_rulings", "search_rulebook", "resolve_chain"):
        assert tool_name in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/orchestration/test_protocol.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aijudge.orchestration'`

- [ ] **Step 3: Write the implementation**

Create `src/aijudge/orchestration/__init__.py` (empty file) and `tests/orchestration/__init__.py` (empty file).

```python
# src/aijudge/orchestration/protocol.py
import json
from dataclasses import dataclass

TOOL_NAMES = {"lookup_card", "get_rulings", "search_rulebook", "resolve_chain"}

TOOL_DESCRIPTIONS = {
    "lookup_card": 'lookup_card {"name": "<card name>"} - fetch a card\'s text and structured effect data',
    "get_rulings": 'get_rulings {"card_id": "<id>"} - fetch official rulings for a card',
    "search_rulebook": 'search_rulebook {"query": "<question>"} - semantic search over the Konami rulebook/PSCT guide',
    "resolve_chain": 'resolve_chain {"turn_player": "...", "steps": [...]} - deterministically resolve a described chain scenario',
}


class ProtocolError(Exception):
    """Raised when an LLM response doesn't follow the TOOL:/FINAL: protocol."""


@dataclass
class ToolCall:
    name: str
    args: dict


@dataclass
class FinalAnswer:
    text: str
    cited_ids: set[str]


def build_system_prompt() -> str:
    tool_lines = "\n".join(f"- {desc}" for desc in TOOL_DESCRIPTIONS.values())
    return (
        "You are a Yu-Gi-Oh! TCG rules-adjudication assistant. Answer only "
        "questions about Yu-Gi-Oh! rules and card interactions, citing your "
        "sources. You may call one tool per turn by responding with a line "
        "starting with 'TOOL:' followed by the tool name and a JSON object "
        "of arguments. When you have a final answer, respond with a line "
        "starting with 'FINAL:' followed by your answer text, then "
        "'||CITES: id1, id2||' listing every source id (card:<id>, "
        "ruling:<id>, chunk:<id>) your answer relies on -- use '||CITES: ||' "
        "if none apply.\n\nAvailable tools:\n" + tool_lines
    )


def parse_response(response: str) -> ToolCall | FinalAnswer:
    response = response.strip()

    if response.startswith("TOOL:"):
        remainder = response[len("TOOL:"):].strip()
        try:
            name, json_part = remainder.split(" ", 1)
        except ValueError:
            raise ProtocolError(f"malformed TOOL line, expected 'TOOL: name {{json}}': {response!r}")
        if name not in TOOL_NAMES:
            raise ProtocolError(f"unrecognized tool name: {name!r}")
        try:
            args = json.loads(json_part)
        except json.JSONDecodeError as error:
            raise ProtocolError(f"invalid JSON arguments for tool {name!r}: {error}")
        return ToolCall(name=name, args=args)

    if response.startswith("FINAL:"):
        remainder = response[len("FINAL:"):].strip()
        if "||CITES:" not in remainder:
            raise ProtocolError(f"FINAL line missing '||CITES: ...||' trailer: {response!r}")
        text_part, _, cites_part = remainder.partition("||CITES:")
        cites_part = cites_part.strip()
        if not cites_part.endswith("||"):
            raise ProtocolError(f"FINAL line's CITES trailer must end with '||': {response!r}")
        cites_body = cites_part[:-2].strip()
        cited_ids = {c.strip() for c in cites_body.split(",") if c.strip()} if cites_body else set()
        return FinalAnswer(text=text_part.strip(), cited_ids=cited_ids)

    raise ProtocolError(f"response must start with 'TOOL:' or 'FINAL:': {response!r}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/orchestration/test_protocol.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/orchestration/__init__.py src/aijudge/orchestration/protocol.py tests/orchestration/__init__.py tests/orchestration/test_protocol.py
git commit -m "feat(orchestration): add TOOL:/FINAL: text protocol parser"
```

---

### Task 4: Deterministic confidence scoring

**Files:**
- Create: `src/aijudge/orchestration/confidence.py`
- Test: `tests/orchestration/test_confidence.py`

**Interfaces:**
- Consumes: nothing beyond stdlib (`dataclasses`).
- Produces (used by Task 8): `DEFAULT_CONFIDENCE_THRESHOLD = 0.9`, `RETRIEVAL_GAP_PENALTY = 0.3`, `MISSING_STRUCTURED_EFFECT_PENALTY = 0.2`, `SignalState` (`known_ids: set[str], missing_structured_effect: bool, retrieval_gap: bool`, all defaulted), `update_signals(state: SignalState, tool_name: str, result: dict) -> None`, `compute_confidence(cited_ids: set[str], state: SignalState) -> float`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/orchestration/test_confidence.py
import pytest

from aijudge.orchestration.confidence import (
    MISSING_STRUCTURED_EFFECT_PENALTY,
    RETRIEVAL_GAP_PENALTY,
    SignalState,
    compute_confidence,
    update_signals,
)


def test_update_signals_tracks_found_card_id():
    state = SignalState()
    update_signals(state, "lookup_card", {"found": True, "id": "abc", "confirmed_effect": {"effect": "..."}})
    assert state.known_ids == {"card:abc"}
    assert state.missing_structured_effect is False


def test_update_signals_flags_missing_structured_effect():
    state = SignalState()
    update_signals(state, "lookup_card", {"found": True, "id": "abc", "confirmed_effect": None})
    assert state.missing_structured_effect is True


def test_update_signals_ignores_card_not_found():
    state = SignalState()
    update_signals(state, "lookup_card", {"found": False})
    assert state.known_ids == set()
    assert state.missing_structured_effect is False


def test_update_signals_tracks_ruling_ids_and_gap():
    state = SignalState()
    update_signals(state, "get_rulings", {"rulings": [{"id": "r1", "ruling_text": "..."}]})
    assert state.known_ids == {"ruling:r1"}
    assert state.retrieval_gap is False

    empty_state = SignalState()
    update_signals(empty_state, "get_rulings", {"rulings": []})
    assert empty_state.retrieval_gap is True


def test_update_signals_tracks_chunk_ids_and_gap():
    state = SignalState()
    update_signals(state, "search_rulebook", {"chunks": [{"id": "c1", "chunk_text": "..."}]})
    assert state.known_ids == {"chunk:c1"}

    empty_state = SignalState()
    update_signals(empty_state, "search_rulebook", {"chunks": []})
    assert empty_state.retrieval_gap is True


def test_compute_confidence_is_perfect_with_no_negative_signals():
    state = SignalState(known_ids={"card:abc"})
    assert compute_confidence({"card:abc"}, state) == 1.0


def test_compute_confidence_zero_on_fabricated_citation():
    state = SignalState(known_ids={"card:abc"})
    assert compute_confidence({"card:abc", "ruling:never-looked-up"}, state) == 0.0


def test_compute_confidence_applies_retrieval_gap_penalty():
    state = SignalState(retrieval_gap=True)
    assert compute_confidence(set(), state) == pytest.approx(1.0 - RETRIEVAL_GAP_PENALTY)


def test_compute_confidence_applies_missing_structured_effect_penalty():
    state = SignalState(missing_structured_effect=True)
    assert compute_confidence(set(), state) == pytest.approx(1.0 - MISSING_STRUCTURED_EFFECT_PENALTY)


def test_compute_confidence_applies_both_penalties_together():
    state = SignalState(retrieval_gap=True, missing_structured_effect=True)
    assert compute_confidence(set(), state) == pytest.approx(1.0 - RETRIEVAL_GAP_PENALTY - MISSING_STRUCTURED_EFFECT_PENALTY)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/orchestration/test_confidence.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aijudge.orchestration.confidence'`

- [ ] **Step 3: Write the implementation**

```python
# src/aijudge/orchestration/confidence.py
from dataclasses import dataclass, field

DEFAULT_CONFIDENCE_THRESHOLD = 0.9
RETRIEVAL_GAP_PENALTY = 0.3
MISSING_STRUCTURED_EFFECT_PENALTY = 0.2


@dataclass
class SignalState:
    known_ids: set[str] = field(default_factory=set)
    missing_structured_effect: bool = False
    retrieval_gap: bool = False


def update_signals(state: SignalState, tool_name: str, result: dict) -> None:
    if tool_name == "lookup_card":
        if result.get("found"):
            state.known_ids.add(f"card:{result['id']}")
            if result.get("confirmed_effect") is None:
                state.missing_structured_effect = True
    elif tool_name == "get_rulings":
        rulings = result.get("rulings", [])
        if not rulings:
            state.retrieval_gap = True
        for ruling in rulings:
            state.known_ids.add(f"ruling:{ruling['id']}")
    elif tool_name == "search_rulebook":
        chunks = result.get("chunks", [])
        if not chunks:
            state.retrieval_gap = True
        for chunk in chunks:
            state.known_ids.add(f"chunk:{chunk['id']}")


def compute_confidence(cited_ids: set[str], state: SignalState) -> float:
    if cited_ids - state.known_ids:
        return 0.0

    score = 1.0
    if state.retrieval_gap:
        score -= RETRIEVAL_GAP_PENALTY
    if state.missing_structured_effect:
        score -= MISSING_STRUCTURED_EFFECT_PENALTY
    return max(0.0, min(1.0, score))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/orchestration/test_confidence.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/orchestration/confidence.py tests/orchestration/test_confidence.py
git commit -m "feat(orchestration): deterministic confidence scoring from tool-call signals"
```

---

### Task 5: Clarification phase

**Files:**
- Create: `src/aijudge/orchestration/clarify.py`
- Test: `tests/orchestration/test_clarify.py`

**Interfaces:**
- Consumes: nothing beyond stdlib (`dataclasses`).
- Produces (used by Task 9): `ClarificationItem` (`kind: str, text: str`), `build_clarification_prompt(question: str) -> str`, `parse_clarification_response(response: str) -> list[ClarificationItem]`, `clarification_prompt_text(item: ClarificationItem) -> str`, `format_clarification_context(items: list[ClarificationItem], answers: list[str]) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/orchestration/test_clarify.py
from aijudge.orchestration.clarify import (
    ClarificationItem,
    build_clarification_prompt,
    clarification_prompt_text,
    format_clarification_context,
    parse_clarification_response,
)


def test_parse_clarification_response_returns_empty_list_on_proceed():
    assert parse_clarification_response("PROCEED") == []


def test_parse_clarification_response_parses_clarify_lines():
    response = "CLARIFY: Which monster do you mean, the Level 4 or Level 8?"
    items = parse_clarification_response(response)
    assert items == [ClarificationItem(kind="clarify", text="Which monster do you mean, the Level 4 or Level 8?")]


def test_parse_clarification_response_parses_continuous_check_lines():
    response = "CONTINUOUS_CHECK: Skill Drain\nCONTINUOUS_CHECK: Rivalry of Warlords"
    items = parse_clarification_response(response)
    assert items == [
        ClarificationItem(kind="continuous_check", text="Skill Drain"),
        ClarificationItem(kind="continuous_check", text="Rivalry of Warlords"),
    ]


def test_build_clarification_prompt_includes_the_question():
    prompt = build_clarification_prompt("Can I activate Solemn Strike here?")
    assert "Can I activate Solemn Strike here?" in prompt


def test_clarification_prompt_text_for_clarify_item_is_the_question_itself():
    item = ClarificationItem(kind="clarify", text="Which monster do you control?")
    assert clarification_prompt_text(item) == "Which monster do you control?"


def test_clarification_prompt_text_for_continuous_check_asks_about_activity():
    item = ClarificationItem(kind="continuous_check", text="Skill Drain")
    assert clarification_prompt_text(item) == "Is Skill Drain's effect currently active?"


def test_format_clarification_context_joins_items_and_answers():
    items = [
        ClarificationItem(kind="clarify", text="Which monster do you control?"),
        ClarificationItem(kind="continuous_check", text="Skill Drain"),
    ]
    answers = ["Blue-Eyes White Dragon", "yes"]

    context = format_clarification_context(items, answers)

    assert "Which monster do you control?: Blue-Eyes White Dragon" in context
    assert "Is Skill Drain's effect currently active?: yes" in context
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/orchestration/test_clarify.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aijudge.orchestration.clarify'`

- [ ] **Step 3: Write the implementation**

```python
# src/aijudge/orchestration/clarify.py
from dataclasses import dataclass


@dataclass
class ClarificationItem:
    kind: str  # "clarify" | "continuous_check"
    text: str


def build_clarification_prompt(question: str) -> str:
    return (
        "A user asked a Yu-Gi-Oh! rules question. Before answering, decide "
        "whether you need more information:\n"
        "- If the question is ambiguous or missing details you need, "
        "respond with one or more lines: 'CLARIFY: <question to ask the user>'\n"
        "- If the question depends on a continuous or lingering effect card "
        "whose current on-board status you can't observe, respond with one "
        "or more lines: 'CONTINUOUS_CHECK: <card name>'\n"
        "- If neither applies, respond with exactly: 'PROCEED'\n\n"
        f"Question: {question}"
    )


def parse_clarification_response(response: str) -> list[ClarificationItem]:
    items = []
    for line in response.strip().splitlines():
        line = line.strip()
        if not line or line == "PROCEED":
            continue
        if line.startswith("CLARIFY:"):
            items.append(ClarificationItem(kind="clarify", text=line[len("CLARIFY:"):].strip()))
        elif line.startswith("CONTINUOUS_CHECK:"):
            items.append(ClarificationItem(kind="continuous_check", text=line[len("CONTINUOUS_CHECK:"):].strip()))
    return items


def clarification_prompt_text(item: ClarificationItem) -> str:
    if item.kind == "continuous_check":
        return f"Is {item.text}'s effect currently active?"
    return item.text


def format_clarification_context(items: list[ClarificationItem], answers: list[str]) -> str:
    lines = []
    for item, answer in zip(items, answers):
        label = "Clarification" if item.kind == "clarify" else "Continuous effect status"
        lines.append(f"{label} - {clarification_prompt_text(item)}: {answer}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/orchestration/test_clarify.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/orchestration/clarify.py tests/orchestration/test_clarify.py
git commit -m "feat(orchestration): upfront clarification-phase parsing and prompts"
```

---

### Task 6: DB-dependent tool wrappers

**Files:**
- Create: `src/aijudge/orchestration/tools.py`
- Test: `tests/orchestration/test_tools_db.py`

**Interfaces:**
- Consumes: `get_card_by_name` from `db.cards_repo`; `get_confirmed_effect` from `db.effects_repo`; `get_rulings_for_card` from `db.rulings_repo`; `search_chunks` from `db.rulebook_repo` (Task 2); `EmbeddingClient` from `embeddings.client`.
- Produces (used by Task 7): `DEFAULT_MAX_DISTANCE = 0.15`, `lookup_card(args: dict) -> dict`, `get_rulings(args: dict) -> dict`, `_search_rulebook(args: dict, *, embedding_client: EmbeddingClient) -> dict`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/orchestration/test_tools_db.py
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
        conn.execute("TRUNCATE rulebook_chunks")
        conn.commit()


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
    assert result["confirmed_effect"] is None

    missing = lookup_card({"name": "Nonexistent Card"})
    assert missing == {"found": False}


def test_lookup_card_includes_confirmed_effect_when_present():
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
    assert result["confirmed_effect"]["effect_type"] == "quick"


def test_get_rulings_returns_empty_list_when_none_exist():
    from aijudge.db.cards_repo import insert_card
    from aijudge.orchestration.tools import get_rulings

    card_id = insert_card(
        name="Called by the Grave",
        card_text="During either player's turn...",
        card_type="Quick-Play Spell",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="47355498",
    )

    assert get_rulings({"card_id": card_id}) == {"rulings": []}


def test_get_rulings_serializes_ruling_date_to_isoformat():
    from aijudge.db.cards_repo import insert_card
    from aijudge.db.rulings_repo import insert_ruling
    from aijudge.orchestration.tools import get_rulings

    card_id = insert_card(
        name="Infinite Impermanence",
        card_text="Target 1 face-up monster your opponent controls...",
        card_type="Trap",
        source="ygoprodeck",
        fetched_at=date(2026, 8, 18),
        ygoprodeck_id="10045474",
    )
    insert_ruling(
        card_id=card_id,
        ruling_text="This effect can target itself.",
        source="db.ygoresources",
        ruling_date=date(2020, 1, 1),
    )

    result = get_rulings({"card_id": card_id})
    assert result["rulings"][0]["ruling_date"] == "2020-01-01"
    assert result["rulings"][0]["ruling_text"] == "This effect can target itself."


def test_search_rulebook_wrapper_respects_default_max_distance():
    from aijudge.db.rulebook_repo import insert_chunk
    from aijudge.embeddings.client import MockEmbeddingClient
    from aijudge.orchestration.tools import _search_rulebook

    client = MockEmbeddingClient()
    text = "Priority is the ability to activate a card or effect in response to something."
    insert_chunk(chunk_text=text, source="konami_rulebook", embedding=client.embed(text))

    result = _search_rulebook({"query": text}, embedding_client=client)
    assert len(result["chunks"]) == 1
    assert result["chunks"][0]["chunk_text"] == text

    empty = _search_rulebook({"query": "something totally unrelated to yugioh at all"}, embedding_client=client)
    assert empty["chunks"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/orchestration/test_tools_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aijudge.orchestration.tools'`

- [ ] **Step 3: Write the implementation**

```python
# src/aijudge/orchestration/tools.py
from aijudge.db.cards_repo import get_card_by_name
from aijudge.db.effects_repo import get_confirmed_effect
from aijudge.db.rulebook_repo import search_chunks
from aijudge.db.rulings_repo import get_rulings_for_card
from aijudge.embeddings.client import EmbeddingClient

DEFAULT_MAX_DISTANCE = 0.15


def lookup_card(args: dict) -> dict:
    card = get_card_by_name(args["name"])
    if card is None:
        return {"found": False}
    confirmed_effect = get_confirmed_effect(card["id"])
    return {
        "found": True,
        "id": card["id"],
        "name": card["name"],
        "card_text": card["card_text"],
        "card_type": card["card_type"],
        "confirmed_effect": confirmed_effect,
    }


def get_rulings(args: dict) -> dict:
    rulings = get_rulings_for_card(args["card_id"])
    return {
        "rulings": [
            {
                "id": ruling["id"],
                "ruling_text": ruling["ruling_text"],
                "source": ruling["source"],
                "ruling_date": ruling["ruling_date"].isoformat() if ruling["ruling_date"] else None,
            }
            for ruling in rulings
        ]
    }


def _search_rulebook(args: dict, *, embedding_client: EmbeddingClient) -> dict:
    query_embedding = embedding_client.embed(args["query"])
    chunks = search_chunks(query_embedding, max_distance=DEFAULT_MAX_DISTANCE)
    return {
        "chunks": [
            {
                "id": chunk["id"],
                "chunk_text": chunk["chunk_text"],
                "source": chunk["source"],
                "section_reference": chunk["section_reference"],
            }
            for chunk in chunks
        ]
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/orchestration/test_tools_db.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/orchestration/tools.py tests/orchestration/test_tools_db.py
git commit -m "feat(orchestration): DB-backed lookup_card/get_rulings/search_rulebook tool wrappers"
```

---

### Task 7: `resolve_chain` wrapper and tool dispatch registry

**Files:**
- Modify: `src/aijudge/orchestration/tools.py` (append to the file created in Task 6)
- Test: `tests/orchestration/test_tools.py`

**Interfaces:**
- Consumes: `resolve_chain`, `UnsupportedScenarioError` from `rules_engine.resolve` (Task 1); `lookup_card`, `get_rulings`, `_search_rulebook`, `DEFAULT_MAX_DISTANCE` from this file (Task 6).
- Produces (used by Task 9): `resolve_chain(args: dict) -> dict` (tools.py-level wrapper, distinct name from the rules-engine function it wraps), `build_tool_dispatch(embedding_client: EmbeddingClient) -> dict[str, Callable[[dict], dict]]` with exactly the keys `"lookup_card"`, `"get_rulings"`, `"search_rulebook"`, `"resolve_chain"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/orchestration/test_tools.py
import pytest

from aijudge.embeddings.client import MockEmbeddingClient
from aijudge.orchestration.tools import build_tool_dispatch, resolve_chain
from aijudge.rules_engine.resolve import UnsupportedScenarioError


def test_resolve_chain_wrapper_returns_plain_dict():
    scenario = {
        "turn_player": "player_a",
        "steps": [
            {
                "kind": "activate",
                "effect": {
                    "card_name": "Card A",
                    "controller": "player_a",
                    "effect_type": "ignition",
                    "spell_speed": 1,
                    "prevents_response": False,
                },
            }
        ],
    }

    result = resolve_chain(scenario)

    assert result == {
        "resolution_order": [{"link_number": 1, "card_name": "Card A", "controller": "player_a"}],
        "violation": None,
    }


def test_resolve_chain_wrapper_propagates_unsupported_scenario_error():
    scenario = {"turn_player": "player_a", "steps": [{"kind": "replay"}]}

    with pytest.raises(UnsupportedScenarioError):
        resolve_chain(scenario)


def test_build_tool_dispatch_has_all_four_tools():
    dispatch = build_tool_dispatch(MockEmbeddingClient())
    assert set(dispatch.keys()) == {"lookup_card", "get_rulings", "search_rulebook", "resolve_chain"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/orchestration/test_tools.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_tool_dispatch'`

- [ ] **Step 3: Write the implementation**

Add these imports to the top of `src/aijudge/orchestration/tools.py` (alongside the existing ones from Task 6):

```python
from dataclasses import asdict
from typing import Callable

from aijudge.rules_engine.resolve import resolve_chain as _resolve_chain_scenario
```

Append to the end of `src/aijudge/orchestration/tools.py`:

```python
def resolve_chain(args: dict) -> dict:
    result = _resolve_chain_scenario(args)
    return asdict(result)


def build_tool_dispatch(embedding_client: EmbeddingClient) -> dict[str, Callable[[dict], dict]]:
    return {
        "lookup_card": lookup_card,
        "get_rulings": get_rulings,
        "search_rulebook": lambda args: _search_rulebook(args, embedding_client=embedding_client),
        "resolve_chain": resolve_chain,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/orchestration/test_tools.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/orchestration/tools.py tests/orchestration/test_tools.py
git commit -m "feat(orchestration): resolve_chain tool wrapper and dispatch registry"
```

---

### Task 8: The orchestration loop

**Files:**
- Create: `src/aijudge/orchestration/loop.py`
- Test: `tests/orchestration/test_loop.py`

**Interfaces:**
- Consumes: `LLMClient` from `llm.client`; `UnsupportedScenarioError` from `rules_engine.resolve` (Task 1); `DEFAULT_CONFIDENCE_THRESHOLD`, `SignalState`, `compute_confidence`, `update_signals` from `orchestration.confidence` (Task 4); `FinalAnswer`, `ProtocolError`, `ToolCall`, `build_system_prompt`, `parse_response` from `orchestration.protocol` (Task 3).
- Produces (used by Task 9): `MAX_MALFORMED_RETRIES = 3`, `NOT_SUPPORTED_MESSAGE`, `ESCALATE_MESSAGE`, `LoopResult` (`kind: str, text: str` — `kind` is one of `"answer"`, `"escalate"`, `"not_supported"`), `run_loop(question: str, *, llm_client: LLMClient, tools: dict[str, Callable[[dict], dict]], clarification_context: str = "", threshold: float = DEFAULT_CONFIDENCE_THRESHOLD) -> LoopResult`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/orchestration/test_loop.py
from aijudge.llm.client import MockLLMClient
from aijudge.orchestration.loop import run_loop
from aijudge.rules_engine.resolve import UnsupportedScenarioError


def test_final_answer_with_no_tool_calls_returns_answer():
    llm = MockLLMClient()
    llm.queue_response("FINAL: Ash Blossom negates that effect. ||CITES: ||")

    result = run_loop("What does Ash Blossom do?", llm_client=llm, tools={})

    assert result.kind == "answer"
    assert result.text == "Ash Blossom negates that effect."


def test_tool_call_then_final_answer_cites_the_returned_id():
    llm = MockLLMClient()
    llm.queue_response('TOOL: lookup_card {"name": "Ash Blossom & Joyous Spring"}')
    llm.queue_response("FINAL: It negates the effect. ||CITES: card:abc123||")

    tools = {"lookup_card": lambda args: {"found": True, "id": "abc123", "confirmed_effect": {"effect": "..."}}}

    result = run_loop("What does Ash Blossom do?", llm_client=llm, tools=tools)

    assert result.kind == "answer"
    assert result.text == "It negates the effect."


def test_fabricated_citation_escalates():
    llm = MockLLMClient()
    llm.queue_response("FINAL: It negates the effect. ||CITES: card:never-looked-up||")

    result = run_loop("What does Ash Blossom do?", llm_client=llm, tools={})

    assert result.kind == "escalate"


def test_retrieval_gap_lowers_confidence_below_threshold():
    llm = MockLLMClient()
    llm.queue_response('TOOL: search_rulebook {"query": "obscure ruling"}')
    llm.queue_response("FINAL: I could not find a direct source. ||CITES: ||")

    tools = {"search_rulebook": lambda args: {"chunks": []}}

    result = run_loop("An obscure ruling question", llm_client=llm, tools=tools, threshold=0.95)

    assert result.kind == "escalate"


def test_unsupported_scenario_error_from_resolve_chain_short_circuits():
    llm = MockLLMClient()
    llm.queue_response(
        'TOOL: resolve_chain {"turn_player": "player_a", "steps": [{"kind": "replay"}]}'
    )

    def _raise(args):
        raise UnsupportedScenarioError("replay steps aren't modeled yet")

    result = run_loop("Resolve this weird replay scenario", llm_client=llm, tools={"resolve_chain": _raise})

    assert result.kind == "not_supported"


def test_malformed_responses_exhausted_surfaces_not_supported():
    llm = MockLLMClient()
    for _ in range(4):
        llm.queue_response("I am not following the protocol.")

    result = run_loop("A confusing question", llm_client=llm, tools={})

    assert result.kind == "not_supported"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/orchestration/test_loop.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aijudge.orchestration.loop'`

- [ ] **Step 3: Write the implementation**

```python
# src/aijudge/orchestration/loop.py
import json
from dataclasses import dataclass
from typing import Callable

from aijudge.llm.client import LLMClient
from aijudge.rules_engine.resolve import UnsupportedScenarioError

from .confidence import DEFAULT_CONFIDENCE_THRESHOLD, SignalState, compute_confidence, update_signals
from .protocol import FinalAnswer, ProtocolError, ToolCall, build_system_prompt, parse_response

MAX_MALFORMED_RETRIES = 3
NOT_SUPPORTED_MESSAGE = "not supported yet, contact dev team"
ESCALATE_MESSAGE = "escalate to a human judge"


@dataclass
class LoopResult:
    kind: str
    text: str


def run_loop(
    question: str,
    *,
    llm_client: LLMClient,
    tools: dict[str, Callable[[dict], dict]],
    clarification_context: str = "",
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> LoopResult:
    conversation = build_system_prompt() + "\n\nQuestion: " + question
    if clarification_context:
        conversation += "\n\n" + clarification_context

    state = SignalState()
    malformed_count = 0

    while True:
        response = llm_client.complete(conversation)

        try:
            parsed = parse_response(response)
        except ProtocolError as error:
            malformed_count += 1
            if malformed_count > MAX_MALFORMED_RETRIES:
                return LoopResult(kind="not_supported", text=NOT_SUPPORTED_MESSAGE)
            conversation += f"\n\nERROR: {error}"
            continue

        if isinstance(parsed, ToolCall):
            tool = tools[parsed.name]
            try:
                result = tool(parsed.args)
            except UnsupportedScenarioError:
                return LoopResult(kind="not_supported", text=NOT_SUPPORTED_MESSAGE)
            update_signals(state, parsed.name, result)
            conversation += f"\n\nTOOL RESULT ({parsed.name}): {json.dumps(result)}"
            continue

        assert isinstance(parsed, FinalAnswer)
        score = compute_confidence(parsed.cited_ids, state)
        if score < threshold:
            return LoopResult(kind="escalate", text=ESCALATE_MESSAGE)
        return LoopResult(kind="answer", text=parsed.text)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/orchestration/test_loop.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/orchestration/loop.py tests/orchestration/test_loop.py
git commit -m "feat(orchestration): tool-use loop with deterministic escalation gating"
```

---

### Task 9: CLI

**Files:**
- Create: `src/aijudge/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `LLMClient` from `llm.client`; `EmbeddingClient` from `embeddings.client`; `build_clarification_prompt`, `clarification_prompt_text`, `format_clarification_context`, `parse_clarification_response` from `orchestration.clarify` (Task 5); `build_tool_dispatch` from `orchestration.tools` (Task 7); `run_loop` from `orchestration.loop` (Task 8).
- Produces: `run_cli(llm_client: LLMClient, embedding_client: EmbeddingClient, *, input_fn: Callable[[str], str] = input, print_fn: Callable[[str], None] = print) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cli.py
from aijudge.cli import run_cli
from aijudge.embeddings.client import MockEmbeddingClient
from aijudge.llm.client import MockLLMClient


def test_run_cli_exits_immediately_on_quit():
    printed = []
    inputs = iter(["quit"])

    run_cli(MockLLMClient(), MockEmbeddingClient(), input_fn=lambda _: next(inputs), print_fn=printed.append)

    assert any("AIJudge" in line for line in printed)


def test_run_cli_exits_on_eof():
    printed = []

    def _input(_prompt):
        raise EOFError

    run_cli(MockLLMClient(), MockEmbeddingClient(), input_fn=_input, print_fn=printed.append)

    assert any("AIJudge" in line for line in printed)


def test_run_cli_answers_a_question_with_no_clarification_needed():
    printed = []
    inputs = iter(["What does Card X do?", "quit"])

    llm = MockLLMClient()
    llm.queue_response("PROCEED")
    llm.queue_response("FINAL: It does X. ||CITES: ||")

    run_cli(llm, MockEmbeddingClient(), input_fn=lambda _: next(inputs), print_fn=printed.append)

    assert "It does X." in printed


def test_run_cli_asks_clarification_questions_before_answering():
    printed = []
    inputs = iter(["Can I respond to this?", "Blue-Eyes White Dragon", "quit"])

    llm = MockLLMClient()
    llm.queue_response("CLARIFY: Which monster do you control?")
    llm.queue_response("FINAL: Yes, you can respond. ||CITES: ||")

    run_cli(llm, MockEmbeddingClient(), input_fn=lambda _: next(inputs), print_fn=printed.append)

    assert "Yes, you can respond." in printed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aijudge.cli'`

- [ ] **Step 3: Write the implementation**

```python
# src/aijudge/cli.py
from typing import Callable

from aijudge.embeddings.client import EmbeddingClient
from aijudge.llm.client import LLMClient

from .orchestration.clarify import (
    build_clarification_prompt,
    clarification_prompt_text,
    format_clarification_context,
    parse_clarification_response,
)
from .orchestration.loop import run_loop
from .orchestration.tools import build_tool_dispatch


def run_cli(
    llm_client: LLMClient,
    embedding_client: EmbeddingClient,
    *,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
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

        clarify_response = llm_client.complete(build_clarification_prompt(stripped))
        items = parse_clarification_response(clarify_response)
        answers = [input_fn(f"{clarification_prompt_text(item)} ") for item in items]
        context = format_clarification_context(items, answers)

        result = run_loop(stripped, llm_client=llm_client, tools=tools, clarification_context=context)
        print_fn(result.text)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/cli.py tests/test_cli.py
git commit -m "feat: add REPL CLI driving the orchestration loop"
```

---

## Final Verification

- [ ] Run the full suite: `pytest -v` — expect all pure-Python tests passing, DB tests skipped without `DATABASE_URL`.
- [ ] With `docker compose up -d db` and `DATABASE_URL` set: `pytest -v` — expect all tests passing, including Tasks 2 and 6's DB-dependent cases.
