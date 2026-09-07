# R2-M4 Baseline CI Remediation Scope

**Project:** Content & Narrative Production OS
**Purpose:** Remove pre-existing Python CI debt that blocks the approved C04/M4 plans.
**Date:** 2026-09-07
**Status:** APPROVED / AUTHORITATIVE
**Pinned baseline:** `1985b815d70dd600519839973b1da20472012d8f` on `r2/main`
**Implementation status:** NOT STARTED

## 1. Evidence

The baseline probe verified:

```text
branch = r2/main
local HEAD = origin/r2/main
HEAD = 1985b815d70dd600519839973b1da20472012d8f
worktree = CLEAN
starting_head_gate = PASS
```

Observed quality gates:

```text
ruff check .                  FAIL — 113 findings
ruff format --check .         FAIL — 43 files
basedpyright --warnings       FAIL — 11 errors, 2 warnings
deptry ... r2                 PASS
lint-imports                  PASS — 2 kept, 0 broken
```

Current static-analysis configuration still excludes `r2` from the declared roots/includes:

```text
importlinter.root_packages = ["lib"]
basedpyright.include = ["lib", "server", "alembic", "tests", "scripts"]
deptry.known_first_party = ["lib", "server", "alembic", "scripts", "tests"]
```

## 2. Scope

### In scope

```text
behavior-preserving Ruff cleanup
Ruff formatting of the exact 43 reported files
static-test expression changes needed for basedpyright
package re-export hygiene without removing public R2/M3 API
targeted modernization required by the currently configured Ruff rules
R2 static-analysis root/include coverage after the existing baseline is green
CI workflow + CLAUDE.md deptry scope alignment so r2 is scanned in real CI and documented local gates
post-remediation exact-SHA handoff/re-pin to C04 v2.2 and M4 v2.2
verification of frozen M1/M2/M3/Host behavior after cleanup
one full repository pytest run because the formatter touches lib/artifact_manifest.py
```

### Out of scope

```text
C04 budget implementation
M4 Production Intelligence implementation
new features
contract redesign
provider/runtime redesign
M5
H1 closure
DB migration
Host queue changes
Artifact Manifest semantic changes
new Ruff ignores or blanket baseline exclusions
--unsafe-fixes
repo-wide unrelated refactor
```

## 3. Behavior-preservation rules

1. Do not weaken Pydantic contracts to satisfy basedpyright.
2. Tests that intentionally pass forbidden provider/model/endpoint fields must use runtime validation entrypoints such as `model_validate(...)`, not make those fields legal.
3. Tests relying on a `mode="before"` validator/default derivation must use `model_validate(...)` rather than adding a value solely for the static constructor signature.
4. Public package imports currently exposed from `r2.contracts`, `r2.m3`, and `r2.production` must remain importable.
5. Formatting authoritative Markdown changes layout only; run frozen-registry/baseline verification after formatting.
6. No Ruff `noqa`, global ignore, exclude, or unsafe fix is added merely to make the gate pass.
7. Any cleanup that changes a frozen public value, state transition, fingerprint, ApprovedMaster behavior, or Host baseline semantics is a STOP condition.
8. `ClaimStatus(str, Enum) -> StrEnum` is allowed only after impact discovery proves no caller depends on the old `str(enum_member)` representation; otherwise STOP rather than silently changing behavior.
9. `.github/workflows/test.yml`, `CLAUDE.md`, and the deptry scope comment in `pyproject.toml` must agree on scanning `r2`.
10. Do not bypass pre-commit/pre-push hooks with `--no-verify` or `SKIP=...`; if a hook auto-fixes staged files, review and restage the hook-produced diff before committing.
11. Evidence records `verified_head` (the commit actually tested). The next stage pins its `starting_head` to the producer worktree's clean current `handoff_head` after evidence-only commits, and proves `verified_head` is an ancestor of that handoff. No early merge/push to `r2/main` is required.

## 4. Acceptance

```text
ruff check .                                  PASS
ruff format --check .                         PASS
basedpyright --warnings                       PASS
deptry lib server alembic tests scripts r2   PASS
lint-imports                                  PASS
full repository pytest -n 4 --dist loadfile     PASS

M3 focused frozen selection                  122 PASS
M2 frozen selection                          53 PASS
M1 frozen selection                          41 PASS
ArcReel Host frozen selection                349 PASS
architecture audit                           0 blocking issues

new feature behavior                         NONE
DB migration                                 NONE
unapproved Host runtime change               NONE
worktree at evidence gate                    CLEAN
```

The `349 PASS` Host assertion is valid only against the pinned baseline lineage. A rebase/merge/sync that changes that lineage requires explicit re-baselining rather than carrying the number forward.
