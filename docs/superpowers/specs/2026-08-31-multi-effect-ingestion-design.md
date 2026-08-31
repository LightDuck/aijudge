# AIJudge — Multi-Effect Ingestion & Damage-Step-Aware KNOWN FACTS Design

## Purpose

`docs/superpowers/specs/2026-08-27-activation-recognition-design.md` (Component 3) already identified a real
bug: `effects_repo.get_confirmed_effect` does `SELECT ... WHERE card_id = %s AND status = 'confirmed'` then
`.fetchone()` with no `ORDER BY` — silently discarding every confirmed effect but one for any card that has more
than one, non-deterministically. That design named the fix (`get_confirmed_effects`, plural, `.fetchall()`) but
explicitly deferred implementing it, pending a separate design pass for "effect recognition" (matching a
question to a specific effect) that this design does **not** attempt.

That gap stopped being theoretical once `Baronne de Fleur` (a Synchro Monster with three independent effects)
was added to `HAND_PICKED_CARDS`: today's ingestion (`seed_card`) parses a card's *entire* `card_text` as
exactly one effect clause, always, regardless of how many effects the card actually has. For Baronne de Fleur
this produces one garbled or partial `card_effects_structured` row instead of three accurate ones — and even
once `get_confirmed_effects` exists, there's nothing upstream populating more than one row per card.

This design closes both gaps: it implements the previously-deferred `get_confirmed_effects` fix, and adds the
ingestion-time capability to actually produce multiple effect rows for a card that has multiple effects — so
that a question like "is one of Baronne de Fleur's effects usable in the Damage Step" can be answered from
deterministic `KNOWN FACTS`, per the project's guiding principle ("the LLM orchestrates and explains; the rules
engine and database decide").

Classified as **architectural** (brainstorming skill): touches the DB repo layer, ingestion, orchestration
tools, confidence scoring, and preflight grounding — no single existing flow covers it, and it changes an
existing interface (`lookup_card`'s output shape) that other components depend on.

## Investigation: why automatic syntactic splitting is unsafe

Before designing the split mechanism, the real `card_text` for all 6 hand-picked cards was fetched from the
live ygoprodeck API (not assumed from memory) to check whether a cheap syntactic rule — split on sentences, on
"●" bullets, on "(1)/(2)" markers — could reliably separate multiple effects:

- **Ash Blossom & Joyous Spring** uses "●" bullets, but they enumerate what "these effects" means inside a
  *single* trigger condition ("When a card or effect is activated that includes any of these effects... ● Add a
  card... ● Special Summon... ● Send a card..."), not three separate effects. Splitting on bullets or sentence
  boundaries would fragment one real effect into three garbage rows.
- **Infinite Impermanence** has two sentences, but the second ("If you control no cards, you can activate this
  card from your hand.") is an alternate-activation permission for the *same* effect, not a second effect.
- **Baronne de Fleur** genuinely has three independent effects, each its own "Once...: ..." clause, with a
  usage-limit sentence sitting between effects 2 and 3 that restricts only effect 2.
- The other three cards (**Called by the Grave**, **Effect Veiler**, **Solemn Strike**) are each a single
  sentence, single effect — trivially safe either way.

No syntactic signal in hand (bullets, sentence count, numbering) distinguishes "these are separate effects" from
"this continues/modifies the previous effect" — it requires understanding what each sentence *means*. That's
exactly why `2026-08-27-activation-recognition-design.md` deferred this. This design accepts that the split
itself needs semantic judgment, and contains that judgment behind two independent safety gates (below) so a bad
split degrades to today's existing single-effect behavior rather than becoming false ground truth.

## Goals

- Implement `get_confirmed_effects` (plural) as specified (but not built) by the prior design.
- Let ingestion produce one `card_effects_structured` row per real effect a card has, for cards that need it,
  without weakening accuracy for the cards that don't.
- Surface all of a card's effects — not just one — in the deterministic `KNOWN FACTS` block the orchestration
  loop already relies on, each annotated with its own Damage Step legality, computed via the rules engine
  functions that already exist (`is_activatable`, `can_activate_during_damage_step`) — no new rules_engine code.
- For Damage-Step-legality questions specifically, this removes the need for the LLM to correctly orchestrate a
  `resolve_chain` tool call at all: the deterministic fact is already in the grounding context it reads before
  reasoning.

## Non-goals

- **Effect recognition** (deciding which single effect a question refers to) — still deferred, per the prior
  design's own Non-goals. This design surfaces *all* effects' facts and leaves synthesizing which one(s) answer
  the question to the LLM's final-answer step, not a new deterministic matcher.
- **A manual per-card override table.** YAGNI: the safety gates below always have a safe fallback (today's
  single-effect behavior), so a manual escape hatch isn't needed up front. If the LLM splitter proves unreliable
  for a specific future card, that's a small, targeted follow-up, not something to build preemptively.
- **Re-seeding/migrating already-seeded cards automatically.** `cards.name` is `UNIQUE`; re-running `seed_card`
  for an already-seeded name fails on insert today. Picking up multi-effect data for an already-seeded card
  requires deleting its existing row first — an existing, unrelated limitation this design doesn't change.
- **Schema changes.** `card_effects_structured` already allows multiple rows per `card_id` with no uniqueness
  constraint — nothing to migrate.
- **rules_engine changes.** `is_activatable`, `can_activate_during_damage_step`, `spell_speed_for` are reused
  exactly as they exist today.
- **Enforcing usage-limit restrictions.** Unchanged from the prior design: parsed and stored, never enforced —
  the project tracks no live game state.

## Component 1: `get_confirmed_effects` (plural)

`db/effects_repo.py`:
- Add `get_confirmed_effects(card_id: str) -> list[dict]` — same
  `SELECT ... WHERE card_id = %s AND status = 'confirmed'` as today's `get_confirmed_effect` (unconfirmed rows
  are never ground truth, unchanged), but `.fetchall()` instead of `.fetchone()`. No `ORDER BY` needed for
  correctness (all rows are wanted); tests assert on the returned set, not a specific order.
- Remove `get_confirmed_effect` (singular) — replace both of its callers (`orchestration/tools.py`,
  `orchestration/preflight.py`) with the plural function. Keeping both around would leave two subtly different
  ways to read the same table for no benefit.

## Component 2: LLM-proposed effect-clause splitting, doubly gated

New module `effect_parser/clause_splitter.py` (parallel to `review_agent.py` — deterministic parsing stays in
`parser.py`; anything LLM-involving lives alongside `review_agent.py`).

**Step A — propose boundaries.** `split_effect_clauses(llm_client, card_text) -> list[str]`:
- Prompts the LLM to return the card's distinct, independently-activatable effects as exact verbatim excerpts of
  `card_text`, one per line-delimited segment. The prompt explicitly instructs that a trailing usage-limit
  sentence, or a sentence that only modifies/restricts/grants an alternate activation method for an effect
  already stated, is *not* its own effect — it stays attached to the effect it modifies (this is what correctly
  keeps Ash Blossom's bullets and Infinite Impermanence's second sentence from being wrongly split, per the
  investigation above). If the card has one effect, the whole text comes back unchanged as a single segment.
- Parse the delimited response into a list of candidate segments.
- **Gate 1 — deterministic reconstruction check:** whitespace-normalized concatenation of the candidate segments
  must equal the whitespace-normalized original `card_text`. This catches omission or paraphrasing (the LLM
  inventing/dropping wording). On mismatch, discard the split entirely and return `[card_text]` — today's
  existing single-effect behavior, always a safe fallback.

**Step B — validate split quality.** Gate 1 proves the segments *reconstruct* the original text; it does not
prove the *boundaries* are correct (a wrong split can still use 100% of the original characters — e.g. one real
effect cut in half). So when Step A returns more than one segment, a second LLM-scored check runs: given the
full original `card_text` and the proposed segments, score confidence (0.0–1.0, same pattern as
`review_agent.review_parsed_effect`) that these are genuinely independent, correctly-bounded effects. Below
threshold (`DEFAULT_CONFIDENCE_THRESHOLD`, reused from `review_agent`), discard the split and fall back to
`[card_text]`.

These two gates matter because `review_parsed_effect`'s *existing* confidence check, run per-chunk once
splitting is trusted, cannot catch a bad split on its own — it only ever sees one already-(possibly-wrongly-)
bounded chunk's own text as `raw_text`, so it judges whether that chunk's Condition/Cost/Effect breakdown
matches *that chunk*, never whether the chunk's boundary was correct in the first place.

**Wiring into `seed_card`:** call the composed `split_and_validate` step once per card to get a list of effect
texts (`[card_text]` in the fallback/no-split case, exactly matching today's behavior for every currently-seeded
card). Loop the *existing, unchanged* per-clause pipeline once per effect text: `classify_effect_type`,
`parse_psct`, `classify_damage_step_category`, `extract_usage_limit_text`, `review_parsed_effect`,
`insert_pending_effect`, and `confirm_effect` when that clause's own review clears threshold — one
`card_effects_structured` row per effect. None of those functions change; only how many times, and over what
substrings, they're called. (`extract_usage_limit_text` now runs per-effect-clause instead of once over the
whole card, which is strictly more correct: a usage-limit sentence attached to one effect by the splitter no
longer gets misattributed to unrelated effects on the same card.)

## Component 3: `orchestration/tools.py` — `lookup_card` returns `confirmed_effects`

`lookup_card` returns `"confirmed_effects": [...]` (a list, possibly empty) instead of
`"confirmed_effect": {...} | None`. This is a breaking shape change to what the LLM's tool-call result and
`confidence.py` see — every caller/test using the singular key updates to the plural list.

## Component 4: `orchestration/confidence.py`

`update_signals`: `state.missing_structured_effect = True` when `result.get("confirmed_effects")` is falsy
(missing key or empty list) — same signal, adapted from "is None" to "is empty."

## Component 5: `orchestration/preflight.py` — multi-effect `KNOWN FACTS`

`build_known_facts_context(card)`:
- Calls `get_confirmed_effects(card["id"])`; empty list → `""`, same fallback as today.
- Otherwise, renders one line per effect. For each, build a `rules_engine.models.Effect` from the row (using the
  existing `spell_speed_for(effect_type, card_type=card["card_type"])`) and compute, with existing functions
  only: `is_activatable(effect_type)` and `can_activate_during_damage_step(effect)`. Each line includes: an
  index, effect type, spell speed, activatable, **damage-step legal** (new), and the existing optional fields
  (activation condition, damage step category, usage limit) when present. `damage-step legal` is always
  computed and shown for every effect, the same way `activatable` already is — the preflight layer doesn't
  interpret the question, it just surfaces every deterministic fact and lets the LLM's final synthesis pick out
  what's relevant.

## Testing

TDD per project convention.

- `get_confirmed_effects`: fixture with two confirmed rows for one `card_id` (and one unconfirmed row, to prove
  `status = 'confirmed'` filtering still holds) asserts both — and only both — confirmed rows come back.
- `clause_splitter.split_effect_clauses`: a single-effect response (list of length 1, unchanged text); a
  multi-effect response that reconstructs cleanly; a response that fails Gate 1 (paraphrased/lossy) falling back
  to `[card_text]`; a response that passes Gate 1 but fails Gate 2 (low split-confidence) falling back to
  `[card_text]`.
- `seed_card`: a fake multi-effect response produces multiple `card_effects_structured` rows, each independently
  confirmed/pending per its own review score; a single-effect card (today's fixtures) still produces exactly one
  row, unchanged.
- `lookup_card`/`confidence.py`: adapted from `confirmed_effect` to `confirmed_effects` list shape.
- `build_known_facts_context`: multi-effect fixture asserts one line per effect including a correct
  `damage-step legal` value for at least one `True` and one `False` case (mirroring the Baronne de Fleur
  hand-verification done during this design: its Quick Effect that negates an activation comes out
  Damage-Step-legal; its two Speed-1 effects do not).

## Out of scope

- Effect recognition / which-effect-the-question-is-about matching (still deferred, per the prior design).
- A manual per-card split override table (YAGNI — add only if a real card needs it).
- Re-seeding already-seeded cards, schema changes, rules_engine changes, usage-limit enforcement — all unchanged
  from today or the prior design, as detailed in Non-goals above.
