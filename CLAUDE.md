# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

AIJudge is a Yu-Gi-Oh! TCG rules-adjudication assistant. Given a user's rules question, it answers with cited
sources or explicitly escalates to a human judge rather than hallucinate. Guiding principle: **the LLM
orchestrates and explains; the rules engine and database decide.** Anywhere LLM reasoning can be replaced with a
deterministic lookup or algorithm, it is — that's where accuracy-critical bugs live.

The project has completed its first "thin slice": the rules engine, DB layer, effect parser, ingestion/seed
script, LLM orchestration (the agentic tool-use loop), and a REPL CLI all exist and are tested, and
`python -m aijudge` runs end-to-end. `src/aijudge/__main__.py` wires the default path — a real `AnthropicLLMClient`
(hosted, reading `ANTHROPIC_API_KEY`) for the LLM and a local `OllamaEmbeddingClient` (via Ollama, $0 cost, no API
key) for embeddings. `src/aijudge/entrypoint.py` is an alternate, fully-hosted wiring using `AnthropicLLMClient` and
`OpenAIEmbeddingClient`, reading `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` from the environment (`.env` via
`python-dotenv`), for when a hosted embedding provider is preferred over local Ollama. See
`docs/superpowers/specs/2026-08-18-thin-slice-design.md` for the full design spec and
`docs/superpowers/plans/2026-08-18-foundations.md` for the implementation plan this codebase was built from
(both are useful for *why*, but the actual code is ground truth for *what exists now* — the plan doc is a
historical scaffold and has already drifted in places, e.g. `has_target`, `ygoprodeck_id NOT NULL`, and the
`SpellSpeed.COUNTER` / `prevents_response` additions below post-date it). Provider-wiring decisions (OpenAI over
Voyage/Ollama for embeddings, the `dimensions=384` truncation to match the pgvector schema) are logged in
`docs/superpowers/specs/2026-08-20-provider-wiring-design.md`.

Still missing for a public v1.0: broader card coverage (currently 10 randomly-sampled cards) and the frontend itself —
each is its own separate sub-project. The HTTP/API service layer (`src/aijudge/api/`) now exists, wrapping the
orchestration loop and clarification flow behind two stateless REST endpoints — see
`docs/superpowers/specs/2026-08-27-api-layer-design.md` for the design and the `api/` bullet under Architecture
below. The frontend is not yet designed; it will consume that API's contract.

## Commands

Install (editable, with dev deps):
```
pip install -e ".[dev]"
```

Start the DB (Postgres 16 + pgvector via Docker Compose; host port **5433**, not 5432 — check `.env`/`.env.example`
before assuming the default):
```
docker compose up -d db
cp .env.example .env   # first time only; .env is gitignored
```

Run the full test suite:
```
pytest
```

Run a single test file / test:
```
pytest tests/rules_engine/test_segoc.py -v
pytest tests/rules_engine/test_segoc.py::test_turn_player_effects_are_chained_first_and_so_resolve_last -v
```

Run migrations manually (repos call `run_migrations`-adjacent setup themselves in tests, but for a fresh DB):
```
python -c "from aijudge.db.migrate import run_migrations; run_migrations()"
```

**DB-dependent tests auto-skip when `DATABASE_URL` isn't set** (`pytestmark = pytest.mark.skipif("DATABASE_URL" not
in os.environ, ...)` at the top of each `tests/db/*` file). This means `pytest` runs green with zero setup — the
rules engine, embeddings, LLM, and effect-parser suites are pure-Python — but silently skips DB coverage if you
forget to bring Docker up. Before running anything that touches Postgres, check `DATABASE_URL` and `docker ps`
first rather than discovering the DB is down after the fact. Each DB-test module truncates its own tables in
`setup_function`, so tests assume a running instance, not a pristine one per run.

There is no lint/format command configured yet (no ruff/black/mypy config in `pyproject.toml`).

## Architecture

`src/aijudge/` is organized into independent-by-design modules, mirroring the sub-project decomposition in the
spec:

- **`rules_engine/`** — pure Python, zero DB/LLM dependency. This is the deterministic core the spec is protecting:
  - `models.py` — `EffectType`, `SpellSpeed` (NORMAL=1, QUICK=2, COUNTER=3), `Effect`, `ChainLink`.
    `spell_speed_for()` special-cases Counter Traps (Spell Speed 3) via a `race` check (`race == "Counter"`), not
    effect type alone. It takes `race`, not `card_type` — YGOPRODeck's real API returns the generic `"Trap Card"`
    in `type` and the actual subtype (`"Counter"`, `"Quick-Play"`, ...) in a separate `race` field that's never
    folded into `type`, so a `card_type` substring check can never actually see "Counter" (see `cards.race` below).
    `is_activatable(effect_type)` says whether an effect of that type can be activated at all (as opposed to a
    passive `CONTINUOUS`/`CONDITION` effect) — checked by `resolve.resolve_chain` before anything else on an
    `"activate"` step.
  - `chain.py` — `Chain`: LIFO resolution order (`resolution_order()` reverses insertion order; `resolve_next()`
    pops the top).
  - `segoc.py` — `apply_segoc()`: the module the spec calls out as the most common source of wrong answers. **The
    turn player's simultaneous triggers are chained first, which — because resolution is LIFO — means they
    resolve LAST**, not first. Non-turn-player effects go on the chain second and resolve first.
  - `priority.py` — `can_activate_now()`: Spell Speed 1 can only activate into an empty chain (never responds, not
    even to another Speed-1 effect). Speed 2/3 can respond if its speed is **at or above** the top chain link's
    speed (empty chain counts as speed 0), unless the top link's effect sets `prevents_response=True`, which
    blocks all response regardless of speed. `can_activate_during_damage_step(effect)` is a separate, additional
    check for the Damage Step: Spell Speed 3 (Counter Traps) always; a Spell Speed 2 effect whose
    `damage_step_category` is `"atk_def_alter"` or `"negates_activation"`; or, regardless of spell speed, an
    effect whose `damage_step_category` is `"explicit_permission"` (its own activation condition names "damage
    step"/"damage calculation" directly) or `"card_moved_trigger"` (a Trigger-type effect whose own card is what
    moved — e.g. "if this card is destroyed by battle" — since that condition can only ever be met during/after
    the Damage Step). The latter two are ungated by spell speed because a plain Trigger Effect is normally Speed
    1 but is Damage-Step-legal anyway in these cases. Both this check and `can_activate_now` must pass for a
    Damage Step activation to be legal.
  - `resolve.py` — `resolve_chain(scenario)` drives a scenario's `"segoc_batch"`/`"activate"` steps through the
    above checks, returning a `ResolutionResult` with the resolution order and, on a failed step, a `Violation`.
    `Violation.reason` includes `"not_activatable"` (fails `is_activatable`) and `"damage_step_restricted"` (an
    `"activate"` step with `"in_damage_step": true` fails `can_activate_during_damage_step`), alongside the
    priority-check violations. Raises `UnsupportedScenarioError` for step kinds it doesn't recognize.
  - `timing.py` — `check_missing_timing()`: a "when"-conditioned effect's activation window is the moment right
    after the event its condition names. At the trigger step itself, whether the window is open depends on the
    checking effect's own spell speed: Spell Speed 1 needs the last event to be a chain link fully `RESOLVED` or a
    non-chain `GAME_ACTION`; Spell Speed 2/3 needs the last event to be the matching link's `ACTIVATED` (quick
    effects can respond to an activation before it resolves). Any other last-event, or any step past trigger_step,
    means timing is missed. Only covers Quick Effects — optional-trigger missing timing is explicitly deferred.

- **`db/`** — psycopg3 + pgvector repos over `schema.sql`, one repo module per table family
  (`cards_repo`, `rulings_repo`, `effects_repo`, `rulebook_repo`). No ORM — raw SQL throughout, intentionally.
  `connection.get_connection()` loads `.env` via `python-dotenv` and calls `register_vector`, tolerating a
  `ProgrammingError` on a brand-new DB where the `vector` extension doesn't exist yet (created by
  `migrate.run_migrations()`, which just executes `schema.sql`).
  - `card_effects_structured` rows are `pending` by default; only `effects_repo.confirm_effect()` (called after
    the review agent passes threshold, or manually) makes a row visible to `get_confirmed_effects()`. **A `pending`
    effect must never be treated as ground truth** — this distinction exists at the repo level specifically so the
    future orchestration layer can't accidentally skip it. Two nullable columns, `damage_step_category` (CHECK
    constrained to `'atk_def_alter'`/`'negates_activation'`/`'explicit_permission'`/`'card_moved_trigger'`/`NULL`)
    and `usage_limit_text`, round out the row; `get_confirmed_effects()` (returns all confirmed effect rows for a
    card, not just one) and `insert_pending_effect()` both read/write them.
  - `bullet_categories` is a reference table mirroring the "Bullet Category Legend" document (13 rows, `A1`
    through `Z`: `code` PK, `name`, `description`, nullable `note`) describing how a card's bulleted effect list
    behaves. Unlike every other table, its rows are seeded by `schema.sql` itself via `INSERT ... ON CONFLICT
    (code) DO UPDATE`, so `run_migrations()` both creates and refreshes them — edit a definition there, not in a
    seed script. Nothing references it yet (no FK from `cards`/`card_effects_structured`).
    `bullet_categories_repo.get_all_bullet_categories()` returns them `ORDER BY code` (which matches the legend's
    order); `get_bullet_category(code)` returns one or `None`.
  - Errata is never overwritten: `insert_errata_version()` adds a new `card_errata_versions` row and flips
    `cards.has_errata`; the original `card_text` stays as originally ingested.
  - `cards.ygoprodeck_id` is `NOT NULL` (always available from the source API); `ygoresources_id` is nullable
    since that API's shape is still unverified. `get_card_by_ygoprodeck_id` / `get_card_by_ygoresources_id` exist
    to reconcile the two id spaces once `ygoresources_id` starts being populated.
  - `cards.race` is nullable TEXT, CHECK-constrained to the closed 33-value enum YGOPRODeck's API itself accepts
    (7 Spell/Trap subtypes — `Normal`/`Field`/`Equip`/`Continuous`/`Quick-Play`/`Ritual`/`Counter` — plus the 26
    monster Types — `Dragon`/`Zombie`/`Spellcaster`/etc.). It mirrors YGOPRODeck's `race` field verbatim, which is
    a *different* piece of information from `card_type` (YGOPRODeck's `type` field): for Spell/Trap cards, `type`
    is always the generic `"Spell Card"`/`"Trap Card"` and the real subtype lives only in `race` — `seed.py` used
    to read `type` alone and silently lose it entirely (e.g. a Quick-Play Spell or Counter Trap would classify as
    Spell Speed 1, the wrong answer). For monsters, `race` is the elemental Type (Dragon, Zombie, ...); monster
    *subtype* (Tuner, Spirit, Pendulum, ...) is unaffected by this — YGOPRODeck already folds that into `type`
    itself as one of a closed set of ~29 precomposed strings (e.g. `"Pendulum Tuner Effect Monster"`), so nothing
    was lost there and `race` is simply unused by `classify_effect_type`/`spell_speed_for` for monsters.

- **`effect_parser/`** — code-based PSCT grammar parser plus an LLM-scored confidence review step:
  - `parser.py` — `parse_psct()` splits `Condition : Cost/Target ; Effect` on the first `:` and first `;`.
    Cost/targeting splitting is two-tier: first look for a PSCT connector (`and if you do` > `then` > `also` >
    `and`, checked longest-first) and decide which side is the targeting clause by whether it contains "target";
    if no connector matches, fall back to locating the bare word "target" and checking for a cost keyword
    (banish/discard/pay/send/tribute/remove/reveal/shuffle) before it. A bare "and" is genuinely ambiguous in PSCT
    (it can separate cost from target, or join two things in one targeting clause) — the parser doesn't try to
    fully resolve this; that's what the review agent exists to catch.
    `classify_effect_type(card_text, *, card_type, race=None)` takes the real `card_type` string (not just an
    `is_monster` bool) and checks, in order: `(Quick Effect)` substring → QUICK/QUICK_LIKE; no `:` and no `;`
    anywhere → CONDITION (if "you can only") or CONTINUOUS; starts with "if "/"when " → TRIGGER/TRIGGER_LIKE; the
    pre-colon condition segment names "damage step"/"damage calculation" *and* contains a ", if "/", when " clause
    (a Trigger condition that leads with a timing phrase instead of starting with "if"/"when" directly — e.g.
    Borreload Dragon: "At the start of the Damage Step, if this card attacks...") → TRIGGER/TRIGGER_LIKE
    (deliberately narrow: a bare "comma + if" anywhere would wrongly reclassify e.g. Called by the Grave's "During
    either player's turn, if..." condition, which must stay QUICK_LIKE); otherwise IGNITION for monsters, or for
    spells/traps QUICK_LIKE if `race == "Quick-Play"` or `card_type` contains "Trap" (all Traps are inherently
    Spell Speed 2 by game rule regardless of subtype, so a plain substring match is enough there and doesn't need
    `race`) else EFFECT. `race` is the same YGOPRODeck field described under `spell_speed_for()` above and
    `cards.race` below — unused for monsters, whose `card_type` string already encodes every subtype.
    `classify_damage_step_category(effect_text, *, activation_condition=None, effect_type=None)` returns
    `"negates_activation"`, `"atk_def_alter"`, `"explicit_permission"`, `"card_moved_trigger"`, or `None`.
    `negates_activation`/`atk_def_alter` are checked first (in that order, since "negate the activation" is the
    more specific phrase) against `effect_text` — the resolution clause, where a negation or ATK/DEF change is
    actually described. The negation pattern requires the word "activation" specifically (`negate\w* (the|its|
    that|this) activation`), not just "effect(s)" — negating an effect and negating an activation are different
    game concepts. The ATK/DEF-alter pattern requires a change-indicating verb (becomes/gains/loses/increases/
    decreases/halved/doubled) within a short distance of an ATK/DEF token, not just a bare mention/comparison, so
    text like "if that monster's ATK is higher than 1000" does not falsely classify as an alteration.
    `explicit_permission`/`card_moved_trigger` are checked against `activation_condition` instead (that's where
    PSCT puts a trigger's condition), and only when `effect_type` is TRIGGER/TRIGGER_LIKE/QUICK/QUICK_LIKE:
    `explicit_permission` when the condition names "damage step" or "damage calculation" directly (the two are
    treated as equivalent); `card_moved_trigger` when the condition's subject is the card's own self ("this
    card") undergoing a zone-change verb (destroyed/banished/sent/returned/summoned/flipped/tributed) — e.g. "if
    this card is destroyed by battle" or "if this card is Special Summoned". A condition about some *other* card
    moving (e.g. "if a Salamangreat monster... is sent to the GY") is deliberately never matched — real cards
    carve such non-self conditions out of the Damage Step explicitly and inconsistently, so guessing would be
    wrong more often than not. Speaking of which: an explicit carve-out in the condition itself (e.g. "except
    during the Damage Step") is checked first and overrides every other category, full stop.
    `extract_usage_limit_text(card_text)` pulls a
    trailing "You can only ... per turn." restriction sentence independent of `parse_psct`'s Condition/Cost/Effect
    split, since that clause sits outside all three. Both return `None` when their pattern isn't found, rather
    than guessing; both feed the `damage_step_category`/`usage_limit_text` columns in `db/`.
  - `review_agent.py` — `review_parsed_effect()` sends the raw text + parsed fields to an `LLMClient`, expects a
    bare `0.0`–`1.0` confidence string back, and returns `auto_confirmed = confidence >= threshold` (default
    `DEFAULT_CONFIDENCE_THRESHOLD = 0.9`). Takes an optional `damage_step_category` parameter, included in the
    review prompt alongside the other parsed fields when present.

- **`embeddings/` and `llm/`** — thin `Protocol` interfaces (`EmbeddingClient.embed`, `LLMClient.complete`).
  `embeddings/` has `MockEmbeddingClient` (deterministic SHA256-derived 384-dim vectors),
  `OpenAIEmbeddingClient` (real provider, `dimensions=384` truncation to match the pgvector schema — see
  `docs/superpowers/specs/2026-08-20-provider-wiring-design.md`), constructed by `entrypoint.py` only, and
  `OllamaEmbeddingClient` — a local client via Ollama's `/api/embeddings` endpoint, $0 cost, no API key,
  defaulting to the `all-minilm` model, which natively outputs 384-dim vectors so it matches the pgvector
  schema without any truncation or migration. `llm/` has `MockLLMClient` (FIFO `queue_response()`/`complete()`,
  raises `AssertionError` on an empty queue), `OpenRouterLLMClient` (hosted, pinned to a specific free model —
  see `docs/superpowers/specs/2026-08-20-openrouter-llm-client-design.md` — kept in the codebase but no longer
  the default hosted wiring), `AnthropicLLMClient` — a real `claude-sonnet-5` client via the official `anthropic`
  SDK, constructed by both `__main__.py` and `entrypoint.py` (`ANTHROPIC_API_KEY`) — and `OllamaLLMClient` — a
  local Qwen3-8B client via Ollama's HTTP API, $0 cost, no API key, still constructed directly by real-Ollama
  tests/scripts (`OLLAMA_MODEL` / `OLLAMA_BASE_URL` env vars) but no longer part of any default wiring.
  `AnthropicLLMClient` and `OllamaEmbeddingClient` are the ones `python -m aijudge` / `aijudge.__main__.main()`
  construct by default (`ANTHROPIC_API_KEY` for the former; `OLLAMA_BASE_URL` / `OLLAMA_EMBEDDING_MODEL` env vars,
  default `http://localhost:11434` / `all-minilm`, for the latter). `OllamaLLMClient` disables Qwen's thinking mode
  and strips any `<think>...</think>` block defensively, since `run_loop`'s protocol parses an exact
  `TOOL:`/`FINAL:` text format that a reasoning preamble would break. `AnthropicLLMClient` doesn't need this:
  thinking blocks arrive as separate `content` entries from the Messages API rather than inline in the text, so
  there's nothing to strip.

- **`call_log.py`** — cross-cutting LLM call logging, kept separate from `logging`/stdlib debug output so calls
  and their failure reasons stay queryable after the fact. `CallLogger` appends one JSON object per line to a
  file (`AIJUDGE_LOG_FILE` env var, default `logs/aijudge.jsonl`; parent dirs created on first write, path
  gitignored), stamping each record with a UTC timestamp. `LoggingLLMClient` wraps any `LLMClient` and logs every
  `complete()` call's full prompt/system/response (or, on exception, the exception type/message) plus duration,
  then returns/re-raises exactly what the wrapped client did — so callers that catch specific exceptions (e.g.
  `api/app.py`'s `requests.exceptions.ConnectionError` → 503 mapping) are unaffected. `call_site(name)` is a
  `contextvars`-backed context manager that tags whatever `LoggingLLMClient` calls happen inside it (`"loop"`,
  `"verify"`, `"clarify"`, `"extraction"`, `"review_agent"`) without changing the `LLMClient` protocol or any
  `complete()` call's arguments — every real call site (`orchestration/loop.py`, `verify.py`, `extraction.py`,
  `effect_parser/review_agent.py`, and the clarification calls in `cli.py`/`api/app.py`) wraps its own
  `llm_client.complete(...)` in one. `log_event(call_logger, *, site, event, reason=None, **context)` is the
  sibling for orchestration-level *why* (not a raw LLM call): `run_loop` calls it at each of its existing
  decision branches (`malformed_response`, `tool_error`, `verification_failed`, `escalate`, `not_supported`,
  `off_topic`, `answered`), alongside its pre-existing `logger.debug` calls rather than replacing them. No-ops
  silently when `call_logger` is `None`, which every caller (`run_loop`, `run_cli`, `create_app`) defaults it to,
  so logging stays fully opt-in. `__main__.py`, `entrypoint.py`, and `api/__main__.py` are the only places that
  construct a real `CallLogger` and wrap the real LLM client in `LoggingLLMClient`, once, at startup.

- **`orchestration/`** — the agentic tool-use loop that turns a user question into an answer, escalation, or
  "not supported":
  - `protocol.py` — `build_system_prompt()` describes the `TOOL: <name> {json}` / `FINAL: <text>||CITES:
    id1, id2||` / `REFUSE: <reason>` response format the LLM must follow, and pins the assistant's identity as a
    Yu-Gi-Oh! TCG rules adjudicator: it's told to answer only Yu-Gi-Oh! rules/card-interaction questions and to
    emit `REFUSE:` instead of guessing on anything else. `parse_response()` parses one into a `ToolCall`,
    `FinalAnswer`, or `Refusal`, raising `ProtocolError` on anything else (missing prefix, bad JSON, unknown tool,
    malformed or missing `||CITES: ...||` trailer). This system prompt is also passed to the `clarify.py`
    pre-loop LLM call (see below) so the scope pin holds from the very first LLM turn, not just inside `run_loop`.
    `build_answering_system_prompt()` is a second, narrower system prompt used only for the final answering turn
    (both `cli.py` and `api/app.py` call `run_loop` with `tools={}` and this prompt uniformly, never
    `build_system_prompt()`/a real tool dispatch, for that turn): it tells the model it has already been given
    complete, verified KNOWN FACTS and has **no tools** this turn, explicitly forbids attempting a `TOOL:` line,
    instructs it to report (never guess) a card listed under `card_effect_pipeline.py`'s LOOKUP FAILURES block,
    and to treat its own memory of a card's effect as unreliable and never state it as fact. This is the mechanism
    behind the branch's core fix: previously the LLM could optionally skip `lookup_card` and answer from memory,
    ungrounded and uncited, scoring a perfect confidence of `1.0`; now the final turn is deterministically grounded
    (via `preflight.py`/`card_effect_pipeline.py`'s KNOWN FACTS injected into `clarification_context`) or has no
    tool available to fabricate a citation with in the first place.
  - `tools.py` — `build_tool_dispatch()` wires the DB/embedding-backed tool implementations
    (`lookup_card`, `get_rulings`, `search_rulebook`, `resolve_chain`) into the `{name: callable}` dict the loop
    dispatches against. `resolve_chain` delegates to `rules_engine.resolve.resolve_chain`, which raises
    `UnsupportedScenarioError` for step kinds it doesn't recognize.
  - `confidence.py` — `compute_confidence()`: starts at `1.0`, returns `0.0` outright if the answer cites an id
    no tool result actually surfaced (`known_ids`), otherwise subtracts `RETRIEVAL_GAP_PENALTY` (0.3) if any
    `get_rulings`/`search_rulebook` call came back empty and `MISSING_STRUCTURED_EFFECT_PENALTY` (0.2) if a
    looked-up card had no `confirmed_effects`. `update_signals()` accumulates these signals per tool call, and on
    a `lookup_card` hit with non-empty `confirmed_effects` also populates `SignalState.structured_effects` --
    keyed under both the internal id and, when present, the passcode alias (same dual-keying as
    `citation_index`) -- with the card's full `confirmed_effects` list (the whole
    activation_condition/cost/targeting/effect breakdown, not just `effect` text). `verify.py`'s grounding gate
    (below) reads this directly rather than re-fetching.
  - `loop.py` — `run_loop()`: repeatedly calls the LLM, dispatches `ToolCall`s and folds results back into the
    conversation, and on a `FinalAnswer` scores it via `compute_confidence()` against `threshold` (default
    `DEFAULT_CONFIDENCE_THRESHOLD = 0.9`) — below threshold escalates instead of answering. A `Refusal` short-
    circuits immediately to `LoopResult(kind="off_topic", ...)`, bypassing confidence scoring entirely -- this is
    the enforcement half of the scope pin: without it, an off-topic question the LLM answers anyway (no tool
    calls, no citations) would score a perfect `1.0` and sail through as a normal answer, since
    `compute_confidence` has no signal that would ever penalize it. Malformed LLM responses or tool-arg errors
    (`KeyError`/`ValueError`/`TypeError`) get fed back as `ERROR:` context, capped at `MAX_MALFORMED_RETRIES = 3`;
    total tool calls are capped at `MAX_TOOL_CALLS = 10`. Either cap, or an `UnsupportedScenarioError` from
    `resolve_chain`, ends the loop with `kind="not_supported"` rather than looping forever or guessing. Once a
    `FinalAnswer` clears the confidence gate, a second, independent gate runs: `verify_structured_grounding()`
    (from `verify.py`) checks, via a second LLM call, whether the answer's prose actually matches the stored
    effect breakdown of any structured-effect card it cites. A mismatch is fed back into `conversation` as a
    `VERIFICATION_FAILED` message -- naming each mismatched card by name (via `state.citation_index`, not its raw
    citation id) with its stored breakdown, plus the prior draft text (`parsed.text`) so the model can see what it
    got wrong -- and the loop retries, bounded by `MAX_VERIFICATION_RETRIES = 2`, a separate budget from
    `MAX_MALFORMED_RETRIES` since these are different failure classes (protocol/tool-argument errors vs. content
    correctness). A redraft that evades the check by citing none of the cards a prior turn was flagged for (e.g.
    dropping the citation instead of fixing the prose) is itself treated as another verification failure under
    the same counter/budget -- not a free pass to a silently ungrounded answer. Exceeding the retry budget
    escalates (`kind="escalate"`) exactly like a low confidence score does.
  - `verify.py` — the structured-grounding verification gate `loop.py` calls after the confidence check passes.
    `VERIFIER_SYSTEM_PROMPT` frames a narrow strict-fact-checker role, deliberately not
    `protocol.build_system_prompt()`, which would pull in tool-use/persona instructions irrelevant to this
    narrower task. `build_verification_prompt(answer_text, structured_effects)` renders every matched effect's
    full stored breakdown -- `activation_condition`/`cost`/`targeting`/`effect`, each omitted when `None`,
    mirroring `preflight.build_known_facts_context`'s conditional-append style -- not just `effect` alone, which
    can't distinguish e.g. a targeting swap (the word distinguishing "Effect Monster" from "spell or trap card" in
    the spec's own motivating example lives in `targeting`; see the spec doc's Amendments section) -- followed by
    the drafted answer fenced between explicit `BEGIN`/`END DRAFTED ANSWER` markers so answer text (downstream of
    a user-controlled question) has less room to be read as instructions. `parse_verification_response(response)`
    tolerates this project's default Qwen3-8B-via-Ollama formatting sloppiness (the same class of issue commits
    `7b95e2c`/`b2dce55` salvage elsewhere in this layer): it strips markdown/whitespace/punctuation and accepts a
    leading bare `YES` token, but rejects anything whose leading token isn't `YES` or that also contains a
    standalone `NO`. `verify_structured_grounding(answer_text, cited_ids, state, llm_client)` collects
    `state.structured_effects` for every cited id (deduped by list identity so a card cited under both its
    internal id and passcode alias isn't double-counted), returns `VerificationResult(ok=True)` with **zero LLM
    calls** if nothing matched, otherwise makes exactly one LLM call bundling all matched cards' effects and
    returns `VerificationResult(ok, mismatches)` -- each mismatch carries its `card_id` plus the full
    `activation_condition`/`cost`/`targeting`/`effect_text` breakdown (not just bare text), for `loop.py`'s
    feedback-message construction.
  - `clarify.py` — a pre-loop pass: `build_clarification_prompt()` asks the LLM whether the question is
    ambiguous or hinges on an unobservable continuous/lingering effect; `parse_clarification_response()` turns
    `CLARIFY:`/`CONTINUOUS_CHECK:` lines into `ClarificationItem`s (or an empty list on `PROCEED`), deduping
    lines with identical `(kind, text)` so an LLM that restates the same clarifying question twice doesn't
    surface it to the user twice; `format_clarification_context()` folds the user's answers back into context
    passed to `run_loop`. Both `cli.py` and `api/app.py` pass `protocol.build_system_prompt()` as this call's
    `system` argument (previously it had none), so the model isn't left to infer from a user-turn mention alone
    that it's a Yu-Gi-Oh! assistant.
    `ClarificationItem.kind` has a third value, `"disambiguate_card"` (alongside `"clarify"`/`"continuous_check"`),
    used when `cli.py` detects the user's question plausibly matches more than one known card and needs to know
    which one before it can render `preflight.py`'s KNOWN FACTS block.
  - `preflight.py` — deterministic pre-loop card grounding, independent of the clarification pass above.
    `find_mentioned_card_names(question, known_names)` matches an exact case-insensitive word-boundary substring
    first, falling back to a `difflib`-based fuzzy comparison (`_FUZZY_CUTOFF = 0.75`) against every equal-length
    word-window of the question, so a slightly misspelled or differently-cased name (e.g. "effect veiler") still
    matches. `find_matched_cards(question)` runs that against every known card name and returns the full card
    dict for each match. `build_known_facts_context(card)` renders a "KNOWN FACTS (deterministic -- do not
    contradict)" block with one line per confirmed effect, each including effect type, spell speed, `is_activatable`,
    and when non-`None`, activation condition, damage step category, usage limit text, and damage-step legality
    (computed via `rules_engine.models.is_activatable()` and `rules_engine.priority.can_activate_during_damage_step()`,
    reused unchanged) — returns `""` if the card has no confirmed effects, so callers fall back to unaided LLM reasoning.
    The block's header also states the card's `card_type` and full `card_text` verbatim (not just per-effect
    facts), since the restricted answering turn (see `protocol.build_answering_system_prompt()` below) has no
    `lookup_card` tool to fall back on for that -- omitting them was a confirmed source of fabrication (a real
    Tuner Monster described as a "Quick-Effect spell card") caught in manual testing.
  - `extraction.py` — `extract_card_names(question, *, llm_client)` asks the LLM (via the narrow
    `EXTRACTION_SYSTEM_PROMPT`, deliberately not `protocol.build_system_prompt()`) to list every card name a
    question references, one per line, or the literal `NONE`. `parse_extraction_response()` strips bullet/number
    prefixes and quoting per line and returns `[]` for `NONE` or blank input. This is the entry point for the
    mandatory pipeline below: a question naming a card with 0 local `preflight` matches (e.g. one of the ~13,000+
    real cards outside the hand-picked seed list) still gets a shot at deterministic grounding instead of silently
    falling through to unaided LLM reasoning.
  - `card_resolution.py` — `resolve_named_cards(names, *, llm_client, online_ingest_enabled=True,
    on_ingest_start=None)` takes `extraction.py`'s extracted names and, for each, calls `tools.lookup_card`
    directly (not through `tools.build_tool_dispatch`, which nothing in the restricted answering pathway uses any
    more) and classifies the result into a `CardResolution(name, status, card=None)`: `"ambiguous"` when
    `lookup_card` reports more than one match, `"not_found"` when it reports none, or `"resolved"` with the full
    raw row (re-fetched via `get_card_by_id` -- not `lookup_card`'s own trimmed shape, since
    `build_known_facts_context` needs fields like `race` that only the raw row carries) when exactly one match is
    found. Guards a narrow race where the row backing a just-reported `found: True` id is gone by the time it's
    re-fetched: rather than ever return `status="resolved"` with `card=None` (which would later crash
    `build_known_facts_context`/`build_grounded_result` with an unguarded `TypeError`), it downgrades that case to
    `"not_found"`, which every caller already handles.
  - `card_effect_pipeline.py` — composes the two modules above into the mandatory fallback used whenever
    `preflight.find_matched_cards` finds nothing locally (or a multi-match disambiguation answer doesn't resolve
    to any candidate -- see `cli.py`/`api/` below). `build_pipeline_context(resolutions)` renders one
    `build_known_facts_context` block per resolved `CardResolution` plus, when any name failed to resolve, a
    "LOOKUP FAILURES (deterministic -- report these to the user, do not guess their effects)" block listing each
    by name and status -- so the LLM is told explicitly to report a lookup miss rather than fabricate an answer
    for it. `resolve_card_effect_question(question, *, llm_client, online_ingest_enabled=True,
    on_ingest_start=None)` ties it together into a `PipelineResolution(supported, context="", grounded_cards=[])`:
    `supported=False` (with no context/grounded_cards) if `extraction.py` finds no card names at all, otherwise
    `supported=True` with the rendered context and a `build_grounded_result`-shaped entry per resolved card, ready
    to hand straight to `run_loop(..., clarification_context=resolution.context,
    grounded_cards=resolution.grounded_cards)`.

- **`cli.py`** — `run_cli()`: a REPL (`input_fn`/`print_fn`, plus `find_matched_cards_fn`/`build_known_facts_context_fn`/
  `build_grounded_result_fn`/`resolve_card_effect_question_fn`, defaulting to `preflight.find_matched_cards`/
  `preflight.build_known_facts_context`/`preflight.build_grounded_result`/`card_effect_pipeline.resolve_card_effect_question`,
  are all injectable for testing) that, per question, first runs `find_matched_cards_fn` -- if more than one card
  plausibly matches, it adds a `"disambiguate_card"` clarification item asking the user which one they mean --
  then runs the clarification pass, prompts for answers to any `CLARIFY`/`CONTINUOUS_CHECK`/`disambiguate_card`
  items, resolves the disambiguation answer back to a candidate card via `preflight.find_mentioned_card_names`
  (fuzzy, case-insensitive -- not a bare `==`, so "effect veiler" still resolves to "Effect Veiler"; an
  unresolvable answer prints a one-line notice via `print_fn`). If there were 0 local matches at all, *or* a
  disambiguation answer failed to resolve to any candidate (leaving `grounded_cards` empty -- a gap that used to
  fall through to an ungrounded answer, fixed in the final-review fix wave), it falls back to the mandatory
  `resolve_card_effect_question_fn` pipeline (`card_effect_pipeline.py`, below) instead of proceeding ungrounded;
  an unsupported pipeline result (no card names extracted at all) prints `NOT_SUPPORTED_MESSAGE` and skips the
  question entirely rather than calling `run_loop`. Either way, the resulting `KNOWN FACTS`
  context/`grounded_cards` are folded in ahead of the clarification context, then `run_loop` is called with
  `tools={}` and `system_prompt=protocol.build_answering_system_prompt()` -- never a real tool dispatch --
  and the result is printed. Wired to a real entrypoint by both `__main__.py` (Ollama, default) and
  `entrypoint.py` (OpenRouter/OpenAI, alternate).

- **`api/`** — `create_app(llm_client, embedding_client, *, cors_origins=None, find_matched_cards_fn=None,
  build_known_facts_context_fn=None, build_grounded_result_fn=None, resolve_card_effect_question_fn=None,
  online_ingest_enabled=True) -> FastAPI` wires the same orchestration functions the CLI uses (`preflight.py`
  and, as of this branch, `card_effect_pipeline.resolve_card_effect_question` -- there is no `tools` parameter
  any more; both endpoints call `run_loop` with `tools={}` and `system_prompt=protocol.build_answering_system_prompt()`
  uniformly, and `tools.build_tool_dispatch` is no longer called by this module at all) behind two stateless REST
  endpoints (no server-side session store): `POST /questions` runs preflight card-matching and the clarification
  pass, and either returns `{"status": "needs_clarification", ...}` or, if no clarification is needed, resolves
  `KNOWN FACTS` (falling back to `resolve_card_effect_question_fn` when there were 0 local matches) and runs
  `run_loop` directly; `POST /questions/answer` takes the client's echoed-back question/items/answers, rebuilds
  `ClarificationItem`s, resolves the disambiguation answer (if any) via the module-private
  `_resolve_preflight_card()` helper, and runs `run_loop` with the resulting context. Preflight mirrors `cli.py`'s
  logic (`find_matched_cards`, `build_known_facts_context`, both from `orchestration/preflight.py`, injectable the
  same way the other functions are) but is re-run from scratch on *every* call, since the API has no in-process
  session to carry a resolved card across the two endpoints the way the CLI's single request-handling loop does: a
  single card match folds its `KNOWN FACTS` context in immediately; more than one match adds a
  `"disambiguate_card"` item to the `needs_clarification` response (alongside any LLM-raised
  `CLARIFY`/`CONTINUOUS_CHECK` items) and only resolves to `KNOWN FACTS` once `/questions/answer` sees that
  item's answer echoed back, fuzzy-matched via `find_mentioned_card_names` (same case-insensitive,
  misspelling-tolerant matching the CLI uses). If there were 0 local matches, *or* (in `post_answer`) a
  disambiguation answer failed to resolve to any candidate (leaving `grounded_cards` empty), `post_answer` falls
  back to the mandatory `resolve_card_effect_question_fn` pipeline instead of proceeding ungrounded -- the same
  fix as `cli.py`'s, since the API has no `print_fn` equivalent to surface a notice and would otherwise ship an
  unlabeled, unverified answer straight through. An unsupported pipeline result there returns `{"status":
  "not_supported", ...}`. Both endpoints return a `ResultResponse`/`NeedsClarificationResponse` (Pydantic models
  in `schemas.py`) — `citations` are always `{"label", "text"}` pairs; the internal
  `card:<id>`/`ruling:<id>`/`chunk:<id>` ids `LoopResult.citations` carries (see `orchestration/` below) never
  reach the response body. Backend connection errors (`requests.exceptions.ConnectionError`,
  `psycopg.OperationalError`) become a generic `503`, any other unhandled exception a generic `500` — both log the
  real exception server-side via `logger.exception(..., exc_info=exc)` (exception handlers run in Starlette's
  threadpool, where bare `logger.exception()` without `exc_info=exc` logs nothing) but never leak exception text
  to the client. `__main__.py` wires real `OllamaLLMClient`/`OllamaEmbeddingClient` and runs `uvicorn`
  (`AIJUDGE_API_HOST`/`AIJUDGE_API_PORT`/`AIJUDGE_API_CORS_ORIGINS` env vars). See
  `docs/superpowers/specs/2026-08-27-api-layer-design.md` for the original design (predates the
  `resolve_card_effect_question_fn` fallback and the `tools`-parameter removal, both from this branch).

- **`ingestion/`** — `ygoprodeck_client.fetch_card()` and `ygoresources_client.fetch_rulings()` pull only the
  fields this project uses (not a full API mirror). `seed.py` ties it together: `seed_card()` fetches card +
  rulings, calls `effect_parser.clause_splitter.resolve_effect_clauses()` to split the card text into individual
  effect clauses (gated by two independent safety checks: a deterministic verbatim-reconstruction check and an
  LLM-scored split-quality check; a failed split falls back to treating the whole card as one effect), runs each
  resulting effect through the parser and review agent, inserts one `card_effects_structured` row per effect,
  and auto-confirms if the review score clears threshold. `run_seed()` iterates `HAND_PICKED_CARDS` — despite the
  name, this list is now a random sample (Digitron, Shafu the Wheeled Mayakashi, Cyber Angel Benten, Masked HERO
  Anki, Crystron Quariongandrax, Super Quantal Mech Beast Magnaliger, Powercode Talker, Amazoness Call, The Prime
  Monarch, Cynet Conflict), one card drawn at random per major card category (all 7 monster summoning mechanics,
  Quick-Play Spell, Continuous Trap, Counter Trap) from real cards first printed 2015-01-01 through 2025-12-31 via
  YGOPRODeck's `cardinfo.php` date-range filter, replacing an earlier hand-curated list — this is a one-off seed
  script, not a scheduled ingestion pipeline (out of scope for this slice). The clause splitter correctly
  decomposes real multi-effect cards into multiple confirmed effect rows (one per real effect) in most cases —
  e.g. Cyber Angel Benten and Shafu each split cleanly — unless one of the two safety gates fails, in which case it
  falls back to single-row behavior; this broader, randomly-sourced sample also surfaced genuine parser gaps
  (Masked HERO Anki's entire card text misclassified as Card Material losing both real effects, an "and/or"
  cost/targeting mis-split on Crystron Quariongandrax, and The Prime Monarch's second effect landing inside
  `usage_limit_text` instead of its own row) that the narrower hand-picked set never exercised — none fixed yet.
  `effect_parser/clause_splitter.py` exports `split_effect_clauses()`,
  `score_split_confidence()`, and `resolve_effect_clauses()`.
  `rulebook_seed.py` — `seed_rulebook_file(path, embedding_client=..., source=...)` chunks a rulebook text file
  (via `rulebook_loader.load_rulebook_file`) and embeds+inserts each chunk into `rulebook_chunks`. It deletes any
  existing chunks for that `source` first (`rulebook_repo.delete_chunks_by_source()`), so re-running it against
  the same source re-seeds rather than duplicates — expected to be re-run whenever the live rulebook page changes.

## Not yet built

Per the spec's non-goals / deferred list: no missing-timing check for optional trigger effects, no automated
ingestion pipeline beyond the hand-picked seed list, no structured-output protocol for the orchestration loop, no
formal eval harness (an informal `qa_test_cases` table exists in the schema for this, unused so far). Don't assume
these exist when reading code — check before referencing a tool/module that spec sections 4–7 describe but that
isn't under `src/`.

## Development process

TDD: a failing test precedes implementation code for every change, most importantly in the rules engine and
effect parser, where a wrong-but-confident result is the exact failure mode this project exists to avoid.

## Git workflow

Branch off `dev`, not `main`, for new work — worktrees included. `main` only receives merges from `dev` and can
lag significantly behind it (this repo's git host default branch is `main`, so any tooling that bases a new
branch/worktree off "the default branch" will silently pick the wrong, stale base unless told otherwise). Use
`dev` as the base unless the user explicitly asks for a different base branch.

Spec and plan docs (e.g. anything under `docs/superpowers/plans/` or `docs/superpowers/specs/`) are written and
committed directly to `dev`, even if the work producing them happens on a worktree or feature branch — these docs
are reference material for future sessions and should land on `dev` immediately rather than waiting on that
branch's PR to merge. Implementing a plan is a separate step: create a new branch off `dev` (worktrees included,
per above) for the implementation work itself — don't implement directly on `dev`.
