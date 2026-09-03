# AIJudge — Effect Parser Deterministic Rules & Printing-Eligibility Gate

## Purpose

Today's ingestion pipeline (`ingestion/seed.py:seed_card`) splits a card's
raw text into effect clauses entirely via LLM call (`clause_splitter.
split_effect_clauses`), then classifies/parses each clause with the
existing deterministic helpers in `effect_parser/parser.py`
(`classify_effect_type`, `parse_psct`, `classify_damage_step_category`,
`extract_usage_limit_text`), then reviews each clause in isolation via one
more LLM call (`review_agent.review_parsed_effect`). This design replaces
the LLM-driven *segmentation* step with deterministic rules grounded in
PSCT's own grammar, adds a printing-eligibility gate so pre-PSCT card text
is never fed through rules that assume PSCT grammar, adds first-class
handling for Extra Deck material lines, and extends the usage-limit
extraction to correctly scope a restriction across multiple effects
instead of just the clause it trails. The LLM's role narrows from "do the
segmentation" to "verify the deterministic segmentation, and resolve the
specific cases the grammar itself can't disambiguate" — consistent with
this project's core principle that the rules engine/deterministic layer
decides wherever possible and the LLM is reserved for what's genuinely
ambiguous.

Classified as an **architectural** change (brainstorming skill): it adds
two new `EffectType` values, one new schema column, three new modules, and
changes the call signature/behavior of `clause_splitter.
resolve_effect_clauses`, `review_agent.review_parsed_effect`, and
`ingestion/seed.py:seed_card`.

Every rule below was validated by hand against four real cards fetched
live from YGOPRODeck during design (not synthetic examples) — see "Worked
examples" for the full traces. Each rule in this doc exists because one of
those traces produced a wrong or incomplete result under the
straightforward version of the idea; where a trace *didn't* surface a
problem, that's noted too so this doc doesn't read as a change log for
problems that were already handled correctly.

## New pipeline shape

```
fetch_card
  -> printing-eligibility gate            (NEW — ingestion/printing_eligibility.py)
       ineligible -> insert one UNCLASSIFIED pending row, stop
       eligible   -> continue
  -> Card Material extraction             (NEW — effect_parser/sentence_splitter.py)
       Fusion/Synchro/Xyz/Link only; strips the materials line
       BEFORE the sentence tokenizer ever sees the text
  -> sentence-first deterministic split   (NEW — effect_parser/sentence_splitter.py)
  -> clause grouping + usage-limit scope  (NEW — effect_parser/usage_limit.py)
  -> LLM split-confidence verify          (existing score_split_confidence, always runs)
  -> per-clause classify/parse            (existing classify_effect_type / parse_psct /
                                            classify_damage_step_category, both extended)
  -> review, with cross-effect concurrence (existing review_parsed_effect, extended)
       when a usage-limit scope spans multiple clauses
  -> insert_pending_effect / confirm_effect (existing)
```

Card Material extraction runs **before** sentence splitting, not after —
an Extra Deck monster's materials line (e.g. `"Elemental HERO Bubbleman" +
"Elemental HERO Clayman"`) commonly has no trailing period at all before
the real effect text begins, which would corrupt a period-anchored
sentence tokenizer if the line were still present in the text it runs on.

## 1. Printing-eligibility gate

New module `ingestion/printing_eligibility.py`. Deterministic PSCT-grammar
rules (colon/semicolon structure, "target"/cost keywords, the whole
apparatus in `parser.py`) assume text written under Konami's Problem-
Solving Card Text initiative. A card whose most current known printing
predates that initiative's TCG rollout — **2011-07-08** — cannot be
assumed to follow that grammar, and should escalate to a human judge
immediately rather than be run through rules that assume a grammar it may
not use.

`PSCT_CUTOFF_DATE = date(2011, 7, 8)`.

**Eligibility check must use the full printing history, not just the
card's original release.** `fetch_card`'s response already includes
`card_sets` (the list of sets a card was printed in); this module cross-
references each entry's `set_name`/`set_code` against YGOPRODeck's
`cardsets.php` endpoint (which carries `tcg_date` per set) and checks
whether **any** printing is `>= PSCT_CUTOFF_DATE` — not just the first.
This distinction is load-bearing, not a hypothetical: *Elemental HERO
Mudballman* originally released 2006-12-22 (pre-PSCT), but was reprinted
in *Legendary Collection 2* (2011-10-04) and *Ra Yellow Mega Pack*
(2012-02-17) — both post-cutoff. Relying on `misc_info.tcg_date` alone (a
simpler option considered and rejected during design) would misclassify
this card, and any other card with a similar reprint history, as requiring
escalation when it doesn't.

`is_deterministic_parse_eligible(card_sets: list[dict], sets_index:
dict[str, date]) -> bool` — `sets_index` maps `set_name` (or `set_code`) to
its `tcg_date`, built once per ingestion run (not per card) by fetching
`cardsets.php` a single time and reusing the result, since it's a large,
slowly-changing catalog rather than per-card data.

**On ineligible:** `seed_card` skips every parsing step (deterministic and
LLM alike) entirely and inserts exactly one pending row: `effect_type =
EffectType.UNCLASSIFIED` (the enum value already exists, unused elsewhere
in current code, and already means exactly "not classified, needs a
human" — no new enum value needed), `effect = <verbatim card_text>`,
every other structured column `None`, `confidence_score = 0.0`. This row
is never auto-confirmed.

**Schema:** `cards` gains `deterministic_parse_eligible boolean not null`,
computed once at ingest by this gate. Persisting the result (rather than
only using it as transient ingest-time control flow) lets future review
tooling query "why is this card stuck at `UNCLASSIFIED`" without
re-deriving the printing check.

## 2. Card Material extraction

New `EffectType.CARD_MATERIAL` in `rules_engine/models.py`, added to
`_NON_ACTIVATABLE_EFFECT_TYPES` alongside `CONTINUOUS`/`CONDITION` — a
materials line is never activatable, so `is_activatable()` must return
`False` for it. Any user-facing rendering of this row (`orchestration/
preflight.build_known_facts_context`, API citation labels) must present it
distinctly — e.g. `"Card Material:"` — never as if it were an effect.

**Trigger condition:** `card_type` contains one of Fusion/Synchro/Xyz/
Link. **This check must be case-insensitive** (or matched against the
literal 4 strings YGOPRODeck actually returns). The API's real `type`
field for Xyz monsters is `"XYZ Monster"` — all-caps XYZ — not `"Xyz
Monster"`; a naive case-sensitive substring check for `"Xyz"` silently
misses every real Xyz monster in the database. Confirmed against *Gem-
Knight Pearl* (`type: "XYZ Monster"`).

**Extraction:** the first line of `card_text` (split on the first `\r\n`/
`\n`) is pulled out as the materials text, stored as its own
`card_effects_structured` row (`effect = <materials line verbatim>`,
every other column `None`), and stripped from the text before the
sentence splitter runs.

**Empty-remainder guard:** a vanilla Extra Deck monster's entire
`card_text` can *be* the materials line, with nothing following it at all
(confirmed against *Gem-Knight Pearl*: `desc: "2 Level 4 monsters"`,
`misc_info.has_effect: 0`). After stripping the materials line, if the
remainder is empty (after stripping whitespace), the pipeline stops with
just the one `CARD_MATERIAL` row — it must not feed `""` into
`classify_effect_type`, which would otherwise fall through its own
no-colon/no-semicolon branch and fabricate a spurious `CONTINUOUS` row
out of nothing.

## 3. Sentence-first deterministic split

New module `effect_parser/sentence_splitter.py`. `split_sentences(text:
str) -> list[str]` tokenizes on sentence boundaries — a run of text from a
capital letter to the next sentence-final period — replacing the LLM as
the segmentation engine. This is the deterministic pre-pass; the existing
`score_split_confidence` LLM call still always runs afterward to verify
the resulting grouping (see "Clause grouping" below), per the earlier
design decision to keep an LLM check in the loop even though it no longer
does the splitting itself.

Validated clean (no embedded-period edge cases) against all four worked
examples — PSCT's own convention of ending each condition/cost/effect
clause with exactly one sentence-final period, with internal punctuation
using commas/semicolons/colons instead, makes this reliable across every
case traced so far. No embedded-period failure mode has been found during
design; if one turns up during implementation (e.g. an abbreviation or a
quoted card name containing a period), handle it as a targeted addition to
the tokenizer, not a reason to fall back to the LLM for segmentation.

## 4. Clause grouping

Sentences are grouped into effect clauses: a sentence starts a new clause
by default, **except**:

- A sentence matching a usage-limit/restriction pattern (see "Usage-limit
  scope grammar" below) is never its own clause — it attaches to whichever
  clause(s) it scopes.
- A sentence's classification as a genuinely new activatable effect vs. a
  continuation of the previous one reuses the existing structural
  signals `classify_effect_type` already looks for (its own top-level
  colon, a leading "If"/"When" trigger phrase, an enumerated/bulleted
  marker) rather than introducing a second, separate boundary-detection
  ruleset.

The resulting clause list is passed to `score_split_confidence` (existing,
unchanged signature) exactly as today's LLM-produced candidate list was —
below `DEFAULT_CONFIDENCE_THRESHOLD` (0.75) still falls back to treating
the whole (material-stripped) remainder as one effect, per
`resolve_effect_clauses`'s existing fallback behavior.

## 5. Usage-limit scope grammar

New module `effect_parser/usage_limit.py`, replacing the plain-regex
`extract_usage_limit_text` for the scoping question (that function's
verbatim-sentence extraction stays useful and is reused; what's new is
determining *which clause(s)* the extracted sentence applies to).

**Selector form** — how the restricted set is referenced:

- **Self** (implicit): no positional pointer at all, or "this effect" —
  scopes to the one clause the sentence trails. This is `extract_
  usage_limit_text`'s existing behavior and needs no change for this
  case.
- **Positional pointer, singular** — "the preceding effect" / "the
  following effect" — exactly the one adjacent clause on that side.
- **Positional pointer, plural** — "the preceding effects" / "the
  following effects" — **every** clause on that side; count is however
  many clauses actually precede/follow in the already-grouped clause
  list, not a fixed number. Confirmed against *Tearlaments Rulkallos*:
  `"You can only use each of the following effects of "Tearlaments
  Rulkallos" once per turn."` scopes to both clauses after it (the Quick
  negate effect and the Trigger Special Summon effect), not the
  Continuous effect before it.
- **Group-select** — "N of these effects" / "N of the following
  effect(s)" — picks N from a set as a **shared** budget (activating one
  counts against the others). When a positional pointer is present, the
  set is resolved via the positional rule above (so "1 of following
  effect" — singular — collapses to exactly one adjacent clause, sharing
  its budget with nothing). When the reference is bare ("these effects,"
  no positional pointer), the set is ambiguous.
- **Each-of, independently budgeted** — "each of these/the following
  effects...once per turn" — grammatically distinct from group-select:
  every clause in the resolved set gets its **own** independent
  once-per-turn budget, not a shared one. This is a real, common pattern
  discovered during design (not present in the grammar as originally
  scoped) — confirmed on *Tearlaments Rulkallos* as shown above; do not
  conflate it with group-select just because both use "these effects"-
  style phrasing.
- **Named-card** — "N '[Card Name]'" — restricts the named card/its
  copies, not clause position. Carries a verb-width signal: "activate" is
  narrow (initial hand→field placement only), "use" is broad (also
  covers field/GY/hand applications) — this distinction is informational
  metadata alongside the extracted text, not something requiring separate
  storage, since `usage_limit_text` is reference-only and never enforced
  (see below).

**Ambiguous case → LLM concurrence.** A bare "these effects" reference
with no positional pointer cannot be resolved by grammar alone — the
scoped set could be "every effect on the card," a previously-enumerated
sublist, or something else entirely dependent on how the card's text is
laid out. This is the one case in the whole grammar that escalates: the
LLM is shown the card's full clause list and asked to resolve which
clauses the restriction applies to. This is the concrete trigger condition
for "confront the LLM if needed" — everything else in this section
resolves deterministically.

**Frequency stays embedded when fused into the condition, by design — not
a gap.** A restriction can appear as a leading qualifier fused directly
into an activation condition rather than as a separate trailing sentence
at all — confirmed on *Floowandereeze & Empen*: `"Once per battle, during
damage calculation, if this card battles an opponent's monster (Quick
Effect): ..."` has no distinct "You can only...per X" sentence, and "per
battle" isn't even a period `extract_usage_limit_text`'s pattern
recognizes. This was explicitly evaluated and rejected as something to
fix: per domain ruling, this stays embedded in `activation_condition`
exactly as parsed today, untouched by this design. It is captured
verbatim there; it is simply not additionally tagged into a structured
usage-limit field. No code change follows from this case — documented
here only so it isn't rediscovered as a "bug" later.

**Storage:** a resolved scope duplicates the same `usage_limit_text`
string onto every effect row it restricts. No new join table — this field
is reference-only and never enforced (matches the existing docstring on
`extract_usage_limit_text`), so correct duplication across the relevant
rows is sufficient; there's no live game state to track a shared budget
against.

## 6. Damage-step category: self-reference widening

`_CARD_MOVED_TRIGGER_PATTERN` (parser.py) currently requires the literal
substring `"this card"`. Extra Deck monsters routinely self-refer using
their summon-mechanic name instead — `"this Xyz Monster"`, `"this Synchro
Monster"`, `"this Fusion Summoned card"`, `"this Link Monster"` — and the
literal-`"this card"` pattern misses all of them. Confirmed on
*Tearlaments Rulkallos*: `"If this Fusion Summoned card is sent to the GY
by a card effect"` doesn't match today's regex (it happened not to change
that card's *correct* output, since this particular condition isn't
battle-bound anyway — see below — but the gap is real and will bite a
genuine battle-destruction trigger on some other Extra Deck monster).
Widen the self-reference alternation to also match `"this (Xyz|Synchro|
Fusion|Link|Pendulum) Monster"` and `"this Fusion Summoned card"`.

**The self-movement verb list itself (destroy/banish/send/return/summon/
flip/tribute) stays exactly as broad as it is today — this was
deliberately evaluated during design and confirmed correct, not a gap.**
Traced against *Floowandereeze & Empen*'s `"If this card is Tribute
Summoned: ..."`, which the current pattern *does* match (`"this card"` +
`"Summoned"`) — meaning the engine currently allows this Trigger to
activate during the Damage Step, despite Tribute Summoning normally
happening in the Main Phase and having no obvious Damage-Step-exclusive
timing the way "destroyed by battle" does. Per explicit ruling: this is
correct as-is. The category represents "this condition *could* be met
during the Damage Step," which remains possible in principle (e.g. some
other effect enabling a Tribute Summon during the Damage Step) even though
it isn't this specific card's concern — narrowing the verb list to only
battle-related verbs was considered and rejected.

## 7. Summoning Condition classification

New `EffectType.SUMMONING_CONDITION` in `rules_engine/models.py`, added to
`_NON_ACTIVATABLE_EFFECT_TYPES` — a standing restriction, never activated,
same category as `CONTINUOUS`/`CONDITION`/`CARD_MATERIAL`.

Today, a clause like *Elemental HERO Mudballman*'s `"Must be Fusion
Summoned and cannot be Special Summoned by other ways."` falls into
`CONTINUOUS` only because `classify_effect_type`'s no-colon/no-semicolon
branch has no third option — it checks for `"you can only"` (→
`CONDITION`) and otherwise defaults to `CONTINUOUS`. This pattern is
near-universal on non-Normal Extra Deck (and Ritual) monsters and is
official rules terminology distinct from both.

**Detection: a small canonical-phrase list, checked before the existing
`"you can only"` check, with a conservative fallback — not an LLM
escalation.** This mirrors the confidence assessment reached during
design: this specific boilerplate is some of the most rigidly formulaic
text Konami produces (reused near-verbatim across thousands of cards, for
legal/rules reasons rather than creative variation), so precision on the
canonical forms is expected to be high. The known risk is recall — rarer
phrasing variants not seen during this design's four-card sample — not
false positives on the phrases that are matched. Per explicit ruling, that
risk is accepted with a conservative fallback rather than resolved via
LLM concurrence the way the ambiguous usage-limit case is: anything that
doesn't match one of the known phrases and doesn't match `"you can only"`
falls through to `CONTINUOUS` exactly as today, rather than guessing.

Canonical phrases (case-insensitive):
- `must (?:be|first be) .*summoned`
- `cannot be special summoned except`
- `cannot be normal summoned or set`
- `cannot be used as .*material`

## 8. Review concurrence

`review_agent.review_parsed_effect` gains an optional context parameter
carrying the card's other parsed effects. It's populated — and the
review prompt actively asked to reason about it — **only** when a
usage-limit scope resolved in step 5 spans more than one clause, so the
LLM double-checks scope consistency specifically (e.g., "does this
restriction really cover both of these clauses, and only these two")
rather than running a blanket cross-effect review on every call
regardless of relevance. This matches the concrete need identified during
design ("if parsing effect reach some usage per turn limit I want this
specific part of effect to be understood concerning other effects on
card") rather than a general expansion of what review checks.

## Data model changes

- `rules_engine/models.py`: add `EffectType.CARD_MATERIAL =
  "card_material"` and `EffectType.SUMMONING_CONDITION =
  "summoning_condition"`; add both to `_NON_ACTIVATABLE_EFFECT_TYPES`.
- `db/schema.sql`: add `cards.deterministic_parse_eligible boolean not
  null`.
- No other schema changes — usage-limit scope is represented by
  duplicating `usage_limit_text` across rows (see "Usage-limit scope
  grammar" above), not a new column/table.

## Worked examples (validation)

All four cards were fetched live from `https://db.ygoprodeck.com/api/v7/
cardinfo.php` during design (the same endpoint `ygoprodeck_client.
fetch_card` calls) and traced by hand against this design before it was
written up, per the brainstorming skill's dry-run step. None were
ingested; this is a design-time trace only, no DB rows were created.

### Tearlaments Rulkallos (Fusion Monster)

- Eligible (only printing: Darkwing Blast, `tcg_date` 2022-10-20).
- Card Material: `"Tearlaments Kitkallos" + 1 "Tearlaments" monster`
  (no trailing period — confirms material extraction must precede
  sentence splitting).
- 3 further clauses: `CONTINUOUS` ("Other Aqua monsters..."), `QUICK`
  (negate-activation Quick Effect, `damage_step_category =
  negates_activation`), `TRIGGER` (self Special-Summon-from-GY).
- Usage-limit sentence `"You can only use each of the following effects
  of "Tearlaments Rulkallos" once per turn."` scopes to the `QUICK` and
  `TRIGGER` clauses (positional-plural "following," each-of
  independently-budgeted), not the preceding `CONTINUOUS` clause.
- Surfaced findings 1 and 2 (each-of selector form; self-reference
  widening for damage-step category).

### Floowandereeze & Empen (Effect Monster — not Extra Deck)

- Eligible (`tcg_date` 2021-11-04).
- No Card Material row — `type` has no Fusion/Synchro/Xyz/Link, correctly
  skipped (negative-case confirmation).
- 3 clauses: `TRIGGER` ("If this card is Tribute Summoned...",
  `damage_step_category = card_moved_trigger` — see finding 3),
  `CONTINUOUS` ("While this Tribute Summoned card is in the Monster
  Zone..."), `QUICK` (damage-calculation ATK/DEF-halving effect,
  `damage_step_category = atk_def_alter`, checked and matched before the
  `activation_condition`'s literal "damage calculation" phrase is even
  considered, since `atk_def_alter`/`negates_activation` are checked
  against `effect_text` first).
- Surfaced findings 3 and 4 (both evaluated and explicitly left
  unchanged, per rulings above).

### Gem-Knight Pearl (XYZ Monster, vanilla)

- Eligible (`tcg_date` 2012-05-24).
- Entire `card_text` is the materials line (`"2 Level 4 monsters"`,
  `misc_info.has_effect: 0`) — one `CARD_MATERIAL` row, nothing else.
- Surfaced findings 5 (case-insensitive `card_type` matching — API
  returns `"XYZ Monster"`, all-caps, not `"Xyz Monster"`) and 6
  (empty-remainder guard after material extraction).

### Elemental HERO Mudballman (Fusion Monster, pre-PSCT original)

- Eligible **only via reprint**: original TCG release 2006-12-22
  (pre-cutoff), but reprinted in Legendary Collection 2 (2011-10-04) and
  Ra Yellow Mega Pack (2012-02-17) — both post-cutoff. This is the case
  that settled the printing-eligibility design: a `misc_info.tcg_date`-
  only check would have wrongly forced this card to escalation.
- Card Material: `"Elemental HERO Bubbleman" + "Elemental HERO Clayman"`.
- 1 further clause: `"Must be Fusion Summoned and cannot be Special
  Summoned by other ways."`, currently `CONTINUOUS` by default fallback —
  the case that motivated `EffectType.SUMMONING_CONDITION` (finding 9).

## Testing approach

TDD per project convention — failing test before implementation code,
most importantly here since this is exactly the kind of surface where a
wrong-but-confident result is the failure mode the project exists to
avoid. Each new grammar rule gets unit tests built from real card text
(the four cards above, plus additional cases as implementation surfaces
them) rather than synthetic examples, consistent with how this design was
validated. Printing-eligibility gating is tested with mocked `card_sets`/
`cardsets.php` responses (both the reprint-saves-a-pre-PSCT-card case and
the no-qualifying-printing case). Card Material and Summoning Condition
detection are tested against real Fusion/Synchro/Xyz/Link card text,
including the vanilla (`CARD_MATERIAL`-only) case. Full `seed_card`
integration is exercised against `Baronne de Fleur` and `Borreload
Dragon` — both already-seeded Link Monsters whose material lines are
currently unhandled — to confirm the new pipeline order doesn't regress
existing seeded output for the cards already in `HAND_PICKED_CARDS`.

## Explicitly out of scope

- **No re-ingestion of already-seeded cards as part of this change.**
  `HAND_PICKED_CARDS`'s existing rows are not touched by this design;
  re-running `seed.py` against them with the new pipeline (which will
  change their output, particularly for Baronne de Fleur and Borreload
  Dragon) is a separate follow-up decision.
- **No numeric/machine-readable frequency modeling.** Usage-limit
  frequency (count × period) stays a verbatim reference string, per the
  existing "never enforced" design — this document doesn't introduce
  live-state tracking.
- **No broader printing-history modeling beyond the eligibility boolean**
  — `cards.deterministic_parse_eligible` is a derived flag, not a stored
  printing history; if future work needs the actual set/date list, that's
  a separate design.
- **No changes to `orchestration/`'s tool-use loop or API layer** beyond
  the `preflight.build_known_facts_context` rendering label change for
  `CARD_MATERIAL` noted in "Card Material extraction" above.
