# Card-Effect Grounding Pipeline — Design

**Date:** 2026-09-08
**Status:** proposed

## Problem

`run_loop` (`src/aijudge/orchestration/loop.py`) lets the LLM decide, turn by turn, whether to call `lookup_card`
before answering. Nothing structurally requires it to. Two real failure modes were observed tracing this:

1. **Bundled fabrication (Tearlaments Metanoise):** the LLM's first turn emitted both a `TOOL: lookup_card` call
   and a fabricated `FINAL:` answer (wrong passcode, invented "Xyz Material" mechanics) in the same response.
   This happened to get rejected — `protocol.parse_response()` only accepts one directive per turn — but that's
   an accident of the generic parser, not a rule that exists to catch fabrication.
2. **The open gap (same shape as the original Tearlaments Sulliek bug):** nothing stops the LLM from responding
   with a lone `FINAL:` and zero prior tool calls in the whole conversation. If it cites nothing,
   `compute_confidence()` scores it `1.0` — `cited_ids - known_ids` is `{} - {} = {}` (falsy), and
   `retrieval_gap`/`missing_structured_effect` are only ever set by a tool call that already happened. An
   ungrounded, memory-authored answer with no citations passes both the confidence gate and
   `verify_structured_grounding()` (which trivially returns `ok=True` with zero LLM calls when `cited_ids` is
   empty) and reaches the user as a normal, non-escalated answer.

Card lookup being *optional* for the LLM is the root cause of both. This design makes it *mandatory* and
*deterministic* for the one question shape the project needs to be stable at: asking about the effect(s) of one
or more named cards, including timing-specific questions about a card's own activation properties.

## Scope

**In scope:** questions that name one or more Yu-Gi-Oh! cards (complete or partial name) and ask about their
effect(s) — including precision/timing questions answerable from a card's own stored activation
condition/spell-speed/damage-step data (e.g. "can I activate this during the Damage Step").

**Explicitly suspended, not deleted:** general rules/mechanics questions with no named card, official ruling
lookups (`get_rulings`/`ygoresources`, already separately known-broken per prior investigation), rulebook search
(`search_rulebook`), and arbitrary multi-effect chain/scenario resolution (`resolve_chain`). These tools stay in
the codebase but are not wired into this pathway's tool dispatch. Re-enabling them is future work, out of scope
here.

**Explicitly deferred (not designed now):** recovery when the extraction step misses a card the question actually
named — treated as an extraction bug to fix later, not a case the LLM self-corrects via a fallback tool call.
Listing candidate names for an `ambiguous` online-API match is also deferred (see Component 3) — an ambiguous
name is reported to the user without a candidate list for now.

## Architecture

```
User question
     │
     ▼
find_matched_cards(question)        existing, unchanged: local-only, free, fuzzy/substring
     │                               match against card names already in the DB
     ├─ ≥1 local match ─────────────────────────────┐
     │                                                │
     └─ 0 local matches                               │
           │                                          │
           ▼                                          │
     [NEW] extract_card_names(question)               │
     — one narrow LLM call: "list every card          │
       name this question references"                 │
           │                                          │
           ├─ 0 names extracted ──► return              │
           │                        LoopResult(         │
           │                        kind="not_supported"│
           │                        ) directly — no     │
           │                        run_loop call at    │
           │                        all for this branch │
           │                                          │
           └─ ≥1 name(s) extracted ────────────────────┤
                                                        │
                                                        ▼
                                    [NEW] resolve_named_cards(names)
                                    for each name (local match OR
                                    extracted): call tools.lookup_card()
                                    directly as a Python function call —
                                    NOT as an LLM-issued TOOL: directive.
                                    Each name resolves to one of:
                                      resolved / not_found / ambiguous
                                                        │
                                                        ▼
                                    [NEW] build_pipeline_context(results)
                                    — KNOWN FACTS block per resolved card
                                    + a FAILURES block per unresolved name
                                                        │
                                                        ▼
                                    run_loop(question, tools={},
                                        system_prompt=build_answering_system_prompt(),
                                        clarification_context=pipeline_context)
                                    LLM's only job: compose FINAL from what
                                    it was already given, or REFUSE if
                                    genuinely off-topic (not Yu-Gi-Oh at all)
```

## Components

### 1. `orchestration/extraction.py` (new module)

Mirrors the existing narrow-role pattern in `verify.py` (`VERIFIER_SYSTEM_PROMPT`) rather than reusing
`protocol.build_system_prompt()`, which would pull in unrelated tool-use/persona instructions.

```python
EXTRACTION_SYSTEM_PROMPT = (
    "You extract Yu-Gi-Oh! TCG card names from a user's question. List every "
    "card name the question references, complete or partial, one per line. "
    "If the question does not reference any card by name, respond with "
    "exactly NONE."
)

def build_extraction_prompt(question: str) -> str: ...
def parse_extraction_response(response: str) -> list[str]: ...
```

`parse_extraction_response` returns `[]` for a bare `NONE` (tolerant of the same Qwen3-8B formatting sloppiness
`verify.parse_verification_response` already handles — trims markdown/whitespace noise). Triggered only when
`find_matched_cards()` returns zero local matches (Approach A from the design discussion — local matching is
free and already reliable for cards already in the DB; the extraction call exists specifically to catch names
the DB has never seen).

### 2. `orchestration/card_resolution.py` (new module)

```python
@dataclass
class CardResolution:
    name: str                    # the name as extracted/matched
    status: str                  # "resolved" | "not_found" | "ambiguous"
    card: dict | None = None     # lookup_card()'s full result, when status == "resolved"

def resolve_named_cards(
    names: list[str],
    *,
    llm_client: LLMClient,
    online_ingest_enabled: bool = True,
) -> list[CardResolution]: ...
```

For each name, calls `tools.lookup_card({"name": name}, ...)` directly — the exact same function the LLM's
`TOOL: lookup_card` directive dispatches to today, just invoked from pipeline code instead of through the
LLM-issued protocol. Status mapping from `lookup_card`'s existing return shape:
- `{"found": True, ...}` → `resolved`
- `{"found": False, "ambiguous": True}` → `ambiguous`
- `{"found": False}` → `not_found`

Note there is no separate `error` status: `lookup_card` as it exists today already catches every unexpected
exception during online ingest (`except Exception: return {"found": False}`, `tools.py`) and collapses it into
the same shape as a genuine not-found — there is no way to distinguish "doesn't exist / misspelled" from "a
technical failure happened" without changing that existing swallowing behavior, which is out of scope for this
design. Both are reported to the user as `not_found`.

No candidate list is threaded through for `ambiguous` (see Scope) — `lookup_card` itself doesn't return one
today; enriching it is future work if this turns out to matter in practice.

### 3. `orchestration/preflight.py` (extend)

New `build_pipeline_context(local_matches, extracted_resolutions) -> str`: concatenates
`build_known_facts_context(card)` (existing, unchanged) for every resolved card — local matches and newly-
resolved extracted names alike — followed by a `LOOKUP FAILURES` block listing `(name, status)` for every
unresolved name, e.g.:

```
LOOKUP FAILURES (deterministic -- report these to the user, do not guess their effects):
- "Tearlaments Scrimm": not_found
- "Visas Starfrst": not_found
```

### 4. `orchestration/protocol.py` (extend)

New `build_answering_system_prompt() -> str`, used only by this pathway in place of `build_system_prompt()`.
States plainly: no tools are available in this turn; all card information the model needs has already been
provided below; for any card listed under LOOKUP FAILURES, tell the user it wasn't found (suggesting a spelling
check is reasonable) and do **not** describe what that card might do from memory; respond with `FINAL:` or
`REFUSE:` only (never `TOOL:`).

`run_loop` is called with `tools={}` for this pathway — reusing its existing malformed-response retry path
unchanged. If the LLM ever tries `TOOL:` anyway, `tools[name]` raises `KeyError`, which `loop.py` already treats
as a malformed-response retry, degrading to `not_supported` after `MAX_MALFORMED_RETRIES` — no new code needed
in `loop.py` for this case.

This does require one small signature change `run_loop` doesn't have today: it currently hardcodes
`system_prompt = build_system_prompt()` internally with no way to override it. `run_loop` needs a new optional
`system_prompt: str | None = None` parameter — `None` keeps today's default (`build_system_prompt()`) for every
existing caller, while this pathway passes `build_answering_system_prompt()` explicitly.

### 5. `orchestration/confidence.py` (extend)

```python
def compute_confidence(cited_ids: set[str], state: SignalState) -> float:
    if cited_ids - state.known_ids:
        return 0.0
    if state.known_ids and not cited_ids:      # NEW
        return 0.0
    ...
```

Closes the structural gap described in Problem #2: once at least one card has actually resolved, an answer
describing anything about a card while citing none of them can no longer score above `0.0` — regardless of
whether the prose happens to be accurate. This does not penalize the legitimate "none of these cards were found"
case (Component 6), where `known_ids` is correctly empty because nothing ever resolved.

Getting resolved cards into `state.known_ids` before the LLM's first turn requires no new plumbing: `run_loop`
already accepts a `grounded_cards: list[dict] | None` parameter (used today by `cli.py` for its single-match
preflight case) that pre-registers each card via `update_signals(state, "lookup_card", card)` before the loop
starts. This pathway just passes every resolved card from Component 2's results as `grounded_cards`, instead of
at most one.

Existing tests that assert an empty-citation answer scores nonzero confidence while `known_ids` is populated
will need updating as part of implementation — this is a deliberate behavior change, not a regression to avoid.

This is a change to a shared module used by every caller of `compute_confidence`, not something scoped only to
this pathway. Since every other pathway is currently suspended, this has no live effect elsewhere today, but
should be re-examined if/when a suspended pathway (e.g. rulebook search, where citing nothing might be
legitimate mid-conversation) is re-enabled.

### 6. Multi-card and partial-failure handling

No new orchestration logic needed beyond what's already described: `build_pipeline_context` folds every
resolution (success or failure) into one context block ahead of the question, and the answering-turn system
prompt instructs the LLM to answer normally for resolved cards and report failures plainly for unresolved ones
in the same response. If **every** extracted/matched name fails to resolve, `known_ids` stays empty, the
hardened confidence rule from Component 5 doesn't fire (nothing to have cited), and an honest "none of these
were found" answer passes normally with empty citations — this is not routed through `kind="escalate"`, since
there's no genuine rules ambiguity for a human judge to adjudicate, only an identification miss.

### 7. Entry points (`cli.py`, `api/app.py`)

Both currently call `find_matched_cards` then either inject `KNOWN FACTS` (1 match) or add a
`disambiguate_card` clarification item (>1 match) or do nothing (0 matches, today's gap). This design replaces
the "0 matches" branch: it calls `extract_card_names`, and then either returns `LoopResult(kind="not_supported")`
directly with no `run_loop` call (0 names extracted — see Architecture diagram) or calls `resolve_named_cards` →
`build_pipeline_context` → `run_loop` with `tools={}` and `build_answering_system_prompt()` (≥1 names extracted).
The existing `disambiguate_card` clarification flow for *local* ambiguous matches (>1 local match) is unchanged.

## Testing Approach

TDD throughout, per project convention. New test modules mirroring existing style
(`tests/orchestration/test_verify.py`'s `_CapturingLLMClient` pattern reused where a full-path assertion is
needed):

- `test_extraction.py`: prompt construction, response parsing (including `NONE` and Qwen-style formatting
  sloppiness), 0-name and multi-name cases.
- `test_card_resolution.py`: each `lookup_card` return shape maps to the correct `CardResolution.status`;
  multi-name lists resolve independently (one failure doesn't block another's success).
- `test_preflight.py` (extend): `build_pipeline_context` renders resolved cards' KNOWN FACTS and unresolved
  names' failure statuses correctly, and omits the failures block entirely when there are none.
- `test_protocol.py` (extend): `build_answering_system_prompt` forbids `TOOL:`, instructs against fabricating
  unresolved cards.
- `test_confidence.py` (extend): the new rule — `known_ids` non-empty + `cited_ids` empty → `0.0`; `known_ids`
  empty + `cited_ids` empty → unaffected (existing passing behavior preserved); existing
  `cited_ids - known_ids` non-empty case unaffected.
- `test_loop.py` / new end-to-end pipeline test: `MockLLMClient`-driven scenarios covering (a) single resolved
  card, cited, verified, answered; (b) two cards, one resolves and one doesn't, partial answer; (c) all
  extracted names fail, honest "not found" answer with empty citations, `kind="answer"` not `"escalate"`;
  (d) zero cards extracted, `kind="off_topic"`/`"not_supported"`; (e) LLM attempts `TOOL:` anyway despite empty
  dispatch, degrades to `not_supported` after retries via existing `KeyError` path.

## Open Questions / Explicitly Deferred

- Extraction-miss recovery (LLM notices mid-answer that data is missing and wants to self-correct) — deferred
  per explicit direction; the current design has no fallback path for this.
- Enriching `lookup_card`'s `ambiguous` response with a candidate name list, so `ambiguous` failures could name
  the specific cards a partial name might mean — deferred; today it's reported as a bare "ambiguous" status.
- Re-enabling `resolve_chain`/`search_rulebook`/`get_rulings` and general (no-card) rules questions — future
  work, not designed here.
