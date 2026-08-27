# AIJudge — Deterministic Activation Recognition Design

## Purpose

CLAUDE.md states the project's guiding principle: "the LLM orchestrates and
explains; the rules engine and database decide. Anywhere LLM reasoning can be
replaced with a deterministic lookup or algorithm, it is." Today that
principle is not fully honored around one specific question: recognizing
that a user's question describes an *activation*, and judging whether that
activation is legal.

The rules engine already has real deterministic meta-rules —
`spell_speed_for`, `can_activate_now`, `apply_segoc`,
`check_missing_timing`, `Chain.resolution_order` — and the effect parser
already deterministically classifies effect type and splits PSCT text at
ingestion time (`classify_effect_type`, `parse_psct`). But none of this runs
before the LLM starts reasoning about a question, and none of it validates
the LLM's own claims when it builds a `resolve_chain` tool call. The LLM
currently infers a card's effect type, spell speed, and whether an
activation is even legal entirely from its own judgment — even though the
DB already holds reviewed, confirmed ground truth for exactly these facts
via `effects_repo.get_confirmed_effect`.

Classified as **architectural** (brainstorming skill): this touches the
parser, two repo layers, orchestration, and the rules engine, and
introduces a new pre-reasoning stage — no single existing flow covers it.

## Goals

- Ground the LLM's reasoning in deterministic, already-confirmed data
  *before* it starts reasoning about a question, not just validate its
  claims after the fact.
- Let a user's question identify a card even when it's misspelled,
  abbreviated, or the DB has no exact match — with the user disambiguating
  when the match is ambiguous, never the system guessing silently.
- Separate two genuinely different legality questions that were previously
  conflated: *can this effect ever be activated* (a structural, effect-type
  property) versus *can it be activated right now, given what the card's
  own text requires* (a condition-satisfaction property).
- Encode Damage Step legality — the game's most restrictive timing
  window — as a deterministic rule, sourced from the current official
  rulebook, not LLM guesswork.
- Give the project's `search_rulebook` RAG fallback real data to retrieve
  from, since today `rulebook_chunks` is empty despite the ingestion
  pipeline existing.
- Keep the rules engine from growing without bound as card coverage scales
  past the current 5 hand-picked cards, by drawing a hard line between
  fixed-size global game law (safe to hardcode) and per-card data (must be
  extracted at ingestion time into reviewed, structured DB fields, never
  parsed at answer-time).

## Non-goals

- Full natural-language parsing of arbitrary questions to detect "this
  describes an activation" — that stays an LLM judgment call. This design
  only grounds the LLM's reasoning about a card/effect *once identified*;
  it does not replace the LLM's read of the user's question.
- Enforcing once-per-turn / usage-count restrictions during reasoning. The
  project tracks no live game state (whether *this specific* Pot of Desires
  was already activated this turn is not knowable from a rules question in
  isolation), so this is out of scope for legality checking. The
  restriction is still parsed and stored (see Component 6) for future use.
- A complete, up-front table of every phase's activation rules. Only the
  Damage Step rule is specified here, sourced now; other phases' rules will
  be supplied incrementally by the project owner as development needs them.
- Designing the algorithm that matches a card's `activation_condition` text
  against the user's question as a whole (both to pick which effect a
  prompt refers to, and to judge whether that effect's condition is
  satisfied). This design specifies the *interface* each consuming
  component needs (inputs, outputs, and the clarify-on-ambiguity fallback)
  and defers the matching logic itself to a follow-up design pass.

## Existing deterministic meta-rules (for reference)

These already exist and are not changed by this design; the new components
below are additive and, where noted, validate against them.

| Rule | Where | What it encodes |
|---|---|---|
| Spell-speed assignment | `rules_engine/models.py::spell_speed_for` | Counter Trap → Speed 3 override; Quick/Quick-like → Speed 2; else Speed 1 |
| Priority/response legality | `rules_engine/priority.py::can_activate_now` | Speed 1 never responds; Speed 2/3 responds at ≥ top link's speed unless `prevents_response` |
| SEGOC ordering | `rules_engine/segoc.py::apply_segoc` | Turn player's simultaneous triggers chain first → resolve last |
| Chain resolution order | `rules_engine/chain.py::Chain.resolution_order` | LIFO |
| Missing-timing window | `rules_engine/timing.py::check_missing_timing` | Speed-1 vs Speed-2/3 table for whether a "when" window is open |
| Effect-type classification | `effect_parser/parser.py::classify_effect_type` | Text-structure grammar, run at ingestion time |
| PSCT cost/target split | `effect_parser/parser.py::parse_psct` | `Condition : Cost/Target ; Effect`, connector-priority table |
| Pending-vs-confirmed trust | `db/effects_repo.py` | A `pending` effect is never ground truth until `confirm_effect()` |
| Answer grounding | `orchestration/confidence.py::compute_confidence` | An answer citing an unsurfaced id scores `0.0` |

## Component 1: Rulebook ingestion

`ingestion/rulebook_loader.py` (`chunk_text`, `load_rulebook_file`) and
`db/rulebook_repo.py` (`insert_chunk`, `search_chunks`) already exist and
are fully tested, but `rulebook_chunks` holds no real content — the
loader's own tests use placeholder text ("Section one.", "Paragraph one."),
and there is no rulebook file checked into the repo.

This design's action: fetch the **live current Konami rulebook**
(`https://www.yugioh-card.com/eu/play/tcg-rulebook/`, the official site's
current-rulebook page — chosen over a frozen PDF snapshot so the ingested
content tracks whatever the current rules are, not a specific historical
version), save it as a local text file, and run it through the existing
`load_rulebook_file` → embed → `insert_chunk` pipeline. No new pipeline
code is needed; this is populating existing, tested infrastructure with
real data for the first time. `search_rulebook`'s RAG fallback (used both
by the main orchestration loop and, per this design, as the fallback for
activation-condition edge cases the deterministic layer doesn't cover)
depends on this being done — today it always returns zero chunks.

## Component 2: Preflight stage

New module `orchestration/preflight.py`, running once per question,
**before** the LLM sees it — not a tool the LLM chooses to invoke.

```
build_preflight_context(question: str) -> str
```

1. **Fuzzy card-name matching.** New `cards_repo.find_cards_mentioned_in(text)`
   — fuzzy (not exact-substring) matching of the question against known
   card names, so an incomplete or slightly misspelled name still resolves.
2. **Zero matches:** preflight is a no-op; the loop behaves exactly as it
   does today. Strictly additive — no regression path.
3. **Multiple plausible matches:** a new `ClarificationItem` kind,
   `"disambiguate_card"`, asks the user which card is meant, before the
   loop starts. This follows the same shape as `clarify.py`'s existing
   `"clarify"`/`"continuous_check"` items — same dataclass, same
   `format_clarification_context` handling — not a new mechanism.
4. **Exactly one match:** proceed to Component 3.

## Component 3: Multi-effect fetch and effect recognition

**Status: interface specified now, implementation deferred.** The project
owner wants to design the condition-matching pattern (see Component 4b)
before locking in this component's implementation, since both rely on the
same underlying capability: reading a card's stored text as a whole and
comparing it to the question. The pieces below are agreed and can proceed
independently of that follow-up design.

**Bug found and confirmed in scope to fix (deferred alongside the rest of
this component):** `effects_repo.get_confirmed_effect` runs
`SELECT ... WHERE card_id = %s AND status = 'confirmed'` and calls
`.fetchone()` with no `ORDER BY`. The schema (`card_effects_structured`)
places no uniqueness constraint on `card_id` — a card can have multiple
confirmed effects — so today, a card with more than one confirmed effect
silently loses all but one, non-deterministically (whichever row Postgres
returns first). None of the 5 currently-seeded cards happen to trigger
this, which is why it's gone unnoticed.

Fix: replace with `get_confirmed_effects` (plural), `.fetchall()`, no
`ORDER BY` needed — all rows are wanted, so there's no ordering to specify.

**Effect recognition interface:** given the question text and the full
list of a card's confirmed effects, decide which single effect the
question refers to.
- Exactly one plausible match → use it.
- Ambiguous (question doesn't distinguish between two or more effects) →
  a new `ClarificationItem` kind, `"which_effect"`, asks the user —
  same fallback shape as Component 2's `"disambiguate_card"`.
- The matching logic itself (how "plausible" is judged) is out of scope
  for this design; see Non-goals.

## Component 4: Activation legality — two independent checks

These were previously conflated in earlier drafts of this design and are
now explicitly separated, per project-owner direction.

### 4a. Structural activatability

`rules_engine/models.py::is_activatable(effect_type: EffectType) -> bool`.
A fixed lookup: `CONTINUOUS` and `CONDITION` → `False` (these effect types
are never "activated" in the game-rules sense); every other `EffectType` →
`True`. Global game law, fixed-size, hardcoded — same character as
`spell_speed_for`.

Wired into `rules_engine/resolve.py::resolve_chain`: before
`chain.add_link()` on an `"activate"` step, check
`is_activatable(effect.effect_type)`. On `False`, return a `Violation`
(same shape as the existing `priority_violation`) with a new reason,
`"not_activatable"`, instead of silently chaining an effect that
structurally cannot be activated.

### 4b. Condition satisfaction

Whether the effect's own `activation_condition` text is satisfied by what
the question describes. **The `activation_condition` field must be read
and matched as a whole** — a named phase (as in Effect Veiler's "During
your opponent's Main Phase") is only one recognizable pattern among many
condition types that appear across cards: summon-triggered ("If this card
is Normal Summoned"), opponent-action-triggered ("When a Spell/Trap Card
is activated"), board-state ("If you control no cards in your Spell & Trap
Card Zone"), and self-history conditions combined with a phase (Albion the
Branded Dragon's End Phase condition additionally qualified by "if this
card was sent to the GY this turn"). A phase-keyword lookup table alone
would miss most of these; the check operates on the specific matched
card's existing, already-stored `activation_condition` field, read at
query time — not a new precomputed global "allowed phases" field decided
for every card at ingestion time, which an earlier draft of this design
proposed and which the project owner corrected.

This is the same underlying capability Component 3 needs (reading stored
condition/effect text as a whole against the question), so the matching
algorithm for both is deferred together — see Non-goals.

**What is settled now, as first-pass grounding, independent of the
matching algorithm:** the Damage Step rule (Component 5), which the
project owner confirmed as sourced and usable today. Other phases' rules
will be supplied by the project owner incrementally as development needs
them — this design intentionally does not attempt to pre-specify a
complete phase-rule table.

## Component 5: Damage Step global rule

Sourced from the current official Konami rulebook (the same source as
Component 1): during the Damage Step, only three categories of effect may
be activated by default:

1. Spell Speed 2 effects that directly alter a monster's ATK/DEF.
2. Spell Speed 2 effects that negate the activation of a card or effect.
3. Spell Speed 3 cards (Counter Traps).

Plus effects whose own text explicitly names a Damage Step sub-phase
("during damage calculation," "at the start of the Damage Step," etc.).

This is global game law — fixed-size, independent of card count — and is
hardcoded in `rules_engine`, not derived from RAG retrieval quality. It
requires one new piece of per-effect data that doesn't already exist:
category 1 and category 2 are both Spell Speed 2, so `spell_speed_for`
alone can't distinguish them. A new categorical tag — "alters ATK/DEF" vs.
"negates an activation" vs. neither — is derived at ingestion time from
the effect text (same pipeline shape as `classify_effect_type`: parsed,
then gated through `review_agent`'s confidence threshold) and stored
alongside the existing `effect_type`/`spell_speed` data.

An earlier source found during research (goatformat.com) described a
different, more restrictive Damage Step rule limited to monster negation
effects only. That describes the 2005-era "Goat Format" ruleset, not
current rules, and is explicitly excluded from this design.

## Component 6: Once-per-turn / usage-count parsing

Card text such as Effect Veiler's "You can only use 1 'Effect Veiler'
effect per turn" is a usage-count restriction — orthogonal to timing, and
not currently decomposed by `parse_psct` (it's a trailing sentence after
the effect clause, outside the `Condition : Cost/Target ; Effect` split).

Extend the effect parser to extract this text and store it (a new
nullable column on `card_effects_structured`, e.g. `usage_limit_text`).
Per project-owner direction, this is parsed and kept in the DB purely for
future reference — it is **not** wired into any legality check. The
project has no live game-state tracking (no memory of whether a specific
prior activation happened earlier this turn), so enforcing it is
explicitly out of scope; see Non-goals.

## Data model changes

`card_effects_structured` gains two new nullable columns:
- A damage-step category tag (Component 5): text/enum,
  `'atk_def_alter' | 'negates_activation' | NULL`.
- `usage_limit_text` (Component 6): free text, parsed but unenforced.

No new column for phase/condition data (Component 4b) — that check reads
the existing `activation_condition` column directly, per the correction
described above.

## Governing architecture principle

Every rule introduced by this design falls into one of two buckets, and
which bucket determines where it's implemented:

- **Global game law** (Damage Step's Speed/category gate, structural
  activatability) is fixed-size — it does not grow as cards are added — and
  is hardcoded directly in `rules_engine`, the same way `can_activate_now`
  is today.
- **Per-card data** (the damage-step category tag, usage-limit text, and —
  once designed — condition-matching) must be extracted at *ingestion
  time* through the parser and `review_agent`'s confidence gate into
  structured, reviewed DB fields. It is never parsed at answer-time inside
  the engine.

This split is what keeps the rules engine from growing without bound as
card coverage scales past the current 5 hand-picked cards toward the
broader coverage CLAUDE.md lists as still missing: new complexity becomes
reviewed *data*, one card at a time, not accumulating *procedural code*.

## Testing

TDD per project convention — a failing test precedes each piece of
implementation.

- `is_activatable`: pure-function unit tests, including the
  Continuous/Condition → `False` cases.
- `find_cards_mentioned_in`: unit tests including a deliberate
  false-positive-substring case (one card name embedded in another, or in
  unrelated text) to confirm word-boundary matching doesn't over-match.
- `get_confirmed_effects` (Component 3, deferred): unit test against a
  fixture with two confirmed rows for one `card_id`, asserting both come
  back.
- `resolve_chain`: new test asserting a `"not_activatable"` violation on
  an `"activate"` step whose effect is `CONTINUOUS`/`CONDITION`.
- `preflight.py`: unit tests for zero-match (no-op), single-match, and
  multi-match (`"disambiguate_card"` item produced) cases against a
  fixture DB.
- `clarify.py`: tests for the new `"disambiguate_card"`/`"which_effect"`
  item kinds following the existing `"clarify"`/`"continuous_check"` test
  patterns.
- Damage Step category tag: parser unit tests once the extraction rule is
  written, plus a `resolve_chain` test for the Speed-2/category gate.
- Rulebook ingestion (Component 1): an integration-style test that
  `search_rulebook` returns non-empty results for a Damage-Step-related
  query once real content is loaded — this is what currently cannot be
  tested at all, since `rulebook_chunks` is empty.

## Out of scope

- The condition-matching algorithm itself (Components 3 and 4b) — deferred
  to a follow-up design pass, owned by the project owner.
- Enforcing once-per-turn/usage-count restrictions (Component 6) — no live
  game-state tracking exists in this project.
- A complete phase-by-phase activation rule table beyond Damage Step —
  supplied incrementally during development.
- Broader card coverage beyond the current 5 hand-picked cards — separate,
  already-tracked sub-project per CLAUDE.md.
