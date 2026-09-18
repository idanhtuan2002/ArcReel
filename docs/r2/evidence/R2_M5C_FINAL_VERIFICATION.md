# R2-M5C Final Verification (Checkpoint M5C-4)

## Status: ACCEPTED BY HUMAN OVERRIDE — no Codex review

**This is not a Codex-approved verdict.** The plan
(`docs/superpowers/plans/2026-09-09-r2-m5c-narrative-lifecycle.md`, Task 32 Step 5)
specifies that Codex reviews the whole M5C surface and, after an `APPROVED` verdict,
writes this file. That review did not happen: Codex returned
`"You've hit your usage limit... try again at Sep 19th, 2026 4:33 PM"` on 2026-09-15
(job `task-mu22p9cv-t4a03r`). The operator (Human Showrunner, `human:anhtuan`)
explicitly decided on 2026-09-15 to waive the Codex review requirement rather than
wait until 2026-09-19, and accept the evidence below — including a Claude
self-review substitute — as sufficient to close M5C-4 and unblock M6.

This mirrors the precedent already accepted for M5C-2 and M5C-3, whose own Codex
reviews also never completed (Codex hit the same usage limit both times) and whose
checkpoints were closed on the operator's explicit decision to proceed anyway. Both
of those formal Codex sign-offs remain outstanding; so does this one. If Codex
capacity returns, re-running the same review this file describes is still valuable
and may be done retroactively.

## Frozen head and lineage

- `M5C_FINAL_VERIFIED_HEAD`: `8b1959e7ae882716a9d531f459d8289c83968fbb`
- Worktree: `/home/anhtuan/content-production-os-m5c`, branch `feat/r2-m5c-narrative-lifecycle`
- `M5C_3_VERIFIED_HEAD` (checkpoint M5C-3 base): `dd40613a`
- Commits since M5C-3: Tasks 27-31 (handoff admission, integrity checker completion,
  combined acceptance corpus) + this checkpoint's own fixes:
  `54247033` (3 pre-existing test-fixture Postgres-FK bugs fixed, no production code
  touched), `09f24d3c` + `8b1959e7` (added the missing `m5c4` scope-verification
  checkpoint entry, then tightened it and the FK fix per self-review).
- Working tree: clean at `8b1959e7` (confirmed via `git status --short`).

## PostgreSQL identity

- Docker container `m5c-pg18-test` at `127.0.0.1:54329`
- `SELECT version()`: `PostgreSQL 18.6 (Debian 18.6-1.pgdg13+2) on x86_64-pc-linux-gnu,
  compiled by gcc (Debian 14.2.0-19) 14.2.0, 64-bit`
- `current_database()` / `current_user`: `r2_m5c_isolated` / `m5c_test`
- Matches `docs/r2/evidence/R2_M5C_STARTING_STATE.json`'s pinned identity exactly.

## Gate results (Task 32 Step 2, re-run at `8b1959e7`)

| Command | Result |
|---|---|
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 1366 files already formatted |
| `uv run basedpyright --warnings` | 0 errors, 0 warnings, 0 notes |
| `uv run lint-imports` | 17 kept, 0 broken |
| `uv run deptry lib server alembic scripts tests r2` | No dependency issues found |
| `PYTHONHASHSEED=0 uv run python -m pytest -n 4 --dist loadfile` | 13351 passed, 11 skipped |
| `uv run python scripts/audit_tests.py --check` | 0 violations |
| `DATABASE_URL=$POSTGRES_TEST_URL uv run python -m pytest -m "uses_db and not sqlite_only"` | 814 passed, 0 failed |
| `alembic upgrade head && downgrade 5b7c4a0e0001 && upgrade head` (against `POSTGRES_TEST_URL`) | clean round-trip |
| `verify_m5c_scope.py --base dd40613a --head 8b1959e7 --phase impl --checkpoint m5c4` | exit 0 |
| `git diff --check ab9cbae0..8b1959e7` | clean |

The 11 SQLite skips are all environment-conditional by design (8 are
`PostgreSQL only` races/isolation checks that run and pass under the Postgres run
above; 1 is a macOS-only mutmut check; 1 is an unrelated drama-script-generator
skip; 1 is an SQLite-FK-disabled skip) — zero are M5C-required skips left
unexercised on the dialect where they're required.

## Acceptance-counter block (spec §16.9)

`tests/integration/r2/test_m5c_acceptance.py` (Task 31's capstone corpus) reconfirmed
fresh at `8b1959e7`: 30/30 §16.8 adversarial-mutation rows plus 19 named scenario
tests covering every §16.9 bullet (v1 byte-for-byte replay, mixed v1/v2 plan,
directional relationship at exact instants, thread lifecycle across a story-time
jump, accepted vs. unaccepted payoff proof, no-POV `AUTHOR_DRAFT` both halves,
R9/R10 regressions, multi-lineage compilation, rejected-alternative preservation,
human-resolved vs. unresolved overlap, historical replay of a superseded decision,
`OUTCOME_UNKNOWN` continuation, compilation crash/recompute, pre/post-admission
supersession races, Canon-base race rejection) plus 2 meta-tests (matrix covers
every mutation exactly once; no skips on any dialect). 50/50 pass on both SQLite
and real Postgres.

All fifteen counters are `0`:

```text
v1 Scene/Plan hash regressions           0
relationship constraint violations       0
thread lifecycle violations              0
unproven thread payoff acceptance        0
unauthorized omniscient authoring        0
unauthorized Narrative decisions         0
stale decision consumption               0
unresolved overlap compilation           0
compiler nondeterminism                  0
Narrative-to-Canon authority bypass      0
failed transaction corruption            0
cross-scope evidence leakage             0
donor parity regressions                 0
unverified material donor behavior       0
required skips                           0
```

## R2-DEC-031 donor evidence bundle (spec §16.9)

`tests/integration/donor_parity/` reconfirmed fresh at `8b1959e7`: 75 tests total
(57 Huohuo change-record branch/error/prose cases, 18 Novel Studio hard-rule cases
covering hit/miss/empty/hard-only/soft-only/combined/severity/merge-ordering),
**0 skips, 0 failures**. Confirmed `tests/integration/donor_parity/_harness.py`
genuinely subprocesses `node --import tsx <runner> <fixtures>` against the pinned
TypeScript source (not mocked) — real Node baseline execution, not waived.

## Self-review substitute (Codex unavailable)

Performed 2026-09-15 in place of Task 32 Step 5's Codex review, at the operator's
explicit request once Codex's usage-limit block was confirmed. Scope: read spec
§18 (risk table) and §19 (out-of-scope list); line-by-line review of the two
genuinely-unreviewed-by-anyone commits (`54247033`, `09f24d3c`); spot-check of the
highest-stakes new surface (`NarrativeAcceptanceService.admit_canon_handoff`,
`NarrativeCanonHandoffFacade`) against the risk table and out-of-scope boundaries.

Findings (both fixed, commit `8b1959e7`):
1. `_seed_one_reviewed_change_set`'s Postgres FK-trigger-disable was applied to
   every caller, including ~9 happy-path tests that never needed it — narrowed to
   only the one caller that deliberately seeds a mismatched basis.
2. `IMPLEMENTATION_ALLOWLIST_M5C4` allowed `pyproject.toml` even though this
   checkpoint's actual diff never touches it — removed the unjustified,
   scope-loosening entry.

No §19 out-of-scope violations found: no new Canon repository, approval service,
or second extractor; `NarrativeCanonHandoffFacade.commit_from_admission` has zero
production callers (confirmed via `trace_path`) — correctly unwired, since wiring
a production trigger is out of scope for M5C.

This self-review does not carry the same weight as an independent Codex pass and
is explicitly not a substitute for one — see Status above.

## Handoff

`M5C_FINAL_HANDOFF_HEAD` = `8b1959e7ae882716a9d531f459d8289c83968fbb` (this file's
commit is the only change on top of it). No push, merge, migration, or production
step follows from this file without separate explicit Human approval (spec §17.8).
M6 may treat this head as its accepted upstream base per the operator's override
recorded above.
