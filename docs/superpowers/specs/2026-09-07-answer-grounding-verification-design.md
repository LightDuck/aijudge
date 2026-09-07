# Answer Grounding Verification — Design

**Date:** 2026-09-07
**Status:** proposed

## Problem

`run_loop`'s `FinalAnswer.text` (`src/aijudge/orchestration/loop.py`) is entirely LLM-authored prose. Citations
are grounded — `compute_confidence()` (`src/aijudge/orchestration/confidence.py`) zeroes the score outright if
`FinalAnswer.cited_ids` contains an id no tool result actually surfaced — but nothing checks that the *prose
describing what a citation says* is faithful to the citation's actual content.

Observed failure: asked about Tearlaments Sulliek, the LLM (Qwen3-8B via `OllamaLLMClient`, this project's
default $0 wiring) generated "negates the effects of the target spell or trap card" for an effect whose stored,
verbatim text reads "target 1 Effect Monster your opponent controls; negate its effects". The cited card id was
real and the citation text (returned to the caller) was accurate — only the free-text summary was wrong. Because
`compute_confidence` has no signal for this, the answer scored a perfect 1.0 and was returned as a normal,
non-escalated answer.

This is the failure mode the project exists to avoid (CLAUDE.md: "the LLM orchestrates and explains; the rules
engine and database decide... a wrong-but-confident result is the exact failure mode this project exists to
avoid"). It's specifically dangerous for cards with structured, ground-truth effect data already sitting in
`card_effects_structured` — the correct text was available and simply wasn't used faithfully.

## Scope

This design covers only cards with confirmed structured effects (`card_effects_structured` rows surfaced via
`lookup_card` or preflight's `grounded_cards`) — i.e., exactly the case above, where a deterministic ground truth
exists to check against. Citations from `get_rulings`/`search_rulebook` (rulings, rulebook chunks) have no
structured equivalent to verify against and are out of scope; those stay LLM-paraphrased and ungrounded, as
today. Cards with no confirmed effects are already covered by the existing `missing_structured_effect` confidence
penalty and are unaffected by this design.

## Mechanism

The LLM keeps authoring the final answer's prose — it still frames the answer, decides which of a card's effects
is relevant to the question, and handles the question's specific angle. What changes is that after a
`FinalAnswer` passes the existing confidence gate, a new **structured-grounding verification gate** checks,
deterministically-triggered but LLM-executed, whether the answer's description of any cited structured effect
actually matches that effect's stored text. A mismatch is treated as a correctable failure: the loop feeds the
mismatch back to the LLM (mirroring the existing `MAX_MALFORMED_RETRIES` retry-with-feedback pattern) and gives
it a bounded number of chances to redraft before escalating to a human judge.

This mirrors the project's existing citation-id verification (`compute_confidence`'s `cited_ids - known_ids`
check) — just applied to content instead of ids — rather than replacing LLM prose with a rigid template, which
would lose the model's ability to tailor phrasing to what was actually asked (e.g. "can I activate this during
the Damage Step" needs a direct yes/no framing a fixed template can't anticipate for every question shape).

The verification check itself is a second, cheap LLM call: given the cited card's stored effect text (verbatim,
from `card_effects_structured.effect`) and the drafted answer, ask a strict yes/no question — does the answer
accurately restate this effect (same targets, same actions, nothing invented or swapped)? This is the only
approach general enough to catch paraphrase drift not anticipated by a fixed keyword list (e.g. "Effect Monster"
→ "spell or trap card" is a semantic swap, not a missing keyword) — a deterministic keyword/category check was
considered and rejected as too narrow for a first version, though it remains a cheaper fallback worth revisiting
if verifier-call cost/latency becomes a problem in practice.

## Components

### 1. `SignalState.structured_effects` (extend `confidence.py`)

```python
@dataclass
class SignalState:
    ...
    structured_effects: dict[str, list[dict]] = field(default_factory=dict)
```

Populated in `update_signals()`'s existing `lookup_card` branch, alongside `known_ids`/`citation_index`:

```python
if result.get("confirmed_effects"):
    state.structured_effects[card_id] = result["confirmed_effects"]
    if ygoprodeck_id:
        state.structured_effects[passcode_id] = result["confirmed_effects"]
```

Keyed under both the internal id and passcode alias exactly like `citation_index` is today, so a citation by
either id resolves to the same structured effects. Cards with empty/absent `confirmed_effects` are not added
(already flagged via `missing_structured_effect`), which is what lets the new gate skip entirely when there's
nothing to verify.

### 2. New module `src/aijudge/orchestration/verify.py`

```python
@dataclass
class VerificationResult:
    ok: bool
    mismatches: list[dict]  # [{"card_id": ..., "effect_text": ...}, ...] for feedback-message construction


def build_verification_prompt(answer_text: str, structured_effects: list[dict]) -> str: ...

def parse_verification_response(response: str) -> bool: ...

def verify_structured_grounding(
    answer_text: str,
    cited_ids: set[str],
    state: SignalState,
    llm_client: LLMClient,
) -> VerificationResult: ...
```

- `build_verification_prompt` is deterministic: lists every cited card's stored effect text verbatim (deduped
  across id/passcode aliases so a card cited by both isn't listed twice), then the drafted answer, then a strict
  yes/no instruction. Uses its own minimal system framing (a strict fact-checker role) — **not**
  `protocol.build_system_prompt()` — so it doesn't inherit the rules-adjudicator persona or tool-use protocol
  instructions, which are irrelevant and could confuse this narrower task.
- `parse_verification_response` is strict and fail-closed: only an exact (case-insensitive, whitespace-trimmed)
  `"YES"` returns `True`. Anything else — `"NO"`, empty, garbage, an explanation instead of a bare answer —
  returns `False`. Mirrors `review_agent.py`'s bare-confidence-value parsing style; consistent with the project's
  "don't guess" posture (an ambiguous verifier response is not evidence of correctness).
- `verify_structured_grounding` collects `state.structured_effects` for every id in `cited_ids` that has an
  entry. If none do (the common case — most cited cards have no structured effects, or this citation is a
  ruling/rulebook chunk), it returns `VerificationResult(ok=True, mismatches=[])` **without calling the LLM** —
  zero added cost/latency on the unaffected path. Otherwise it makes exactly one LLM call bundling all matched
  cards' effects together, and returns `ok=False` with the relevant `mismatches` entries if the parsed response
  is `False`.

### 3. `loop.py` changes

- New constant `MAX_VERIFICATION_RETRIES = 2` — a small, separate budget from `MAX_MALFORMED_RETRIES`. These are
  different failure classes (protocol/tool-argument errors vs. content correctness); sharing one counter would
  let a model that stumbles on one drain the budget for the other.
- New local counter `verification_retry_count = 0` in `run_loop`.
- After the existing `if score < threshold: return LoopResult(kind="escalate", ...)` check passes (i.e., the
  answer already cleared the id-fabrication/retrieval-gap/missing-structured-effect gate), call
  `verify_structured_grounding(parsed.text, parsed.cited_ids, state, llm_client)`:
  - `ok=True` → return the answer exactly as today (`LoopResult(kind="answer", ...)`).
  - `ok=False` → `verification_retry_count += 1`; if it exceeds `MAX_VERIFICATION_RETRIES`, return
    `LoopResult(kind="escalate", text=ESCALATE_MESSAGE)`; otherwise append a feedback message to `conversation`
    naming the mismatched card(s) and their actual stored effect text (e.g. `"\n\nVERIFICATION_FAILED: your
    answer's description of <card> doesn't match its stored effect text: \"<effect_text>\". Revise your FINAL
    answer to accurately reflect it."`) and `continue` the loop so the LLM redrafts `FINAL:`.

## Data flow

```
FinalAnswer parsed
  → compute_confidence gate (existing: id-fabrication, retrieval-gap, missing-structured-effect)
      → fail → escalate (unchanged)
      → pass → any cited id present in state.structured_effects?
          → no  → return answer (unchanged path, zero extra LLM calls)
          → yes → one verify_structured_grounding LLM call
              → YES → return answer
              → NO  → feedback appended to conversation, loop retries LLM turn
                    → within MAX_VERIFICATION_RETRIES → LLM redrafts FINAL, re-enters this gate
                    → budget exhausted → escalate
```

## Error handling

- A verifier response that isn't a clean `YES`/`NO` is treated as a verification **failure** (see
  `parse_verification_response` above), not a `ProtocolError`-style malformed-response retry — it doesn't corrupt
  the outer `TOOL:`/`FINAL:` protocol the main loop parses; it's simply an untrusted verification outcome that
  gets the same treatment as an explicit `"NO"`.
- A raw exception from the verifier's `llm_client.complete()` call (network/timeout/etc.) is **not** specially
  caught by this design — consistent with how the primary `complete()` call already isn't specially handled
  elsewhere in `run_loop` (a transport failure there already propagates uncaught today). No new try/except is
  introduced.
- `UnsupportedScenarioError` and tool-argument errors are unaffected — this gate only runs after a `FinalAnswer`
  has already been parsed and has already cleared `compute_confidence`, so it sits entirely downstream of the
  existing tool-call and malformed-response handling.

## Testing

- New `tests/orchestration/test_verify.py`:
  - `build_verification_prompt` — includes stored effect text and the answer text verbatim.
  - `parse_verification_response` — exact `"YES"` (and case/whitespace variants) → `True`; `"NO"`, empty string,
    and non-YES/NO garbage → `False`.
  - `verify_structured_grounding` — skip-when-nothing-to-check path asserts **zero** LLM calls (e.g. via
    `MockLLMClient` with an empty response queue not raising `AssertionError`); a matched-and-verified path; a
    matched-and-mismatched path, asserting `mismatches` content.

- `tests/orchestration/test_loop.py` — **migration cost, not just new coverage**: every existing test that
  supplies non-empty `confirmed_effects` in a `lookup_card` tool result or in `grounded_cards` now triggers the
  new verifier call and needs one additional queued `MockLLMClient` response (`"YES"`) or it will fail with
  `MockLLMClient`'s empty-queue `AssertionError`. A repo-wide check found at least these existing tests affected:
  `test_tool_call_then_final_answer_cites_the_returned_id`, `test_malformed_tool_arguments_are_recoverable`,
  `test_tool_call_then_final_answer_includes_citation_text`, `test_multiple_citations_are_sorted_by_id`,
  `test_grounded_cards_preseed_known_ids_so_direct_final_answer_is_not_fabricated`,
  `test_run_loop_passes_the_system_prompt_on_every_llm_call`, and any other test using
  `"confirmed_effects": [{"effect": "..."}]` in a `lookup_card`-shaped result. Tests using `"confirmed_effects":
  []` (e.g. `test_tool_call_loop_gives_up_after_max_tool_calls`,
  `test_malformed_tool_arguments_exhausted_surfaces_not_supported`) are unaffected — no structured effects means
  no verifier call.
  - New tests: verifier returns `NO` once then `YES` on retry → answer is still returned, and the fed-back
    feedback message names the mismatched card/text; verifier returns `NO` through the full
    `MAX_VERIFICATION_RETRIES` budget → `LoopResult(kind="escalate", ...)`.

## Out of scope / deferred

- Verifying `get_rulings`/`search_rulebook` citation content (no structured ground truth exists to check
  against — a future design could add a weaker text-overlap heuristic for these, but that's a separate,
  lower-confidence mechanism and not part of this change).
- A deterministic keyword/category check as a cheaper alternative or pre-filter to the LLM verifier call — noted
  above as a possible future optimization if verifier-call cost/latency becomes a problem, not built now (YAGNI).
- A feature flag to disable the verification gate — not needed; it's cheap (skips entirely when there's nothing
  structured to check) and always-on keeps the design simple.

## Amendments

**2026-09-07, post-implementation review:** Component 2 as originally specified rendered only
`card_effects_structured.effect` (the post-`;` resolution clause) into the verification prompt. This proved unable
to catch the spec's own motivating example: `parse_psct` splits card text into separate
`activation_condition`/`cost`/`targeting`/`effect` fields, and for "Target 1 Effect Monster your opponent controls;
negate its effects.", the word "Effect Monster" lives in `targeting`, not `effect` — a verifier that only ever sees
`effect` has nothing to contradict an "Effect Monster" → "spell or trap card" swap in the drafted answer, i.e. it
cannot catch the exact failure this design exists to catch. `build_verification_prompt`/`verify_structured_grounding`
now render each matched effect's full stored breakdown (activation_condition/cost/targeting/effect, omitting any
field that's `None`, mirroring `preflight.build_known_facts_context`'s conditional-append style) instead of just
`effect`.
