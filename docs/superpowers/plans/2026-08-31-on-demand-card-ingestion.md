# On-Demand Card Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When `lookup_card` misses the DB, automatically and synchronously fetch-and-ingest the card via the existing `seed_card()` pipeline so a first-ever question about a real (previously unseeded) card has a chance of being answered instead of always escalating.

**Architecture:** All new logic lives in `orchestration/tools.py`. `lookup_card` gains optional kwargs (`llm_client`, `online_ingest_enabled`, `fetch_card_fn`, `fetch_rulings_fn`, `on_ingest_start`) so a DB miss falls through to `ingestion.seed.seed_card()`, then re-queries the DB and returns the same `{"found": True, ...}` shape as a cache hit. `build_tool_dispatch` threads a new required `llm_client` param through and defaults `online_ingest_enabled=True` for real callers, while `lookup_card` itself defaults it `False` so existing direct callers are unaffected. `cli.py` wires a progress-message callback to `print_fn`; `api/app.py` wires none. Both `entrypoint.py` (CLI, OpenRouter wiring) and `api/__main__.py` read a new `AIJUDGE_ENABLE_ONLINE_INGEST` env var (default `true`) once at startup and pass it through.

**Tech Stack:** Python, psycopg3 (for catching `psycopg.errors.UniqueViolation` on the insert-race path), pytest with `MockLLMClient`/`MockEmbeddingClient`/`monkeypatch`, existing `ingestion.seed.seed_card()` and `ingestion.ygoprodeck_client.fetch_card`/`CardNotFoundError`.

**Spec:** `docs/superpowers/specs/2026-08-31-on-demand-card-ingestion-design.md`

## Global Constraints

- The ingest attempt is triggered **deterministically inside `lookup_card`** on a DB miss — the LLM never chooses whether to invoke it (no new tool is added).
- **Synchronous, single round-trip**: the call blocks on `seed_card()` and answers in the same request. No job store, no polling, no SSE.
- `lookup_card`'s `online_ingest_enabled` parameter **defaults to `False` on the function itself** so every existing direct call (`lookup_card({"name": ...})` in tests) keeps passing unchanged. `build_tool_dispatch` is what defaults it to `True` for real usage.
- `build_tool_dispatch` gains a **required** `llm_client` parameter, ordered **before** `embedding_client`: `build_tool_dispatch(llm_client, embedding_client, *, online_ingest_enabled=True, on_ingest_start=None)`.
- `AIJUDGE_ENABLE_ONLINE_INGEST` (default `"true"`) is read **once at startup**, only in `entrypoint.py` (CLI/OpenRouter wiring) and `api/__main__.py` — not in `aijudge/__main__.py` (Ollama default) and not hot-reloaded.
- Card-name resolution for the live fetch is **exact-match only** — no fuzzy matching. A mismatch surfaces as an ordinary `CardNotFoundError` → `{"found": False}`.
- No changes to `ingestion/seed.py` — `seed_card()` already does exactly what's needed.
- No rulebook/embedding ingestion is added for a newly-fetched card.
- Every failure branch (not found, race, unexpected error) converges on the same `{"found": False}` shape the tool already returns today — `loop.py`/`confidence.py` need zero changes.

---

## Task 1: `lookup_card` online-ingest core logic

**Files:**
- Modify: `src/aijudge/orchestration/tools.py`
- Test: `tests/orchestration/test_tools_db.py`

**Interfaces:**
- Consumes: `aijudge.db.cards_repo.get_card_by_name(name: str) -> dict | None`; `aijudge.db.effects_repo.get_confirmed_effects(card_id: str) -> list[dict]`; `aijudge.ingestion.seed.seed_card(name: str, *, llm_client, fetch_card_fn=fetch_card, fetch_rulings_fn=fetch_rulings) -> str` (raises `aijudge.ingestion.ygoprodeck_client.CardNotFoundError` on a ygoprodeck miss, or `psycopg.errors.UniqueViolation` if `cards.name`'s UNIQUE constraint is hit); `aijudge.llm.client.LLMClient` (`complete(prompt, *, system=None) -> str`).
- Produces: `lookup_card(args: dict, *, llm_client: LLMClient | None = None, online_ingest_enabled: bool = False, fetch_card_fn: Callable[..., dict] = fetch_card, fetch_rulings_fn: Callable[..., list[dict]] = fetch_rulings, on_ingest_start: Callable[[str], None] | None = None) -> dict` — same `{"found": bool, ...}` shape as before; Task 2's `build_tool_dispatch` calls this with all five kwargs.

- [ ] **Step 1: Write the failing tests**

Append to `tests/orchestration/test_tools_db.py` (this file already has `pytestmark = pytest.mark.skipif("DATABASE_URL" not in os.environ, ...)` and a `setup_function` that truncates `cards` — no changes needed to either):

```python
def test_lookup_card_ingests_unknown_card_on_miss_when_online_ingest_enabled():
    from aijudge.db.cards_repo import get_card_by_name
    from aijudge.llm.client import MockLLMClient
    from aijudge.orchestration.tools import lookup_card

    desc = "You can target 1 banished monster; banish it."

    def fake_fetch_card(name, http_get=None):
        return {"id": 47355498, "name": name, "type": "Quick-Play Spell", "desc": desc}

    def fake_fetch_rulings(name, http_get=None):
        return [{"text": "Can target monsters banished this turn.", "date": "2021-01-01"}]

    llm_client = MockLLMClient()
    llm_client.queue_response(desc)  # split proposal: one effect, unchanged
    llm_client.queue_response("0.97")  # review agent confidence

    result = lookup_card(
        {"name": "Called by the Grave"},
        llm_client=llm_client,
        online_ingest_enabled=True,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=fake_fetch_rulings,
    )

    assert result["found"] is True
    assert result["name"] == "Called by the Grave"
    assert result["card_text"] == desc
    assert len(result["confirmed_effects"]) == 1
    assert get_card_by_name("Called by the Grave") is not None


def test_lookup_card_returns_not_found_when_card_not_found_error_is_raised():
    from aijudge.db.cards_repo import get_card_by_name
    from aijudge.ingestion.ygoprodeck_client import CardNotFoundError
    from aijudge.llm.client import MockLLMClient
    from aijudge.orchestration.tools import lookup_card

    def fake_fetch_card(name, http_get=None):
        raise CardNotFoundError(f"no card found for name={name!r}")

    result = lookup_card(
        {"name": "Definitely Not A Real Card"},
        llm_client=MockLLMClient(),
        online_ingest_enabled=True,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=lambda name, http_get=None: [],
    )

    assert result == {"found": False}
    assert get_card_by_name("Definitely Not A Real Card") is None


def test_lookup_card_reuses_existing_row_on_unique_violation_race():
    from datetime import date

    from aijudge.db.cards_repo import get_card_by_name, insert_card
    from aijudge.llm.client import MockLLMClient
    from aijudge.orchestration.tools import lookup_card

    def fake_fetch_card(name, http_get=None):
        # Simulate a concurrent request winning the insert race: by the time
        # our own seed_card() tries to INSERT, this row already exists.
        insert_card(
            name=name,
            card_text="a pre-existing race winner's text",
            card_type="Trap",
            source="ygoprodeck",
            fetched_at=date(2026, 8, 31),
            ygoprodeck_id="99999999",
        )
        return {"id": 12345678, "name": name, "type": "Trap Card", "desc": "irrelevant, insert fails first"}

    llm_client = MockLLMClient()  # no responses queued: insert_card raises
    # before seed_card ever reaches clause-splitting/review

    result = lookup_card(
        {"name": "Race Card"},
        llm_client=llm_client,
        online_ingest_enabled=True,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=lambda name, http_get=None: [],
    )

    assert result["found"] is True
    assert result["card_text"] == "a pre-existing race winner's text"
    assert get_card_by_name("Race Card") is not None


def test_lookup_card_online_ingest_disabled_never_calls_fetch_card_fn():
    from aijudge.orchestration.tools import lookup_card

    calls = []

    def fake_fetch_card(name, http_get=None):
        calls.append(name)
        raise AssertionError("fetch_card_fn should never be called when online_ingest_enabled is False")

    result = lookup_card({"name": "Some Card"}, fetch_card_fn=fake_fetch_card)

    assert result == {"found": False}
    assert calls == []


def test_lookup_card_calls_on_ingest_start_once_on_miss_and_not_on_hit():
    from aijudge.llm.client import MockLLMClient
    from aijudge.orchestration.tools import lookup_card

    calls = []

    def fake_fetch_card(name, http_get=None):
        return {"id": 55667788, "name": name, "type": "Trap Card", "desc": "Target 1 card; destroy it."}

    llm_client = MockLLMClient()
    llm_client.queue_response("Target 1 card; destroy it.")
    llm_client.queue_response("0.97")

    result = lookup_card(
        {"name": "Fresh Card"},
        llm_client=llm_client,
        online_ingest_enabled=True,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=lambda name, http_get=None: [],
        on_ingest_start=calls.append,
    )
    assert result["found"] is True
    assert calls == ["Fresh Card"]

    calls.clear()
    hit = lookup_card(
        {"name": "Fresh Card"},
        llm_client=llm_client,
        online_ingest_enabled=True,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=lambda name, http_get=None: [],
        on_ingest_start=calls.append,
    )
    assert hit["found"] is True
    assert calls == []


def test_lookup_card_logs_and_returns_not_found_on_unexpected_ingest_error():
    from aijudge.llm.client import MockLLMClient
    from aijudge.orchestration.tools import lookup_card

    def fake_fetch_card(name, http_get=None):
        raise RuntimeError("network exploded")

    result = lookup_card(
        {"name": "Unlucky Card"},
        llm_client=MockLLMClient(),
        online_ingest_enabled=True,
        fetch_card_fn=fake_fetch_card,
        fetch_rulings_fn=lambda name, http_get=None: [],
    )

    assert result == {"found": False}
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `pytest tests/orchestration/test_tools_db.py -v` (requires `DATABASE_URL` set and the DB up — `docker compose up -d db` first if needed)
Expected: the six new tests FAIL (`lookup_card() got an unexpected keyword argument 'llm_client'` or similar — `lookup_card` doesn't accept these kwargs yet).

- [ ] **Step 3: Implement `lookup_card`'s online-ingest logic**

Replace the top of `src/aijudge/orchestration/tools.py` (imports through `lookup_card`) with:

```python
import logging
from dataclasses import asdict
from typing import Callable

import psycopg

from aijudge.db.cards_repo import get_card_by_name
from aijudge.db.effects_repo import get_confirmed_effects
from aijudge.db.rulebook_repo import search_chunks
from aijudge.db.rulings_repo import get_rulings_for_card
from aijudge.embeddings.client import EmbeddingClient
from aijudge.ingestion.seed import seed_card
from aijudge.ingestion.ygoprodeck_client import CardNotFoundError, fetch_card
from aijudge.ingestion.ygoresources_client import fetch_rulings
from aijudge.llm.client import LLMClient
from aijudge.rules_engine.resolve import resolve_chain as _resolve_chain_scenario

logger = logging.getLogger(__name__)

DEFAULT_MAX_DISTANCE = 0.15


def _card_result(card: dict) -> dict:
    return {
        "found": True,
        "id": card["id"],
        "name": card["name"],
        "card_text": card["card_text"],
        "card_type": card["card_type"],
        "confirmed_effects": get_confirmed_effects(card["id"]),
    }


def lookup_card(
    args: dict,
    *,
    llm_client: LLMClient | None = None,
    online_ingest_enabled: bool = False,
    fetch_card_fn: Callable[..., dict] = fetch_card,
    fetch_rulings_fn: Callable[..., list[dict]] = fetch_rulings,
    on_ingest_start: Callable[[str], None] | None = None,
) -> dict:
    name = args["name"]
    card = get_card_by_name(name)
    if card is not None:
        return _card_result(card)

    if not online_ingest_enabled:
        return {"found": False}

    if on_ingest_start is not None:
        on_ingest_start(name)

    try:
        seed_card(name, llm_client=llm_client, fetch_card_fn=fetch_card_fn, fetch_rulings_fn=fetch_rulings_fn)
    except CardNotFoundError:
        return {"found": False}
    except psycopg.errors.UniqueViolation:
        pass  # a concurrent request won the insert race -- fall through and re-fetch its row
    except Exception:
        logger.exception("online ingest failed for card name=%r", name)
        return {"found": False}

    card = get_card_by_name(name)
    if card is None:
        return {"found": False}
    return _card_result(card)
```

Leave `get_rulings`, `_search_rulebook`, and `resolve_chain` exactly as they are below this. `build_tool_dispatch` (further down) is untouched in this task — Task 2 modifies it.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/orchestration/test_tools_db.py -v`
Expected: PASS — all tests in the file, including the six new ones and the two pre-existing `lookup_card` tests (`test_lookup_card_returns_card_text_and_not_found_flag`, `test_lookup_card_includes_confirmed_effects_when_present`), which must stay green untouched since they call `lookup_card({"name": ...})` with no kwargs and rely on `online_ingest_enabled` defaulting to `False`.

- [ ] **Step 5: Run the full suite once to check for regressions**

Run: `pytest -v`
Expected: all tests PASS (DB-independent suites always run; DB suites run if `DATABASE_URL` is set).

- [ ] **Step 6: Commit**

```bash
git add src/aijudge/orchestration/tools.py tests/orchestration/test_tools_db.py
git commit -m "feat: lookup_card falls back to live ingest on a DB miss"
```

---

## Task 2: `build_tool_dispatch` threads `llm_client` and online-ingest wiring

**Files:**
- Modify: `src/aijudge/orchestration/tools.py`
- Test: `tests/orchestration/test_tools.py`

**Interfaces:**
- Consumes: `lookup_card` from Task 1 (all five kwargs).
- Produces: `build_tool_dispatch(llm_client: LLMClient, embedding_client: EmbeddingClient, *, online_ingest_enabled: bool = True, on_ingest_start: Callable[[str], None] | None = None) -> dict[str, Callable[[dict], dict]]` — the `"lookup_card"` entry is now a closure over `llm_client`/`online_ingest_enabled`/`on_ingest_start`. Tasks 3 and 5 call this with `(llm_client, embedding_client, ...)` positionally in that order.

- [ ] **Step 1: Write the failing tests**

Replace `tests/orchestration/test_tools.py` in full with:

```python
import pytest

from aijudge.embeddings.client import MockEmbeddingClient
from aijudge.llm.client import MockLLMClient
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
    dispatch = build_tool_dispatch(MockLLMClient(), MockEmbeddingClient())
    assert set(dispatch.keys()) == {"lookup_card", "get_rulings", "search_rulebook", "resolve_chain"}


def test_build_tool_dispatch_lookup_card_skips_ingest_when_disabled(monkeypatch):
    from aijudge.orchestration import tools as tools_module

    monkeypatch.setattr(tools_module, "get_card_by_name", lambda name: None)

    seed_calls = []
    monkeypatch.setattr(tools_module, "seed_card", lambda *args, **kwargs: seed_calls.append((args, kwargs)))

    dispatch = build_tool_dispatch(MockLLMClient(), MockEmbeddingClient(), online_ingest_enabled=False)
    result = dispatch["lookup_card"]({"name": "Nonexistent Card"})

    assert result == {"found": False}
    assert seed_calls == []
```

- [ ] **Step 2: Run the tests to verify the new ones fail**

Run: `pytest tests/orchestration/test_tools.py -v`
Expected: `test_build_tool_dispatch_has_all_four_tools` and `test_build_tool_dispatch_lookup_card_skips_ingest_when_disabled` FAIL (`build_tool_dispatch() missing 1 required positional argument` — the function still only accepts `embedding_client`).

- [ ] **Step 3: Implement the new `build_tool_dispatch`**

In `src/aijudge/orchestration/tools.py`, replace:

```python
def build_tool_dispatch(embedding_client: EmbeddingClient) -> dict[str, Callable[[dict], dict]]:
    return {
        "lookup_card": lookup_card,
        "get_rulings": get_rulings,
        "search_rulebook": lambda args: _search_rulebook(args, embedding_client=embedding_client),
        "resolve_chain": resolve_chain,
    }
```

with:

```python
def build_tool_dispatch(
    llm_client: LLMClient,
    embedding_client: EmbeddingClient,
    *,
    online_ingest_enabled: bool = True,
    on_ingest_start: Callable[[str], None] | None = None,
) -> dict[str, Callable[[dict], dict]]:
    return {
        "lookup_card": lambda args: lookup_card(
            args,
            llm_client=llm_client,
            online_ingest_enabled=online_ingest_enabled,
            on_ingest_start=on_ingest_start,
        ),
        "get_rulings": get_rulings,
        "search_rulebook": lambda args: _search_rulebook(args, embedding_client=embedding_client),
        "resolve_chain": resolve_chain,
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/orchestration/test_tools.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/orchestration/tools.py tests/orchestration/test_tools.py
git commit -m "feat: build_tool_dispatch threads llm_client and online-ingest wiring"
```

---

## Task 3: `cli.py` progress message and `online_ingest_enabled` passthrough

**Files:**
- Modify: `src/aijudge/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `build_tool_dispatch(llm_client, embedding_client, *, online_ingest_enabled=True, on_ingest_start=None)` from Task 2.
- Produces: `run_cli(llm_client, embedding_client, *, input_fn=input, print_fn=print, find_matched_cards_fn=find_matched_cards, build_known_facts_context_fn=build_known_facts_context, online_ingest_enabled: bool = True) -> None`. Task 4's `entrypoint.py` passes `online_ingest_enabled` explicitly; `aijudge/__main__.py` (Ollama default, not modified by this plan) relies on the `True` default.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_run_cli_wires_on_ingest_start_callback_to_print_fn(monkeypatch):
    import aijudge.cli as cli_module

    captured = {}

    def fake_build_tool_dispatch(llm_client, embedding_client, *, online_ingest_enabled=True, on_ingest_start=None):
        captured["on_ingest_start"] = on_ingest_start
        captured["online_ingest_enabled"] = online_ingest_enabled
        return {}

    monkeypatch.setattr(cli_module, "build_tool_dispatch", fake_build_tool_dispatch)

    printed = []
    inputs = iter(["quit"])
    run_cli(MockLLMClient(), MockEmbeddingClient(), input_fn=lambda _: next(inputs), print_fn=printed.append)

    assert captured["online_ingest_enabled"] is True
    captured["on_ingest_start"]("Some New Card")
    assert any("Some New Card" in line for line in printed)


def test_run_cli_passes_online_ingest_enabled_through_to_tool_dispatch(monkeypatch):
    import aijudge.cli as cli_module

    captured = {}

    def fake_build_tool_dispatch(llm_client, embedding_client, *, online_ingest_enabled=True, on_ingest_start=None):
        captured["online_ingest_enabled"] = online_ingest_enabled
        return {}

    monkeypatch.setattr(cli_module, "build_tool_dispatch", fake_build_tool_dispatch)

    inputs = iter(["quit"])
    run_cli(
        MockLLMClient(),
        MockEmbeddingClient(),
        input_fn=lambda _: next(inputs),
        print_fn=lambda _: None,
        online_ingest_enabled=False,
    )

    assert captured["online_ingest_enabled"] is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_cli.py -v`
Expected: the two new tests FAIL — `run_cli() got an unexpected keyword argument 'online_ingest_enabled'`, and `captured` stays empty because today's `build_tool_dispatch(embedding_client)` call doesn't match the fake's signature.

- [ ] **Step 3: Implement the wiring**

In `src/aijudge/cli.py`, replace:

```python
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
```

with:

```python
def run_cli(
    llm_client: LLMClient,
    embedding_client: EmbeddingClient,
    *,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
    find_matched_cards_fn: Callable[[str], list[dict]] = find_matched_cards,
    build_known_facts_context_fn: Callable[[dict], str] = build_known_facts_context,
    online_ingest_enabled: bool = True,
) -> None:
    tools = build_tool_dispatch(
        llm_client,
        embedding_client,
        online_ingest_enabled=online_ingest_enabled,
        on_ingest_start=lambda name: print_fn(f"Looking up {name}, this may take a moment..."),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_cli.py -v`
Expected: PASS — all tests in the file, including the pre-existing ones (none of them queue a `TOOL: lookup_card` response, so the real `build_tool_dispatch` is exercised without ever invoking `lookup_card`, and no DB access happens).

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/cli.py tests/test_cli.py
git commit -m "feat: cli.py shows a progress message before live card ingest"
```

---

## Task 4: `entrypoint.py` reads `AIJUDGE_ENABLE_ONLINE_INGEST`

**Files:**
- Modify: `src/aijudge/entrypoint.py`
- Test: `tests/test_entrypoint.py`

**Interfaces:**
- Consumes: `run_cli(..., online_ingest_enabled: bool = True)` from Task 3.
- Produces: `entrypoint._online_ingest_enabled() -> bool`, called once inside `entrypoint.main()`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_entrypoint.py`, replace `test_main_builds_real_clients_and_runs_cli` with a version whose fake accepts the new kwarg, and add three new tests. The full new bottom of the file (everything from that test onward):

```python
def test_main_builds_real_clients_and_runs_cli(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("OPENAI_API_KEY", "oa-key")
    captured = {}

    def fake_run_cli(llm_client, embedding_client, **kwargs):
        captured["llm_client"] = llm_client
        captured["embedding_client"] = embedding_client

    monkeypatch.setattr(entrypoint, "run_cli", fake_run_cli)

    entrypoint.main()

    assert isinstance(captured["llm_client"], OpenRouterLLMClient)
    assert isinstance(captured["embedding_client"], OpenAIEmbeddingClient)


def test_online_ingest_enabled_defaults_to_true(monkeypatch):
    monkeypatch.delenv("AIJUDGE_ENABLE_ONLINE_INGEST", raising=False)
    assert entrypoint._online_ingest_enabled() is True


def test_online_ingest_enabled_reads_false_from_env(monkeypatch):
    monkeypatch.setenv("AIJUDGE_ENABLE_ONLINE_INGEST", "false")
    assert entrypoint._online_ingest_enabled() is False


def test_online_ingest_enabled_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("AIJUDGE_ENABLE_ONLINE_INGEST", "FALSE")
    assert entrypoint._online_ingest_enabled() is False


def test_main_passes_online_ingest_toggle_to_run_cli(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("OPENAI_API_KEY", "oa-key")
    monkeypatch.setenv("AIJUDGE_ENABLE_ONLINE_INGEST", "false")
    captured = {}

    def fake_run_cli(llm_client, embedding_client, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(entrypoint, "run_cli", fake_run_cli)

    entrypoint.main()

    assert captured["online_ingest_enabled"] is False
```

- [ ] **Step 2: Run the tests to verify the new/changed ones fail**

Run: `pytest tests/test_entrypoint.py -v`
Expected: `test_online_ingest_enabled_defaults_to_true`, `test_online_ingest_enabled_reads_false_from_env`, `test_online_ingest_enabled_is_case_insensitive` FAIL with `AttributeError: module 'aijudge.entrypoint' has no attribute '_online_ingest_enabled'`; `test_main_passes_online_ingest_toggle_to_run_cli` FAILS with `KeyError: 'online_ingest_enabled'`.

- [ ] **Step 3: Implement the toggle**

In `src/aijudge/entrypoint.py`, replace:

```python
def main() -> None:
    load_dotenv()
    run_cli(build_llm_client(), build_embedding_client())
```

with:

```python
def _online_ingest_enabled() -> bool:
    return os.environ.get("AIJUDGE_ENABLE_ONLINE_INGEST", "true").strip().lower() != "false"


def main() -> None:
    load_dotenv()
    run_cli(build_llm_client(), build_embedding_client(), online_ingest_enabled=_online_ingest_enabled())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_entrypoint.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aijudge/entrypoint.py tests/test_entrypoint.py
git commit -m "feat: entrypoint.py reads AIJUDGE_ENABLE_ONLINE_INGEST toggle"
```

---

## Task 5: `api/app.py` and `api/__main__.py` online-ingest passthrough

**Files:**
- Modify: `src/aijudge/api/app.py`
- Modify: `src/aijudge/api/__main__.py`
- Test: `tests/api/test_app.py`
- Test: `tests/api/test_main.py`

**Interfaces:**
- Consumes: `build_tool_dispatch(llm_client, embedding_client, *, online_ingest_enabled=True, on_ingest_start=None)` from Task 2.
- Produces: `create_app(llm_client, embedding_client, *, cors_origins=None, tools=None, find_matched_cards_fn=None, build_known_facts_context_fn=None, online_ingest_enabled: bool = True) -> FastAPI`; `api/__main__.py`'s `main()` reads `AIJUDGE_ENABLE_ONLINE_INGEST` via a new `_online_ingest_enabled_from_env()` and passes it to `create_app`. No `on_ingest_start` is ever passed here (silent on a cache miss, per the deferred-SSE decision).

- [ ] **Step 1: Write the failing tests**

Append to `tests/api/test_app.py`:

```python
def test_create_app_defaults_online_ingest_enabled_to_true(monkeypatch):
    import aijudge.api.app as app_module

    captured = {}

    def fake_build_tool_dispatch(llm_client, embedding_client, *, online_ingest_enabled=True, on_ingest_start=None):
        captured["online_ingest_enabled"] = online_ingest_enabled
        captured["on_ingest_start"] = on_ingest_start
        return {}

    monkeypatch.setattr(app_module, "build_tool_dispatch", fake_build_tool_dispatch)

    create_app(MockLLMClient(), MockEmbeddingClient(), find_matched_cards_fn=lambda question: [])

    assert captured["online_ingest_enabled"] is True
    assert captured["on_ingest_start"] is None


def test_create_app_passes_online_ingest_enabled_false_through(monkeypatch):
    import aijudge.api.app as app_module

    captured = {}

    def fake_build_tool_dispatch(llm_client, embedding_client, *, online_ingest_enabled=True, on_ingest_start=None):
        captured["online_ingest_enabled"] = online_ingest_enabled
        return {}

    monkeypatch.setattr(app_module, "build_tool_dispatch", fake_build_tool_dispatch)

    create_app(
        MockLLMClient(),
        MockEmbeddingClient(),
        online_ingest_enabled=False,
        find_matched_cards_fn=lambda question: [],
    )

    assert captured["online_ingest_enabled"] is False
```

Append to `tests/api/test_main.py`:

```python
def test_main_passes_online_ingest_toggle_from_env(monkeypatch):
    monkeypatch.setenv("AIJUDGE_ENABLE_ONLINE_INGEST", "false")
    captured = {}

    monkeypatch.setattr(
        main_module,
        "create_app",
        lambda llm, emb, **kwargs: captured.update(kwargs),
    )

    main(
        llm_client=_StubLLMClient(),
        embedding_client=_StubEmbeddingClient(),
        run_fn=lambda app, **kwargs: None,
    )

    assert captured["online_ingest_enabled"] is False


def test_main_defaults_online_ingest_toggle_to_true(monkeypatch):
    monkeypatch.delenv("AIJUDGE_ENABLE_ONLINE_INGEST", raising=False)
    captured = {}

    monkeypatch.setattr(
        main_module,
        "create_app",
        lambda llm, emb, **kwargs: captured.update(kwargs),
    )

    main(
        llm_client=_StubLLMClient(),
        embedding_client=_StubEmbeddingClient(),
        run_fn=lambda app, **kwargs: None,
    )

    assert captured["online_ingest_enabled"] is True
```

`tests/api/test_app.py` already imports `MockLLMClient` from `aijudge.llm.client` and `create_app` from `aijudge.api.app` at the top of the file — no new imports needed there.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/api/test_app.py tests/api/test_main.py -v`
Expected: the four new tests FAIL — `create_app() got an unexpected keyword argument 'online_ingest_enabled'` for the `test_app.py` pair, and `KeyError: 'online_ingest_enabled'` for the `test_main.py` pair (today's `create_app` call never passes it).

- [ ] **Step 3: Implement the passthrough**

In `src/aijudge/api/app.py`, change the `create_app` signature and its `tools` default:

```python
def create_app(
    llm_client: LLMClient,
    embedding_client: EmbeddingClient,
    *,
    cors_origins: list[str] | None = None,
    tools: dict[str, Callable[[dict], dict]] | None = None,
    find_matched_cards_fn: Callable[[str], list[dict]] | None = None,
    build_known_facts_context_fn: Callable[[dict], str] | None = None,
    online_ingest_enabled: bool = True,
) -> FastAPI:
    app = FastAPI()
    # Test-only seam: real callers never pass `tools` and get the DB/embedding-
    # backed dispatch below; tests can inject a stub dispatch to exercise the
    # citation-serialization path (lookup_card, etc.) without a live DB.
    tools = (
        tools
        if tools is not None
        else build_tool_dispatch(llm_client, embedding_client, online_ingest_enabled=online_ingest_enabled)
    )
```

(Only the `create_app` signature and the `tools = ...` line change; everything else in `app.py` stays as-is.)

In `src/aijudge/api/__main__.py`, replace:

```python
def main(
    *,
    llm_client: LLMClient | None = None,
    embedding_client: EmbeddingClient | None = None,
    run_fn: Callable = uvicorn.run,
) -> None:
    app = create_app(
        llm_client or OllamaLLMClient(),
        embedding_client or OllamaEmbeddingClient(),
        cors_origins=_cors_origins_from_env(),
    )
```

with:

```python
def _online_ingest_enabled_from_env() -> bool:
    return os.environ.get("AIJUDGE_ENABLE_ONLINE_INGEST", "true").strip().lower() != "false"


def main(
    *,
    llm_client: LLMClient | None = None,
    embedding_client: EmbeddingClient | None = None,
    run_fn: Callable = uvicorn.run,
) -> None:
    app = create_app(
        llm_client or OllamaLLMClient(),
        embedding_client or OllamaEmbeddingClient(),
        cors_origins=_cors_origins_from_env(),
        online_ingest_enabled=_online_ingest_enabled_from_env(),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/api/test_app.py tests/api/test_main.py -v`
Expected: PASS — including all pre-existing tests in both files (none of them queue a `TOOL: lookup_card` LLM response, so the real `build_tool_dispatch(llm, MockEmbeddingClient())` construction in `_client()` never touches the DB).

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/aijudge/api/app.py src/aijudge/api/__main__.py tests/api/test_app.py tests/api/test_main.py
git commit -m "feat: api layer reads AIJUDGE_ENABLE_ONLINE_INGEST toggle"
```

---

## Self-Review Notes

- **Spec coverage:** Trigger point (Task 1: no LLM tool involved, `lookup_card` decides deterministically) — covered. Blocking model (Task 1: `seed_card()` called inline, no job store) — covered. CLI progress message (Task 3) — covered. Feature toggle in `entrypoint.py`/`api/__main__.py` only, default `true` (Tasks 4–5) — covered. Component design's exact `lookup_card`/`build_tool_dispatch` signatures (Tasks 1–2) — covered verbatim, including the `False`-on-the-function/`True`-in-the-builder default split. Data flow's four branches (hit passthrough unchanged; success re-fetch; `CardNotFoundError`; unique-violation re-fetch; any-other-exception) — all five (four listed plus the pre-existing hit path) covered by Task 1's tests. Name resolution (exact-match, no fuzzy layer) — no new code needed; `fetch_card_fn` is called with `args["name"]` verbatim, same as today. Testing section's enumerated test list — every bullet has a corresponding test in Tasks 1, 2, 3. Out-of-scope items (async job/polling, SSE, fuzzy matching, per-user rate limiting, rulebook ingestion) — deliberately not implemented anywhere in this plan.
- **Placeholder scan:** no TBD/TODO markers; every step has literal code.
- **Type consistency:** `lookup_card`'s kwargs (`llm_client`, `online_ingest_enabled`, `fetch_card_fn`, `fetch_rulings_fn`, `on_ingest_start`) are identical across Tasks 1–3. `build_tool_dispatch(llm_client, embedding_client, *, online_ingest_enabled, on_ingest_start)` ordering is identical across Tasks 2, 3, 5. `_online_ingest_enabled()` (entrypoint.py) and `_online_ingest_enabled_from_env()` (api/__main__.py) are two separate private helpers with the same body, matching each module's existing pattern of its own private env-reading helper (`_require_env`, `_cors_origins_from_env`) rather than a shared cross-module utility.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-31-on-demand-card-ingestion.md`. Two execution options:

1. **Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
