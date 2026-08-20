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

## Explicitly out of scope (not done here)

- `db/` package coverage, including `db/connection.py` remaining untested —
  deferred until DB infra (`docker compose up -d db` + `.env`) is brought up
  as part of a dedicated follow-up.
- Any coverage threshold enforcement (`--cov-fail-under`, CI gate) — belongs
  to the forced-task-per-commit sub-project.
- The forced-task-per-commit mechanism itself — separate brainstorming pass.

## Work log

- Branch: `worktree-test-coverage-backfill` (off `dev`).
- *(filled in after implementation)*
