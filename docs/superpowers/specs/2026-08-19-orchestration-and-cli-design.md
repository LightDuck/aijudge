# AIJudge — LLM Orchestration & CLI Design

## Purpose

This document specs sub-projects 4 and 5 from the thin-slice design
(`docs/superpowers/specs/2026-08-18-thin-slice-design.md`): the
agentic tool-use loop that lets the LLM answer rules questions by
calling into the DB and rules engine, and the CLI that drives it.
Everything else — data layer, effect parser, rules engine primitives —
already exists; this closes the loop between them.

Per the thin slice's non-goals, this design keeps LLM calls mocked
end-to-end (`MockLLMClient`); no real provider is wired in. Production
Claude wiring is a later, separate swap behind the same interface.

## Existing gaps this design closes

Two things the spec assumed but that don't exist in code yet:

1. **No composed chain-resolution entry point.** `rules_engine/chain.py`,
   `segoc.py`, `priority.py`, and `timing.py` are separate primitives;
   nothing wires them into the single `resolve_chain` tool the spec
   describes.
2. **No vector search.** `rulebook_repo.py` and `rulings_repo.py` only
   support inserts; there is no semantic query function anywhere,
   despite `search_rulebook` requiring one.

Both are in scope for this design, since the orchestration tools
cannot be built without them.

## Tool-call protocol

`LLMClient` stays exactly as it is today — `complete(prompt: str) ->
str` — no interface changes. The orchestrator enforces a text
convention on top of it rather than extending the client to carry
structured tool calls. This was a deliberate choice: it keeps
`LLMClient` unchanged, at the cost of the orchestrator owning a small
parser that a future structured-tool-use provider integration may
partially replace.

The LLM's response, on each turn of the loop, must be either a single
tool call or a final answer:

```
TOOL: lookup_card {"name": "Ash Blossom & Joyous Spring"}
```

```
FINAL: <answer text> ||CITES: card:<id>, ruling:<id>, chunk:<id>||
```

The tool-call line is `TOOL: <tool_name> <json_object>` — the parser
splits on the first space after the tool name and `json.loads`s the
remainder as the tool's arguments. This avoids writing a general
Python-call-syntax parser: the only structure the orchestrator needs
to recognize is the `TOOL:`/`FINAL:` prefix and where the JSON begins.

The `FINAL:` line must end with a `||CITES: ...||` trailer listing
every source id (card/ruling/rulebook-chunk) the answer relies on —
`||CITES: ||` (empty) if none apply. This trailer is what makes
citation coverage checkable in code rather than trusted as prose (see
"Confidence & escalation" below).

Malformed input (a `TOOL:` line with invalid JSON, or an unrecognized
tool name) is treated as a protocol error: the orchestrator does not
guess intent, it reports failure back to the LLM as a synthetic tool
result (`{"error": "..."}"`) and lets it retry, capped at 3 consecutive
malformed turns before surfacing "not supported yet."

## The four tools

All four live in `orchestration/tools.py` as thin wrappers with a
uniform shape: take a `dict` of JSON-decoded arguments, return a
JSON-serializable `dict`, and record what they returned into the
loop's running signal state (used ids, gap flags) as a side effect of
being called through the loop — not something the wrapper itself
tracks.

- **`lookup_card(name)`** → card fields from `cards_repo.get_card_by_name`
  plus `card_text` (always present, always ground truth) and, if
  `effects_repo.get_confirmed_effect` returns one, the confirmed
  structured breakdown. If no card matches: `{"found": false}`. If a
  card matches but has no confirmed structured effect, the result
  still includes `card_text` — the LLM reasons from raw text — and the
  wrapper marks `missing_structured_effect` for that card in the
  loop's signal state. A `pending`-status effect is never surfaced
  as fact, per the existing repo-level guarantee.
- **`get_rulings(card_id)`** → `rulings_repo.get_rulings_for_card`. Empty
  list marks `retrieval_gap`.
- **`search_rulebook(query)`** → embeds `query` via the injected
  `EmbeddingClient`, calls the new `rulebook_repo.search_chunks`.
  Empty list (nothing clears the distance threshold) marks
  `retrieval_gap` — this is the deterministic backstop against a
  vector search returning a merely-closest-not-actually-relevant
  chunk for an out-of-domain or unanswerable question.
- **`resolve_chain(scenario)`** → the new `rules_engine.resolve.resolve_chain`
  (below). An `UnsupportedScenarioError` from this call is not caught
  here — it propagates to the loop, which maps it directly to the
  "not supported yet" outcome, skipping confidence scoring entirely.

## `resolve_chain` composition

New module `rules_engine/resolve.py`, pure Python, same zero-dependency
boundary as the rest of `rules_engine/`.

Input — a scenario the LLM builds from the natural-language game state
it was given (this parsing-into-structure step is the LLM's job, not
code's, per the thin-slice spec):

```json
{
  "turn_player": "playerA",
  "steps": [
    {
      "kind": "segoc_batch",
      "effects": [
        {"card_name": "...", "controller": "playerA", "effect_type": "trigger", "spell_speed": 1, "prevents_response": false}
      ]
    },
    {
      "kind": "activate",
      "effect": {"card_name": "...", "controller": "playerB", "effect_type": "quick", "spell_speed": 2, "prevents_response": false}
    }
  ]
}
```

`effect_type` values are exactly `EffectType`'s existing string values
(`"trigger"`, `"quick"`, etc.) — the LLM emits the same vocabulary the
DB and rules engine already use, no translation layer.

The engine walks `steps` in order:
- `segoc_batch` → build `Effect` objects, call `apply_segoc(chain,
  turn_player=..., triggered_effects=...)`.
- `activate` → build one `Effect`, call `can_activate_now(effect.spell_speed,
  chain)`; if legal, `chain.add_link(effect)`; if not, stop processing
  further steps and record the violation — the scenario as described
  is illegal from that point on, so nothing after it is meaningful.

A `kind` this loop doesn't recognize raises `UnsupportedScenarioError`
immediately — this is the "rules engine hit a case it doesn't
implement yet" branch from the thin-slice spec's gating logic.

Output:

```json
{
  "resolution_order": [
    {"link_number": 2, "card_name": "...", "controller": "playerB"},
    {"link_number": 1, "card_name": "...", "controller": "playerA"}
  ],
  "violation": null
}
```

A priority violation (an illegal `activate` step) is a **legitimate
answer**, not an error — "no, that card can't respond here" is exactly
the kind of question this tool exists to answer. `violation` carries
`{"step_index": ..., "reason": "priority_violation", "detail": "..."}`
in that case. Only an unrecognized scenario shape is an error
condition (`UnsupportedScenarioError`).

Missing-timing checks (`timing.py`'s `check_missing_timing`) are
deliberately **not** wired into this composition for this slice — the
thin-slice spec's Quick-Effect-only missing-timing scope is narrow
enough, and the specific moment "current step" needs to be pinned by
the scenario, that folding it into the general chain-walk risks
under-specifying a currently-untested interaction. It stays a
directly-callable primitive; a future revision can add a `timing_check`
step `kind` once there's a concrete scenario shape to test against.

## Vector search

New function in `db/rulebook_repo.py`:

```python
def search_chunks(query_embedding: list[float], *, max_distance: float, limit: int = 5) -> list[dict]
```

Uses pgvector's `<=>` cosine-distance operator, `ORDER BY embedding
<=> %s LIMIT %s`, filtered by `WHERE embedding <=> %s < %s` (so a
query with no genuinely close chunk returns `[]` rather than the
nearest-available-anyway result). `max_distance` is a required keyword
argument, not defaulted silently, so callers make an explicit choice;
`orchestration/tools.py` supplies the project's tuned default.

This function is DB-dependent and follows the existing
`tests/db/*`-style skip-without-`DATABASE_URL` pattern.

## Confidence & escalation (deterministic)

New module `orchestration/confidence.py`. The loop (below) accumulates
signal state as it runs:

- `known_ids: set[str]` — every source id actually returned by any
  tool call this session (`card:<id>`, `ruling:<id>`, `chunk:<id>`).
- `missing_structured_effect: bool` — set if any `lookup_card` result
  had no confirmed structured effect.
- `retrieval_gap: bool` — set if any `get_rulings` or `search_rulebook`
  call returned empty.

At `FINAL:`, `compute_confidence(cited_ids, known_ids, *,
missing_structured_effect, retrieval_gap) -> float`:

- Any id in `cited_ids` not present in `known_ids` → confidence `0.0`
  outright (a citation for something never actually looked up this
  session is worse than a low-confidence answer — it's a fabricated
  source, and must never pass).
- Otherwise start at `1.0`, subtract a fixed penalty for
  `retrieval_gap` and for `missing_structured_effect` (penalty weights
  are tunable constants, defaulted conservatively; exact values are
  tuned the same way `review_agent.py`'s `DEFAULT_CONFIDENCE_THRESHOLD`
  is — starting point now, refined against real cases later).
- Clamp to `[0.0, 1.0]`.

Compared against a module-level `DEFAULT_CONFIDENCE_THRESHOLD`
constant, same naming convention as `effect_parser/review_agent.py`.

Gating order in the loop, matching the thin-slice spec exactly:
1. `UnsupportedScenarioError` propagated from `resolve_chain` →
   **"not supported yet, contact dev team"** (checked first, not a
   confidence problem).
2. `compute_confidence(...) < DEFAULT_CONFIDENCE_THRESHOLD` →
   **"escalate to a human judge."**
3. Otherwise → the cited answer, verbatim minus the `||CITES: ...||`
   trailer (which is protocol plumbing, not user-facing).

## Clarification phase (upfront, not a loop tool)

New module `orchestration/clarify.py`. Before the main tool-use loop
starts, one LLM call: given the raw user question, the LLM responds
with zero or more of:

```
CLARIFY: <question to ask the user>
CONTINUOUS_CHECK: <card name>
```

or a bare `PROCEED` if neither applies. The orchestrator surfaces each
line to the user via the CLI (`CLARIFY` as a free-text question,
`CONTINUOUS_CHECK` as "is `<card name>`'s effect currently active?"),
collects the answers, and folds them into the main loop's opening
prompt as additional context before the tool-use loop begins.

This is intentionally **not** one of the four callable tools — the
thin-slice spec is explicit that this gathering happens upfront,
"rather than interrupting the reasoning loop mid-flight." Continuous/
lingering-effect board state is never persisted (per the thin-slice
spec) — it's asked fresh every session.

## The loop

New module `orchestration/loop.py`. Ties the above together:

1. Run the clarification phase; fold results into the opening prompt.
2. Loop: build the running prompt (system instructions + tool
   descriptions + conversation-so-far), call `llm.complete(prompt)`,
   parse the response via `protocol.py`.
   - `ToolCall` → dispatch to `tools.py`, update signal state, append
     the tool result to the conversation, continue the loop.
   - `FinalAnswer` → break out and run the gating sequence above.
   - Parse error → append a synthetic error tool result, retry (capped).
3. Return one of: cited answer, escalation message, or "not supported"
   message — the CLI is responsible only for display, all decision
   logic lives here.

## CLI

`cli.py`, top-level module (not a package — no need for one yet). A
plain stdlib `input()`/`print()` REPL, no framework dependency (there
is currently no CLI library in `pyproject.toml`'s dependencies, and
none is needed for this slice):

```
> <question>
[clarification questions printed, answers read via input()]
[loop runs]
<cited answer> | <escalation message> | <not-supported message>
> <next question>
```

`exit`, `quit`, or EOF (Ctrl-D / Ctrl-Z) ends the session.

## Testing

TDD throughout, per the project's established development process —
a failing test precedes implementation for every module below.

- **`rules_engine/resolve.py`** — pure unit tests, no DB/LLM: legal
  multi-step chains resolve in the expected LIFO order, an illegal
  `activate` step produces the expected `violation` and halts
  processing, an unrecognized `kind` raises `UnsupportedScenarioError`.
- **`db/rulebook_repo.search_chunks`** — DB-dependent
  (skip-without-`DATABASE_URL`, matching existing `tests/db/*`
  convention), using `MockEmbeddingClient`'s deterministic vectors to
  verify both a within-threshold match and an over-threshold query
  returning `[]`.
- **`orchestration/protocol.py`** — pure parser tests: well-formed
  `TOOL:`/`FINAL:` lines, malformed JSON, unrecognized tool name,
  missing `||CITES: ...||` trailer.
- **`orchestration/confidence.py`** — pure tests over signal
  combinations, including the fabricated-citation hard-fail case and
  each individual penalty in isolation.
- **`orchestration/clarify.py`** — pure tests over parsed
  `CLARIFY`/`CONTINUOUS_CHECK`/`PROCEED` lines.
- **`orchestration/loop.py`** — tests driven by `MockLLMClient` queued
  responses with fake tool implementations (no DB needed): a
  multi-step tool-call sequence reaching `FINAL`, and one test per
  gating outcome (not-supported, escalate, cited answer).
- **`cli.py`** — thin wiring; covered by a small monkeypatched-stdin
  smoke test rather than exhaustive coverage, since the decision logic
  it depends on is already fully tested at the `loop.py` level.

## Deferred out of this design

- Real Claude API wiring (`LLMClient` stays mock-only; this is a
  separate follow-up once this design's mock-driven loop is proven).
- A structured tool-calling wire format (would replace `protocol.py`'s
  text convention if/when a real provider's native tool-use is wired
  in).
- Missing-timing checks folded into `resolve_chain` (stays a
  standalone primitive for now, per "resolve_chain composition" above).
- Confidence penalty weight tuning against real cases (starting values
  only; same deferred-tuning treatment as the effect-parser review
  threshold).
