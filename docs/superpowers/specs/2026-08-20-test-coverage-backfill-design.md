# AIJudge — Test Coverage Backfill

## Purpose

The user asked for two related things: (1) unit tests covering work already
done, and (2) a mechanism that forces a task to exist for every future commit
to `main`. Classified as **two separate sub-projects** (brainstorming skill)
rather than one blurred effort — this document covers only the first. The
forced-task-per-commit enforcement mechanism is a separate, later
brainstorming pass.

Classified as a **bounded** change: the flow being changed (the `pytest`
suite under `tests/`, mirroring `src/aijudge/` module-for-module) already
exists in this repo. No new subsystem, no spec-plan-implement ceremony beyond
this doc, which the user asked to keep as a record of the discussion.

## Starting state

Every module under `src/aijudge/` already has a matching test file — this is
not a from-zero backfill. A line-count comparison (`src` lines vs. matching
`test` lines) surfaced two real gaps and two thin spots:

- `db/connection.py` (22 lines) — **no test file at all**. Owns the
  psycopg + pgvector registration logic, including the "tolerate
  `ProgrammingError` on a brand-new DB where `vector` doesn't exist yet"
  fallback CLAUDE.md calls out.
- `src/aijudge/__main__.py` (4 lines) — no test, but a trivial `python -m`
  shim already covered indirectly by `tests/test_entrypoint.py`'s `main()`
  smoke test.
- `orchestration/tools.py` (71 src / 42 test) and `orchestration/protocol.py`
  (74 src / 44 test) — thinner than siblings relative to size, flagged for
  closer look via real coverage rather than assumed to be gaps.

Line-count ratio was treated as a crude signal only, not a conclusion — it
doesn't show branch/edge-case coverage inside a file that technically has a
test.

## Decisions

**Scope: pure-Python modules only, `db/` deferred.** `tests/db/*` are
`pytest.mark.skipif("DATABASE_URL" not in os.environ)` and, at the time of
this discussion, no `.env` existed and no aijudge Postgres container was
running (`docker ps` showed only an unrelated `node:24-slim` container). Two
options were raised: bring the DB up now for full-repo coverage including
`connection.py`, or scope this pass to pure-Python modules
(`rules_engine/`, `effect_parser/`, `llm/`, `embeddings/`, `orchestration/`,
`cli.py`, `entrypoint.py`, non-DB `ingestion/`) and defer `db/` — including
the untested `connection.py` — to a follow-up once DB infra is part of the
plan. The user chose the deferred option. This means `db/connection.py`
remains untested after this pass; that is a known, explicit gap, not an
oversight.

**Tooling: real coverage numbers, not eyeballing.** Add `pytest-cov` to the
`dev` extra in `pyproject.toml`. Run
`pytest --cov=aijudge --cov-report=term-missing --ignore=tests/db` to get a
real per-line/branch report. No `--cov-fail-under` threshold is wired into
`pytest` config or CI as part of this pass — enforcing a coverage floor going
forward is an enforcement-mechanism decision that belongs to the
forced-task-per-commit sub-project, not this backfill.

**Bar for "done": tiered by accuracy-criticality, not a flat number.**
CLAUDE.md's stated failure mode is a "wrong-but-confident result," so the bar
is tiered rather than uniform:
- **Accuracy-critical** — `rules_engine/*`, `effect_parser/*`,
  `orchestration/confidence.py`, `orchestration/protocol.py`. Push for full
  branch coverage; every missing branch here gets a real test case. A test
  against already-existing code either confirms correctness or surfaces a
  latent bug — both are useful outcomes, even though this isn't classic
  red-green TDD (the implementation predates the test).
- **Everything else in scope** — `cli.py`, `entrypoint.py`, `llm/*`,
  `embeddings/*`, `orchestration/loop.py`, `clarify.py`, `tools.py`, non-DB
  `ingestion/*`. Pragmatic: close gaps the coverage report actually shows
  (real untested error paths, edge cases), don't pad trivial lines just to
  move a percentage.

## Process

1. Add `pytest-cov`, run the coverage report against pure-Python modules.
2. For each accuracy-critical module, write tests for every missing branch.
3. For other in-scope modules, triage the report and add tests only for
   genuine gaps.
4. Re-run the full `pytest` suite to confirm everything green.
5. Report before/after coverage numbers in this doc's work log.

## What was built

- **`pyproject.toml`** — added `pytest-cov>=5.0` to the `dev` extra.
- **`tests/orchestration/test_protocol.py`** — two new cases:
  a `TOOL:` line with no space (so no JSON part at all, e.g. `"TOOL:
  lookup_card"`) hits the `ValueError` branch on `remainder.split(" ", 1)`;
  a `FINAL:` line whose `||CITES:` trailer is present but never closed with
  `||` hits the trailer-format check. Both were real untested error paths in
  the malformed-response handling the orchestration loop depends on to avoid
  looping forever.
- **`tests/effect_parser/test_parser.py`** — two new cases in
  `_split_cost_and_targeting`/`_split_on_target_keyword`: a PSCT connector
  present but neither side mentioning "target" (falls through to "whole
  segment is cost, no targeting"); a cost keyword preceding "target" with
  *no* connector word in the segment at all, which is a distinct code path
  from the already-tested "cost keyword + connector" case.
- **`tests/test_cli.py`** — blank/whitespace-only input now has a test
  proving the REPL loop `continue`s without calling the LLM (asserted by
  using a `MockLLMClient` with an empty response queue — if the blank-input
  branch didn't short-circuit, the mock would raise on the unexpected call).

All four accuracy-critical modules (`rules_engine/*`, `effect_parser/*`,
`orchestration/confidence.py`, `orchestration/protocol.py`) are now at
100% branch coverage. Every other in-scope module is also at 100% except
two trivial `if __name__ == "__main__": main()` guard lines
(`entrypoint.py:33`, `__main__.py`) — not meaningfully unit-testable without
spawning a subprocess, and already covered only by manual smoke test per
the precedent `2026-08-20-provider-wiring-design.md` set for the same
lines.

## Hiccup: worktree branched from a stale `main`

The isolated worktree for this work was created from `origin/main`, which
at the time was still at the pre-PR#3 commit (`a684aa7`) — missing
`entrypoint.py`, `__main__.py`, `embeddings/openai_client.py`, and their
tests, all of which exist on `dev` (tip `ce32965`, after PR#3 merged). This
surfaced as `entrypoint.py` and `__main__.py` being entirely absent from
the coverage report. Fixed with `git merge dev` inside the worktree (a
clean fast-forward-shaped merge, no conflicts, since the worktree's only
commit was a new file) before continuing. Worth remembering for future
worktree-isolated tasks in this repo: verify the worktree's base actually
matches `dev`'s current tip before trusting a coverage/gap report against
it.

## Explicitly out of scope (not done here)

- `db/` package coverage, including `db/connection.py` remaining untested —
  deferred until DB infra (`docker compose up -d db` + `.env`) is brought up
  as part of a dedicated follow-up.
- Any coverage threshold enforcement (`--cov-fail-under`, CI gate) — belongs
  to the forced-task-per-commit sub-project.
- The forced-task-per-commit mechanism itself — separate brainstorming pass.

## Work log

- Branch: `worktree-test-coverage-backfill`. Initially cut from a stale
  `origin/main`; merged `dev` in partway through (see hiccup note above),
  so it now sits on top of `dev`'s tip (`ce32965`) plus this work.
- Baseline (before this pass): `pytest -q` → 115 passed, 29 skipped.
- Baseline coverage on pure-Python modules
  (`pytest --ignore=tests/db --cov=aijudge`): 80% overall
  (636 statements, 128 missed); real gaps in `orchestration/protocol.py`
  (93%), `effect_parser/parser.py` (96%), `cli.py` (96%).
- After backfill: `pytest -q` → 128 passed, 29 skipped (all 29 skips are
  DB-dependent tests — `tests/db/*`, `tests/ingestion/test_seed.py`,
  `tests/orchestration/test_tools_db.py` — none touched, as scoped).
- Final coverage on pure-Python modules: 81% overall (674 statements, 125
  missed) — the total statement count and percentage barely moved because
  the deferred DB-backed modules (`db/*`, `ingestion/seed.py`, and the
  DB-backed half of `orchestration/tools.py`) dominate the denominator; the
  real signal is that every accuracy-critical module is now at 100% branch
  coverage, up from 93-100%.
- 5 new test cases added across 3 files; 0 existing tests modified; 0 bugs
  found (every new test against existing code passed on the first run,
  confirming correctness rather than surfacing a defect).
