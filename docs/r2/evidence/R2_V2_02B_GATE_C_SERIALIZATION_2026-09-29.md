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

---

# Codex review 4 (job `task-mumcpvlk-d4qj5e`, reviewed HEAD `6697e065`), verbatim

## 1. HEAD reviewed

`6697e06536e4084c04465b43f1953019793202c6` on `fix/r2-v2-02b-serialize-gate-c`; worktree clean. I reviewed `814a7244..6697e065` and the whole packet `cca1eeaf..6697e065`.

## 2. Verdict

**CHANGES_REQUIRED.** The reported semantic-state race is fixed, but a Gate D, listing, or download request can still pass its DB-head check before B commits and consume A after B becomes the committed head. The affected reader paths do not check the head again.

## 3. Per-finding table

| Prior finding | Status | File:line and test evidence |
|---|---|---|
| Phase 2 pairs A’s approved master with B’s semantic state | **FIXED** | [gates.py:362](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:362) passes B’s state into approval; [approval_service.py:75](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/r2/production/approval_service.py:75) checks it, and [approval_service.py:97](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/r2/production/approval_service.py:97) combines it with B’s master for the single manifest replacement at [artifact_bridge.py:133](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/r2/production/artifact_bridge.py:133). The write-recording test is [test_gates_master_authority.py:276](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/tests/integration/server/routers/test_gates_master_authority.py:276); unit checks are [test_approval_service.py:199](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/tests/unit/r2/production/test_approval_service.py:199). Tests did not run in this review. |
| Failed or in-flight staging changes A’s dependencies | **FIXED** | [host_integration.py:279](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/r2/m3/host_integration.py:279) preserves an existing approved state during staging. The failed-promotion case is exercised by [test_gates_master_authority.py:250](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/tests/integration/server/routers/test_gates_master_authority.py:250), inspected but not run here. |
| Superseded approval overwrites the newer export; projection precedes DB commit | **FIXED** for those orderings | Phase 1 commits before phase 2 at [gates.py:414](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:414); phase 2 checks and holds the head lock through projection and export at [master_authority.py:115](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/services/master_authority.py:115). Forced supersession is tested at [test_gates_master_authority.py:180](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/tests/integration/server/routers/test_gates_master_authority.py:180). No phase-1 commit-failure test was run here. |
| Crash leaves a committed head unprojected | **PARTIALLY_FIXED** | The split remains at [gates.py:417](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:417) and [gates.py:422](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:422). Retry is documented at [v1-operator.md:165](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/docs/r2/runbooks/v1-operator.md:165) and exercised after an injected projection refusal at [test_gates_master_authority.py:152](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/tests/integration/server/routers/test_gates_master_authority.py:152). Recovery still needs a retry or re-approval; the reader race below limits the fail-closed claim. |
| Timed overlap test does not force the critical interleaving | **PARTIALLY_FIXED** | [test_gates_master_authority.py:191](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/tests/integration/server/routers/test_gates_master_authority.py:191) forces approval supersession; [test_gates_master_authority.py:219](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/tests/integration/server/routers/test_gates_master_authority.py:219) still relies on sleep. Neither forces the reader interval below. |

## 4. New findings table

| Severity | File:line | Scenario | Confidence |
|---|---|---|---|
| **High** | [gates.py:482](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:482), [gates.py:414](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:414), [gates.py:483](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:483), [gates.py:503](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:503) | **Code-derived interleaving:** Gate D verifies A, then pauses. B’s phase 1 commits its DB head; phase 2 has not yet changed A’s manifest, current file, or export because staging uses `select_current=False` at [host_integration.py:301](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/r2/m3/host_integration.py:301). Gate D resumes, finds A exportable from those agreeing files, and records approval for A while B is the DB head. Listing and download have the same separate check/read sequence at [gates.py:553](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:553) and [gates.py:581](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:581). | High on ordering; interleaving not fault-injected. |

I found no separate V1 Gate C/D/O2a regression by inspection. In the version promoter, the current file changes before the manifest callback ([version_manager.py:1326](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/lib/version_manager.py:1326), [version_manager.py:1329](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/lib/version_manager.py:1329)); a reader in that interval encounters a digest mismatch under [deliverables.py:229](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/r2/m3/deliverables.py:229). The later export replacement is atomic and checked against the approved digest at [deliverables.py:185](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/r2/m3/deliverables.py:185). Existing O2a tests cover successful publish/download and stale or tampered exports at [test_gates_export.py:138](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/tests/integration/server/routers/test_gates_export.py:138) and [test_gates_export.py:236](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/tests/integration/server/routers/test_gates_export.py:236); this review did not execute them.

## 5. Commands run

Read-only `git status`, `git rev-parse`, `git log`, both requested `git diff` ranges, targeted `nl`/`rg`, and code-graph status/coverage attempts. I attempted:

```bash
TMPDIR=/tmp timeout 90s .venv/bin/python -m pytest -q -p no:cacheprovider tests/integration/server/routers/test_gates_master_authority.py tests/integration/server/routers/test_gates_export.py tests/unit/r2/production/test_approval_service.py
```

Pytest failed **before collection** with `FileNotFoundError: No usable temporary directory found`. No test passed in this review.

## 6. Coverage limits

Graph status and coverage calls were approval-blocked; structural conclusions use direct source inspection. The new interleaving, a phase-1 commit failure, crash recovery, and PostgreSQL concurrency behavior were not executed. Test references above describe inspected test code or earlier evidence, not fresh passing results.

## 7. JSON

```json
{"schema_version":1,"status":"V2_02B_NOT_ACCEPTED","reviewed_head":"6697e06536e4084c04465b43f1953019793202c6","reviewer":"codex","reviewed_at":"2026-09-29T07:26:18Z","required_skips":["Targeted pytest failed before collection: no usable temporary directory in the read-only sandbox"],"material_unknowns":["DB-head-check to deliverable-read interleaving was established by source inspection but not fault-injected","Phase-1 commit failure and crash recovery were not executed","PostgreSQL concurrency behavior was not executed","Code-graph status and coverage were approval-blocked"]}
```

## Resolution — `2792a08d`

| Finding | Fix | Test |
|---|---|---|
| High: a reader passes the head check, then reads the previous head's files after a new head commits | `verify_masters` returns the verified heads `(key, version, candidate)`. `_stable_read` runs publish approval, listing and download reads between two checks, and refuses with 409 `master_moving` if they differ; a download snapshot is closed first. A Gate D decision is recorded only after both checks agree | `test_a_head_committed_while_gate_d_reads_refuses_the_decision` lands a complete, consistent Gate C of the source shot during the Gate D read. It fails with the comparison disabled (verified) |

**Verification at `2792a08d`:**

- `test_gates_master_authority.py`: 10 passed ×2 on PG16.
- The PG16 unit, Gate and backfill suites: 40 passed.
- The broad SQLite suites: 1254 passed, 2 skipped.
- Static gates: clean.

---

# Codex review 5 (job `task-mumd0tbz-2tx20e`, reviewed HEAD `71e28616`), verbatim

## 1. HEAD reviewed

`71e28616991a2a920a1da33e3d7d724a1fb4080b` on `fix/r2-v2-02b-serialize-gate-c`; clean worktree. I reviewed the fix range `6697e065..71e28616` and whole packet `cca1eeaf..71e28616`.

## 2. Verdict

**CHANGES_REQUIRED.** The new comparison closes the reported race *during* the deliverable read, but Gate D can still record an approval after the second check becomes stale.

## 3. Per-finding status

| Finding | Status | Evidence |
|---|---|---|
| Gate D, listing, or download reads across a head change | **PARTIALLY_FIXED** | [_stable_read](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:257) compares heads before and after the read and returns 409 on change. The forced Gate D test at [test_gates_master_authority.py:307](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/tests/integration/server/routers/test_gates_master_authority.py:307) asserts no decision was inserted. The post-check decision gap remains. |
| Crash leaves a committed head unprojected | **PARTIALLY_FIXED** | Phase 1 commits before projection at [gates.py:431](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:431). Readers fail closed while the head and projection disagree; [the runbook](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/docs/r2/runbooks/v1-operator.md:165) requires retry or re-approval. The injected failure and retry test is at [test_gates_master_authority.py:152](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/tests/integration/server/routers/test_gates_master_authority.py:152). Recovery is not automatic. |
| Timed overlap test | **PARTIALLY_FIXED** | Forced supersession and the new forced read interleaving are covered at [test_gates_master_authority.py:180](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/tests/integration/server/routers/test_gates_master_authority.py:180) and [307](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/tests/integration/server/routers/test_gates_master_authority.py:307). The separate overlap test still relies on sleep at [219](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/tests/integration/server/routers/test_gates_master_authority.py:219); neither forced test covers the gaps below. |

## 4. New findings

| Severity | File:line | Scenario | Confidence |
|---|---|---|---|
| **High** | [gates.py:499](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:499), [519](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:519) | Gate D finishes both checks for final A. A concurrent Gate C commits a new source-shot head before `PublishApprovalRepository.append` commits. Gate D then records `APPROVE_PUBLISH` for A although A is stale. The decision insert has no head comparison or lock; the new test moves the head *inside* `_stable_read`, not in this gap. | High, source-derived; interleaving not executed |
| **Medium** | [gates.py:345](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:345), [349](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:349) | Composite Gate C checks source heads before entering its final-artifact lock. A source Gate C can then commit a new DB head while its old file projection remains. `composite_dependencies` can read that old projection and the final approval can promote against stale source refs. Subsequent Gate D checks fail closed once they observe divergence or the new projection, but Gate C can report approval for a final already stale at promotion. | Medium, source-derived; interleaving not executed |

The `master_version` comparison prevents a normal ABA promotion: each promotion increments it at [promotion.py:135](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/r2/host_hardening/promotion.py:135), even if the candidate ID returns to an earlier value. Download streaming uses the verified temporary snapshot at [deliverables.py:345](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/r2/m3/deliverables.py:345) and [gates.py:603](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:603), so a later export replacement does not change its bytes. I found no additional V1 Gate C/D/O2a regression by inspection.

## 5. Commands run

`git status`, `git rev-parse HEAD`, both requested `git diff` ranges, targeted numbered source and test reads, `git diff --check`, and:

```text
TMPDIR=/tmp timeout 120s .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/integration/server/routers/test_gates_master_authority.py \
  tests/unit/r2/production/test_approval_service.py
```

Pytest stopped **before collection**: `FileNotFoundError: No usable temporary directory`. There is no fresh test result from this review.

## 6. Coverage limits

Codebase-memory search and status calls were approval blocked, so structural conclusions use direct source inspection. The two new interleavings, crash recovery, and PostgreSQL concurrency were not executed. Referenced tests are inspected test code, not tests passed in this review.

## 7. Review record

```json
{"schema_version":1,"status":"V2_02B_NOT_ACCEPTED","reviewed_head":"71e28616991a2a920a1da33e3d7d724a1fb4080b","reviewer":"codex","reviewed_at":"2026-09-29T07:35:04Z","required_skips":["Targeted pytest stopped before collection: no usable temporary directory in the read-only sandbox"],"material_unknowns":["Post-check Gate D decision interleaving was not fault-injected","Composite source-head interleaving was not fault-injected","Crash recovery and PostgreSQL concurrency were not executed","Code-graph search and coverage were approval blocked"]}
```

## Resolution — `465cbc11`

**Principle:** every write that depends on master heads runs in one transaction that holds
those heads' row write locks. `serialized_artifacts` locks them in sorted key order, and the
write is made only if the heads are unchanged. Gate C holds one row per phase (or the final plus
its sources, sorted), so no multi-row holders form a cycle and there is no deadlock.

| Finding | Fix | Test |
|---|---|---|
| High: a Gate D decision after a stale second check | The decision commits inside `_locked_to_heads(heads)`: the row locks of the heads it read, re-verified in the same transaction, with 409 `master_moving` if they changed | `test_a_head_committed_after_gate_d_read_refuses_the_decision` injects a consistent source Gate C just before the decision lock. It fails with the in-lock comparison disabled (verified) |
| Medium: a composite checks its sources before its lock | Phase 1 locks the final and its source shots (`serialized_artifacts([final, *sources])`) and runs `verify_masters(..., artifact_keys=sources)` inside | `test_a_composite_holds_its_source_shots_while_it_stages_and_promotes`: a source Gate C started while the final stages is still waiting 1.5 s later. It fails on PostgreSQL with the source locks removed (verified); SQLite serializes all writers anyway |

**Verification at `465cbc11`:**

- `test_gates_master_authority.py`: 12 passed on SQLite and 12 passed on PG16. PG16 ran it twice before the final seam change, both passing.
- The PG16 unit, Gate and backfill suites: 40 passed.
- The broad SQLite suites: 1256 passed, 2 skipped.
- Static gates, including `audit_tests`: clean.

**Remaining by design:**

- **Listing and download** return data verified between two checks. They do not write, so a
  head that moves after the second check makes their answer historical, not inconsistent.
- **Crash recovery** after phase 1 is fail-closed, with a retry or re-approval.

---

# Codex review 6 (job `task-mumdhxhn-4u8swc`, reviewed HEAD `e24a19fc`): ACCEPTED, verbatim

Earlier dispatches with an empty request (`task-mumdglcf-9d17gs`) returned no review and are
disregarded.

## 1. HEAD reviewed

`e24a19fc1e38b95abda0304c77fe768c21bee564` on `fix/r2-v2-02b-serialize-gate-c`; worktree clean. I reviewed the requested fix and whole-packet diffs.

## 2. Verdict

**ACCEPTED.** Source inspection found no remaining material issue in the packet. This is an inspection-based verdict: the read-only sandbox prevented fresh test execution.

## 3. Per-finding status

| Finding | Status | Evidence |
|---|---|---|
| Gate D records a decision after its second check goes stale | **FIXED** | [_locked_to_heads](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:280) locks the previously read heads, re-verifies them in that transaction, and returns 409 if they moved; [the decision append](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:562) occurs before that transaction commits. [The forced test](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/tests/integration/server/routers/test_gates_master_authority.py:341) inserts a source approval between the read and lock and asserts no decision is recorded. |
| Composite Gate C checks source shots before locking them | **FIXED** | [Phase 1](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:422) verifies source masters after acquiring the final and source locks at [line 470](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:470). [The concurrency test](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/tests/integration/server/routers/test_gates_master_authority.py:374) checks that a source approval waits during staging. Its PostgreSQL result is recorded in [packet evidence](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/docs/r2/evidence/R2_V2_02B_GATE_C_SERIALIZATION_2026-09-29.md:378), but I could not rerun it. |
| Crash leaves a committed head unprojected | **PARTIALLY_FIXED** | [Phase 1 commits before phase 2 projection](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/server/routers/gates.py:470). Readers fail closed on divergence; the [runbook](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/docs/r2/runbooks/v1-operator.md:165) requires retry or re-approval. [The injected failure test](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/tests/integration/server/routers/test_gates_master_authority.py:154) covers retry convergence, not automatic crash recovery. |
| Timed overlap test | **PARTIALLY_FIXED** | [Forced supersession](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/tests/integration/server/routers/test_gates_master_authority.py:182) and the two new forced race tests cover specific interleavings. [The general overlap test](/home/anhtuan/content-production-os/.worktrees/r2-v2-02b/tests/integration/server/routers/test_gates_master_authority.py:213) still relies on timing. |

## 4. New findings

| Severity | File:line | Scenario | Confidence |
|---|---|---|---|
| None material | — | The multi-row locker uses sorted, distinct keys; Gate C’s phase 2 locks one row. Row creation happens before locks are held. File verification extends lock duration but did not expose an unsafe interleaving in the inspected paths. | Source inspection |

## 5. Commands run

`git status`, `git rev-parse HEAD`, both requested `git diff` ranges, targeted numbered source and test reads, and `git diff --check`. The fix-range whitespace check was clean; the whole-packet check reports trailing whitespace in the evidence document at line 51.

I attempted `TMPDIR=/tmp timeout 120s .venv/bin/python -m pytest -q -p no:cacheprovider` on the master-authority, Gate export, and approval-service test files. Pytest stopped **before collection** with `FileNotFoundError: No usable temporary directory`; no test passed in this review.

## 6. Coverage limits

Codebase-memory status, search, and coverage calls were blocked by the environment’s approval policy, so structural conclusions use direct source inspection. PostgreSQL concurrency, crash recovery, and V1 regression tests were not freshly executed. The packet records earlier PostgreSQL and SQLite passes, which I treated as historical evidence rather than this review’s results.

## 7. Review record

```json
{"schema_version":1,"status":"V2_02B_ACCEPTED","reviewed_head":"e24a19fc1e38b95abda0304c77fe768c21bee564","reviewer":"codex","reviewed_at":"2026-09-29T07:48:50Z","required_skips":["Targeted pytest stopped before collection: no usable temporary directory in the read-only sandbox"],"material_unknowns":["PostgreSQL concurrency and crash recovery were not freshly executed","Codebase-memory search and coverage were approval-blocked"]}
```

## Acceptance note (main agent)

- **Test evidence.** The reviewer could not run tests (read-only sandbox). The test evidence is
  the main agent's runs at `465cbc11`, and `465cbc11..e24a19fc` changes docs only:
  - `test_gates_master_authority.py`: 12 passed on SQLite and on PG16;
  - the PG16 Gate and master suites: 40 passed;
  - the broad SQLite suites: 1256 passed, 2 skipped.
- **Accepted limits:**
  - crash recovery after phase 1 is fail-closed, with a retry or re-approval (runbook §4b);
  - the general overlap test is a stress check; the forced-interleaving tests are the
    deterministic guards.
- **Why it took six rounds.** Each fix closed one interleaving of a dual-store (database and
  file) consistency problem, instead of starting from one lock protocol. The final protocol:
  every write that depends on master heads runs in a transaction that holds those heads' row
  write locks (in sorted key order), and it writes only if the heads are unchanged. It is the
  rule for further work on this authority.
