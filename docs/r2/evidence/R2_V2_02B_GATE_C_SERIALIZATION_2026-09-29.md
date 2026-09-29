# R2 V2-02b — serialize Gate C per artifact (2026-09-29)

This is an implementation candidate awaiting an independent review.

## Defect

`tests/integration/server/routers/test_gates_master_authority.py::test_overlapping_gate_c_approvals_of_one_artifact_end_consistent`
failed 2 of 6 runs on `r2-v2/main` `cca1eeaf` (SQLite). The race:

1. A stages, then B stages. The manifest now holds B's content fingerprint.
2. B promotes, then A promotes, so the head is A.
3. B's projection is superseded.
4. A's projection is refused by `ProductionApprovalService.check`, because of the fingerprint.

The database head is left without its projection.

## Fix

`5d387e4a059cdce97c4ef25c5d3cf85627a477ee` on `fix/r2-v2-02b-serialize-gate-c`, from `cca1eeaf`.

- **What runs under the lock.** `server/services/master_authority.py::serialized_artifact`
  holds the artifact's `master_authorities` row write lock for one transaction. Gate C stages,
  checks, promotes (`master_authority_unit(..., defer_commit=True)`) and projects inside it,
  then commits.
- **Refused projections.** A refused projection rolls the promotion back and returns 409
  `master_conflict`.
- **After the commit.** The export and the Gate C receipt follow it.
- **The first row.** A concurrent first creation of the row is retried, bounded to 5 attempts.

## Verification at `5d387e4a059cdce97c4ef25c5d3cf85627a477ee`

| Run | Result |
|---|---|
| `test_gates_master_authority.py`, 5 repeated runs on SQLite; the overlapping test runs 3 concurrent rounds each | 6 passed ×5 |
| The same file, 3 repeated runs on PG16 (`arcreel_v201`) | 6 passed ×3 |
| The master-authority unit, Gate export and router, and backfill suites on PG16 | 40 passed |
| host_hardening, Gate routers, M3, backfill, architecture, candidate store and production suites on SQLite | 1247 passed, 2 skipped |
| ruff, basedpyright, lint-imports, deptry and audit_tests | clean |

## Limits

- **SQLite.** A Gate C holds the database write lock for its stage copy and projection. Other
  writers wait up to the 30 s busy timeout. Production runs PostgreSQL.
- **Commit failures.** A commit that fails after the projection leaves the projection ahead
  until a retry with the same `approval_record` converges.

---

# Codex review 1 (job `task-mumbkyt0-9t44fw`, reviewed HEAD `18c50eec`), verbatim

**HEAD reviewed:** `18c50eece5633fced6d52e45a8d7bcebb22b625f`  
**Verdict:** **CHANGES_REQUIRED**

| Severity | File:line | Scenario | Confidence |
|---|---|---|---|
| High | [gates.py:389](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:389) | The artifact lock ends before composite export. Approval A can begin copying its final, approval B can then promote and export a newer final, and A can replace B’s export afterward. Both requests can return 200 while `output/` contains A’s bytes under B’s head. The overlapping test uses shots, so it does not exercise this window. | High |
| High | [master_authority.py:81](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/services/master_authority.py:81) | Projection changes files before the enclosing database commit. If that commit fails or is cancelled, rollback restores the old database head but cannot restore its file projection. The evidence document acknowledges projection ahead until a retry; no commit-failure recovery test establishes that a retry occurs. | High |
| Medium | [test_gates_master_authority.py:188](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/tests/integration/server/routers/test_gates_master_authority.py:188) | Three timed rounds increase the chance of overlap but do not force the critical interleaving. The test checks final agreement, not export consistency or a failed commit. | High |

The no-op `UPDATE` is a valid lock acquisition for an existing row on PostgreSQL and a write-lock acquisition on SQLite by inspection. The same session carries promotion through projection; its nested savepoints and deferred promotion commit do not themselves end the outer transaction.

**Commands run:** `git status`, `git rev-parse`, `git diff cca1eeaf..18c50eec`, `git log`, targeted `rg`/`nl` source inspection, and the requested bounded pytest command. Pytest failed before collection: Python found **no usable temporary directory** in `/tmp`, `/var/tmp`, `/usr/tmp`, or the checkout. No tests ran. The checkout remained clean.

**Coverage limits:** The codebase graph was approval-blocked, so call paths were verified from source. PostgreSQL concurrency, cancellation, and commit failure were not fault-injected in this read-only environment.

```json
{
  "schema_version": 1,
  "status": "V2_02B_NOT_ACCEPTED",
  "reviewed_head": "18c50eece5633fced6d52e45a8d7bcebb22b625f",
  "reviewer": "codex",
  "reviewed_at": "2026-09-29T06:55:20Z",
  "required_skips": [
    "Targeted pytest failed before collection: no usable temporary directory"
  ],
  "material_unknowns": [
    "PostgreSQL concurrent composite export behavior was not executed",
    "Database commit failure and cancellation after file projection were not fault-injected"
  ]
}
```

## Resolution — `1c22dccf`

The two-phase Gate C:

- **Phase 1** stages, checks and promotes under the row lock, then commits.
- **Phase 2**, under the row lock again and only while the promoted candidate is still the
  head, restores its semantic state, projects, and writes the composite export.

| Finding | Fix | Test |
|---|---|---|
| High: export outside the lock | Phase 2 writes the export under the lock, only for the current head | `test_an_approval_superseded_before_its_projection_writes_nothing` forces a newer approval between an older one's promotion and its projection. It asserts that the older one gets 409 and that the export holds the newer bytes, and it fails without the phase-2 head check |
| High: projection before commit | The projection now always follows the commit, so files never run ahead of the database | by construction |
| Medium: the timed test does not force the interleaving | The forced-interleaving test above. The overlapping test runs on independent connections (`concurrent_session_factory`, file WAL SQLite, or PG) | — |

**Verification at `1c22dccf`:**

- `test_gates_master_authority.py`: 7 passed ×3 on PG16, 7 passed ×3 on SQLite.
- The master-authority unit, Gate export and router, and backfill suites on PG16: 40 passed.
- The broad SQLite suites: 1248 passed, 2 skipped.
- Static gates: clean.

**Known behaviour.**

- **Superseded approvals.** An approval superseded before phase 2 returns 409
  `master_superseded` (runbook §4b).
- **Transient refusals.** Between phase 1 and phase 2, a master-consuming read of the same
  artifact may get a transient 409 `master_diverged`.

---

# Codex review 2 (job `task-mumc22w3-swd1lt`, reviewed HEAD `7666071b`), verbatim

## 1. HEAD reviewed

`7666071ba976b72a3bc0e0cf39b0419ee8ac74ec` on `fix/r2-v2-02b-serialize-gate-c`; the worktree was clean. I reviewed `18c50eec..7666071b` and the whole packet `cca1eeaf..7666071b`.

## 2. Verdict

**CHANGES_REQUIRED.** The two phase change addresses the export ordering, but a failed or in progress stage can make an *old* approved final appear current against *new* source dependencies. That can let the old export through Gate D and download.

## 3. Prior findings

| Prior finding | Status | Evidence and test |
|---|---|---|
| Export outside the artifact lock | **FIXED** | [gates.py:418](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:418) calls `project_if_current`, which checks the head while holding the write lock at [master_authority.py:115](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/services/master_authority.py:115); export runs within that call at [gates.py:369](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:369). The forced supersession test checks that an older approval cannot replace the newer export at [test_gates_master_authority.py:180](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/tests/integration/server/routers/test_gates_master_authority.py:180). |
| Projection before database commit | **FIXED** for the reported ordering | Phase 1 exits and commits at [gates.py:411](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:411) before phase 2 projects at [gates.py:418](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:418). No test injects a phase 1 commit failure. A committed head can still await projection or remain unprojected after a phase 2 failure; the retry test covers one such failure at [test_gates_master_authority.py:152](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/tests/integration/server/routers/test_gates_master_authority.py:152). |
| Timed test does not force the critical interleaving | **PARTIALLY_FIXED** | The new wrapper forces a newer complete approval between the older promotion and projection at [test_gates_master_authority.py:191](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/tests/integration/server/routers/test_gates_master_authority.py:191). The separate overlapping test still uses timing at [test_gates_master_authority.py:219](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/tests/integration/server/routers/test_gates_master_authority.py:219); neither test forces a phase 1 commit failure or the stale-dependency scenario below. |

## 4. New findings

| Severity | File:line | Scenario | Confidence |
|---|---|---|---|
| **High** | [host_integration.py:260](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/r2/m3/host_integration.py:260), [host_integration.py:182](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/r2/m3/host_integration.py:182), [artifact_bridge.py:198](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/r2/production/artifact_bridge.py:198) | Approve final A from shot v1; then approve shot v2, making A stale. Start final B from v2 and fail after `stage_candidate` writes B’s dependencies but before promotion commits. The manifest keeps A’s `approved_master` while carrying B’s current dependencies. Currency checks those dependencies, and [current_deliverables at deliverables.py:289](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/r2/m3/deliverables.py:289) can consequently mark A’s unchanged bytes and export as current. The database head and projected master still agree, so the route’s master check does not catch it. This window also exists during phase 1. No test exercises it. | High |
| **Medium** | [gates.py:414](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:414), [gates.py:429](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:429) | A crash, cancellation, or phase 2 failure after the phase 1 commit can leave the head without its projection until the same approval is retried. The documented retry converges for injected failures, but no automatic reconciliation or bounded recovery is established here. Readers of that artifact receive the documented transient 409; without a retry it is persistent. | High |

The narrowed composite check covers the named source keys at [gates.py:321](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:321). A diverged unrelated master can therefore pass that pre-check, while the publish, listing, and download routes still call the project-wide check at [gates.py:475](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:475), [gates.py:546](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:546), and [gates.py:559](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:559). I found no basis to mark that narrowing as a separate defect. SQLite’s database-wide write lock also spans staging and, in phase 2, copying the export ([master_authority.py:81](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/services/master_authority.py:81), [master_authority.py:115](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/services/master_authority.py:115)); its contention cost was not measured.

## 5. Commands run

Read-only `git status`, `git rev-parse`, both requested `git diff` ranges, targeted `nl`/`rg` source inspection, and the graph project lookup. I attempted:

```bash
TMPDIR=/tmp timeout 90s .venv/bin/python -m pytest -q -p no:cacheprovider tests/integration/server/routers/test_gates_master_authority.py tests/unit/r2/test_master_authority_boundaries.py
```

Pytest failed **before collection** with `FileNotFoundError: No usable temporary directory found`. No test passed in this review.

## 6. Coverage limits

The graph project lookup succeeded, but subsequent graph status and search calls were approval blocked; structural conclusions above come from direct source inspection. I could not execute the targeted tests, PostgreSQL concurrency cases, commit-failure injection, or SQLite contention measurements. The reported test coverage is therefore inspection of test code, not a fresh passing result.

## 7. Review record

```json
{
  "schema_version": 1,
  "status": "V2_02B_NOT_ACCEPTED",
  "reviewed_head": "7666071ba976b72a3bc0e0cf39b0419ee8ac74ec",
  "reviewer": "codex",
  "reviewed_at": "2026-09-29T07:08:02Z",
  "required_skips": [
    "Targeted pytest failed before collection: no usable temporary directory in the read-only sandbox"
  ],
  "material_unknowns": [
    "Phase 1 commit failure and stale-dependency scenario were not fault-injected",
    "PostgreSQL concurrent behavior and SQLite write-lock contention were not executed",
    "Graph status and search were approval blocked"
  ]
}
```

## Resolution — `32510633`

| Finding | Fix | Test |
|---|---|---|
| High: a failed or in-flight stage makes an old approved final look current against new dependencies | `stage_candidate(keep_approved_semantic_state=True)` leaves an approved artifact's semantic state alone. Phase 1 checks the candidate against the state it would have (`semantic_state_for`, `check_approvable(semantic_state=...)`). Phase 2 writes the state only while the candidate is the head | `test_a_final_whose_promotion_fails_after_staging_leaves_the_old_final_stale`, which fails with the flag off (verified) |
| Medium: a head left unprojected after a crash | Fail-closed: readers of the artifact refuse with 409 `master_diverged`. Recovery is a retry with the same `approval_record` (a client retry on 503 or after a lost connection), or a new Gate C approval. Runbook §4b now states it | `test_a_projection_refused_after_the_commit_asks_for_a_retry_that_converges` |
| Prior Medium: the overlapping test relies on timing | The forced-interleaving test is the deterministic guard. The overlapping test runs on independent connections as a stress check | — |

**Verification at `32510633`:**

- `test_gates_master_authority.py`: 8 passed on SQLite, 8 passed ×2 on PG16.
- The broad SQLite suites: 1249 passed, 2 skipped. The one failure before the fix was a stale test double signature, now fixed.
- The PG16 master-authority, Gate and backfill suites: 40 passed.
- Static gates: clean.

---

# Codex review 3 (job `task-mumcenxp-j9udvl`, reviewed HEAD `814a7244`), verbatim

## 1. HEAD reviewed

`814a7244b435364ab1a90d2f17af429f1b557b9` on `fix/r2-v2-02b-serialize-gate-c`; worktree clean. I reviewed `7666071b..814a7244` and the whole packet `cca1eeaf..814a7244`.

## 2. Verdict

**CHANGES_REQUIRED.** Staging now preserves an approved final’s semantic state, and the new test exercises the reported failure. A reader race remains during phase 2: a request can pass the master check before the new head commits, then read new dependencies paired with the old approved master before projection finishes.

## 3. Per-finding table

| Prior finding | Status | File:line | Test coverage yes/no |
|---|---|---|---|
| Export can run after an approval is superseded | **FIXED** | [gates.py:429](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:429), [master_authority.py:115](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/services/master_authority.py:115) | **Yes**, forced supersession at [test_gates_master_authority.py:180](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/tests/integration/server/routers/test_gates_master_authority.py:180) |
| File projection precedes database commit | **FIXED** for that ordering | [gates.py:422](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:422), [gates.py:429](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:429) | **No** phase 1 commit-failure injection; retry after a projection failure is exercised at [test_gates_master_authority.py:152](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/tests/integration/server/routers/test_gates_master_authority.py:152) |
| Timed overlap test does not force the critical interleaving | **PARTIALLY_FIXED** | Forced supersession at [test_gates_master_authority.py:191](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/tests/integration/server/routers/test_gates_master_authority.py:191); timed test remains at [test_gates_master_authority.py:219](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/tests/integration/server/routers/test_gates_master_authority.py:219) | **Yes** for supersession; **no** for the phase 2 reader window below |
| Failed or in-flight stage can make the old final current against new dependencies | **PARTIALLY_FIXED** | Staging guard at [host_integration.py:278](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/r2/m3/host_integration.py:278); separate phase 2 semantic write at [gates.py:364](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:364) | **Yes** for failed staging at [test_gates_master_authority.py:250](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/tests/integration/server/routers/test_gates_master_authority.py:250); **no** for a concurrent reader |
| A committed head can remain unprojected after a crash | **PARTIALLY_FIXED** | Phase split at [gates.py:422](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:422), retry handling at [gates.py:440](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:440), operator recovery at [v1-operator.md:165](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/docs/r2/runbooks/v1-operator.md:165) | **Yes** for an injected failure followed by the same request at [test_gates_master_authority.py:152](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/tests/integration/server/routers/test_gates_master_authority.py:152); **no** automatic recovery or crash test |

## 4. New findings table

| Severity | File:line | Scenario | Confidence |
|---|---|---|---|
| **High** | [gates.py:490](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:490), [gates.py:364](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:364), [gates.py:373](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:373), [deliverables.py:302](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/r2/m3/deliverables.py:302) | **Inferred interleaving from the cited code:** Gate D verifies old head A, then pauses. Phase 1 commits B. Phase 2 writes B’s current dependencies while the manifest still names A; before `approve` replaces A, Gate D resumes its separate deliverable read. Currency compares B’s dependencies and can report A’s unchanged export as current. Listing and download have the same separated check/read pattern at [gates.py:561](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:561) and [gates.py:589](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:589). No test forces this interleaving. | **High** on code path; runtime interleaving untested |

First-ever approval has a manifest entry created during staging ([host_integration.py:268](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/r2/m3/host_integration.py:268)); replay recomputes `staged_dependencies` before taking the saved-version path ([gates.py:332](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:332), [host_integration.py:255](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/r2/m3/host_integration.py:255)). `promote` checks the restored manifest state ([approval_service.py:69](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/r2/production/approval_service.py:69)). I found no separate defect in those paths by inspection. The new failed-stage test would fail with the guard removed: its final assertion expects 409 after the failed promotion ([test_gates_master_authority.py:268](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/tests/integration/server/routers/test_gates_master_authority.py:268)).

## 5. Commands run

Read-only `git status`, `git rev-parse`, `git log`, both requested `git diff` ranges, and targeted `nl`/`rg` inspections. I attempted `TMPDIR=/tmp timeout 90s .venv/bin/python -m pytest -q -p no:cacheprovider tests/integration/server/routers/test_gates_master_authority.py`. Pytest failed before collection with `FileNotFoundError: No usable temporary directory found`.

## 6. Coverage limits

**No test passed in this review**; “test coverage” above means the test code exercises the path by inspection. Graph status, search, and coverage calls were blocked by the environment’s approval policy, so source and call-site inspection supplied the evidence. The offline Golden A runner also writes approved R2 metadata outside the Gate C route ([golden_a.py:300](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/r2/m3/golden_a.py:300), [golden_a.py:309](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/r2/m3/golden_a.py:309)); its run uses an `output_dir/host_project` checkout ([golden_a.py:257](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/r2/m3/golden_a.py:257)). I did not establish that it writes a live server project.

## 7. JSON

```json
{"schema_version":1,"status":"V2_02B_NOT_ACCEPTED","reviewed_head":"814a7244b435364ab1a90d2f17af429f1b557b9a","reviewer":"codex","reviewed_at":"2026-09-29T07:18:28Z","required_skips":["Targeted pytest failed before collection: no usable temporary directory in the read-only sandbox"],"material_unknowns":["Phase 2 reader interleaving was established by source inspection but not fault-injected","Phase 1 commit failure and crash recovery were not executed","Graph status, search, and coverage were approval blocked"]}
```

## Resolution — `863541ff`

| Finding | Fix | Test |
|---|---|---|
| High: a reader in the phase-2 window sees the new semantic state with the old approved master | `approve(..., semantic_state=)` hands the state to `ProductionApprovalService.promote`. It is checked against, then written with the approved master in the version promotion's single atomic manifest replacement. There is no separate semantic write, and `restore_semantic_state` is removed | `test_no_manifest_write_pairs_the_old_master_with_the_new_semantic_state` records every manifest write of the final. It fails at `814a7244` (verified in a detached worktree). Unit tests: `test_a_semantic_state_is_written_with_its_approved_master_in_one_update` and `test_a_candidate_is_checked_against_the_semantic_state_it_will_have` |
| Partial: head unprojected after a crash | Fail-closed, with the documented retry or re-approval (runbook §4b). There is no automatic reconciler, because the projection needs the request's semantic arguments, which exist only in the request | retry test |

**Remaining reader window, by design.** Inside the version promotion, the host version file is
restored before the manifest update. A reader in between sees the new current file with the old
approved master. That is a digest mismatch, which `current_deliverables` treats as not
exportable (fail-closed). This is the unchanged M2 ordering.

**Verification at `863541ff`:**

- `test_gates_master_authority.py`: 9 passed ×2 on PG16.
- The PG16 unit, Gate and backfill suites: 40 passed.
- The broad SQLite suites: 1253 passed, 2 skipped.
- Static gates: clean.
