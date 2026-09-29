# V2-02d: backfill decides and promotes under the artifact's row lock

## Finding

Source: the independent Codex review of M8-A, round 2 (`dc13cc93..f606ac06`), new finding 1. The same review accepted V2-02c.

`backfill_project` checked that an artifact had no database head in one session. Later, in another session, it promoted with the version it read then (`promote_staged` re-reads the current version). If a Gate C approval committed between those steps, the backfill promoted its stale file master as the next version, over Gate C's new head. A compare-and-set conflict at that point also escaped its exception handler, which omitted `MasterHeadConflictError` and aborted the run.

## Rule

This is the V2-02b rule: a write that depends on a master head runs in one transaction that holds that head's `master_authorities` row lock, and it writes only if the head is unchanged. For each artifact, the backfill now does all of the following inside one `serialized_artifact` transaction:

- reads the head;
- when the head is empty, hashes the staged version;
- registers the candidate and promotes it with a deferred commit.

A later Gate C approval waits for that commit, then promotes over it. Any M7 promotion conflict records the artifact as `diverged` and changes nothing.

## Verification

| Check | Result |
|---|---|
| `test_a_gate_c_approval_between_the_head_check_and_the_promotion_is_not_overwritten` (PG16; a serialized late approval starts inside the backfill's window) | old code: the head is the backfill's stale candidate at version 2 (assertion fails); new code: passed |
| Backfill, M7 promotion repository, master authority unit, Gate C/D master authority routes on PG16 | 39 passed |
| M7 unit, scripts/r2, Gate C/D/export routes on SQLite | 512 passed, 4 skipped. The one failure was `test_verify_m7_scope_git`, which fails on a dirty tree; it was rerun after the commit. |
| `ruff check .`, `ruff format`, `basedpyright --warnings` (changed files), `lint-imports`, `audit_tests.py --check`, `deptry` | clean |

The independent review is bundled with M8-A round 3.

## Round 3 follow-up

The Codex review of M8-A, round 3 (`dc13cc93..07cb27f9`), confirmed the race fix but did not accept V2-02d. It found two backfill paths that report the wrong result:

1. **Missing snapshot file.** The selected host version's snapshot file was missing. `prepare_candidate` raised `FileNotFoundError`, which aborted `--all` before the summary.
2. **Changed bytes on a rerun.** On a rerun, a head that names the expected candidate returned `current` without re-reading the selected version, even if its bytes had changed.

**Rule.** Under the row lock, every artifact checks one thing first: the selected host version exists, has a recorded digest, and its file still hashes to that digest. If it does not, the artifact is `diverged`.

- An existing head is `current` only when it names the expected candidate and its content digest equals the verified staged digest.
- A promotion runs only after the check.
- A file that disappears between the check and the registration (`FileNotFoundError`) is also reported as `diverged`.

| Check | Result |
|---|---|
| `test_a_missing_version_file_is_reported_and_the_run_continues` | old: `FileNotFoundError` escapes; new: exit 2, SH01 diverged, SH02 promoted |
| `test_a_rerun_reports_a_version_whose_bytes_changed_as_diverged` | old: both artifacts reported `current`; new: exit 2, SH01 diverged, SH02 current |
| Backfill tests on SQLite and on PG16 | 4 passed, 1 skipped (PG-only); 5 passed |
| M7 unit, scripts/r2, Gate C/D/export routes on SQLite | 514 passed, 4 skipped. `test_verify_m7_scope_git` fails only on the uncommitted tree; it was rerun after the commit. |
| `ruff`, `basedpyright` (changed files), `lint-imports`, `audit_tests.py --check`, `deptry` | clean |

## Round 4 follow-up

The Codex review of M8-A, round 4 (`dc13cc93..809e1358`), confirmed both round 3 fixes. It found one more abort: a selected version record whose `file` lies outside the managed snapshot bucket raised `UnmanagedSnapshotPathError` (a `BadRequestError`). That exception escaped the handler.

Rather than add another exception type, the rule now separates two boundaries:

- **The verification boundary** reads only project version metadata and files, never the database. It builds the host integration, reads the record, resolves the path, and hashes the file. Any failure there means the selected version cannot be verified. The artifact is then `diverged` and the failure is logged.
- **The registration step** runs after the check, inside the locked transaction. An `OSError` there comes from the file changing or vanishing after the check. It is raised as `_UnverifiableVersionError`, which rolls the transaction back and reports the artifact as `diverged`. A database failure is not an `OSError` at this point, because the connection is already live, so it still aborts the run.

| Check | Result |
|---|---|
| `test_an_unmanaged_or_malformed_version_record_is_reported_and_the_run_continues[../outside.mp4]`, `[5]` | old: `UnmanagedSnapshotPathError` escapes; new: exit 2, SH01 diverged, SH02 promoted |
| `test_a_file_failure_during_registration_rolls_the_artifact_back_and_the_run_continues` | old: `PermissionError` escapes; new: exit 2, SH01 diverged with no head, SH02 promoted |
| Backfill tests: SQLite / PG16 (with Gate C/D master authority routes) | 7 passed, 1 skipped / 20 passed |
| M7 unit, scripts/r2, Gate C/D/export routes on SQLite | 517 passed, 4 skipped. `test_verify_m7_scope_git` fails only on the uncommitted tree; it was rerun after the commit. |
| `ruff`, `basedpyright` (changed files), `lint-imports`, `audit_tests.py --check`, `deptry` | clean |

## Round 5 follow-up: the complete outcome model

The Codex review of M8-A, round 5 (`dc13cc93..96a84875`), confirmed R4-1 and accepted V2-02c. It raised two findings, both present before V2-02d:

- **R5-1.** `projected_master_records` silently dropped an episode-video entry whose R2 metadata failed validation. A run could therefore exit 0 with an unbackfilled master.
- **R5-2.** On a host without `ffprobe`, every valid master was reported `diverged` instead of the run failing as infrastructure.

To stop finding outcome paths one review at a time, the model below was written before this follow-up's code. Every path of the command is listed here.

| Level | Condition | Outcome |
|---|---|---|
| Run | `ffprobe` missing | exit 3 before any project is read or written; stderr names the tool |
| Run | database failure | the exception aborts the run (infrastructure, not data) |
| Project | the manifest cannot be read (any failure while reading project files) | `unreadable: [reason]`; the next project continues; exit 2 |
| Artifact | a non-episode-video key | `skipped` (never a Gate C master) |
| Artifact | episode-video R2 metadata that fails validation | `diverged`, logged |
| Artifact | a head names another candidate | `diverged` |
| Artifact | the selected version cannot be verified (the verification boundary) | `diverged`, logged |
| Artifact | a head names the expected candidate and the verified digest matches | `current` |
| Artifact | a head names the expected candidate, but the digests differ | `diverged` |
| Artifact | no head; verified; registration and promotion succeed | `promoted` |
| Artifact | no head; an M7 conflict or a file failure during registration | the transaction rolls back, then `diverged` |

The exit status is 3 for a missing tool. It is 2 when any artifact is `diverged` or any project is `unreadable`. Otherwise it is 0.

### Round 5 verification

| Check | Result |
|---|---|
| `test_an_episode_master_whose_metadata_does_not_validate_is_reported` | old: the entry is omitted (SH01 not reported); new: exit 2, SH01 diverged, SH02 promoted |
| `test_a_missing_media_probe_fails_the_run_before_any_write` | old: every master diverged; new: exit 3, `ffprobe` named on stderr, no summary, no head |
| `test_an_unreadable_manifest_is_reported_and_exits_2` | old: the manifest error aborts the run; new: exit 2 with one `unreadable` reason |
| `test_a_conflict_after_registration_rolls_the_candidate_back` | old and new: SH01 diverged and its registered candidate rolled back (a coverage test; round 5 noted the earlier test failed before any write) |
| Backfill tests on SQLite | 11 passed, 1 skipped (the skip needs PostgreSQL) |
| Backfill tests and the Gate C/D master authority routes on PG16 | 24 passed |
| M7 unit, scripts/r2, Gate C/D/export routes and `tests/integration/server/services` on SQLite | 1171 passed, 5 skipped. `test_verify_m7_scope_git` fails only on the uncommitted tree; it was rerun after the commit. |
| `ruff`, `basedpyright` (changed files), `lint-imports`, `audit_tests.py --check`, `deptry` | clean |

## Round 6 follow-up: the model, revised against an exhaustive sweep

Round 6 (`dc13cc93..72d1de78`) swept the whole backfill against the model above. It found three blocking and three non-blocking paths, all reported in one round. The model is revised as follows before the code changes:

| Level | Condition | Outcome | Round 6 item |
|---|---|---|---|
| Run | `ffprobe` missing at start, or lost mid-run (a registration probe fails and `ffprobe` is gone) | exit 3; stderr names the tool; artifacts promoted earlier stay promoted, and a rerun replays them | R6-5 |
| Run | the project listing itself fails, or the database fails | the exception aborts the run | — |
| Run | `--all` selects no project | `{}` and exit 0 (nothing to backfill) | informational |
| Project | the project's path lookup or its manifest read fails | `unreadable: [reason]`; the next project continues; exit 2 | R6-3 |
| Artifact | an episode-video database head whose key has no valid manifest projection (entry absent, `r2` null, no `approved_master`, or a missing manifest) | `diverged`, logged | R6-1 |
| Artifact | episode-video R2 metadata that fails validation | `diverged`, logged | R5-1 |
| Artifact | under the row lock, the manifest is read again; the key's approved master is gone or unreadable | `diverged`, logged; nothing is promoted from the stale scan | R6-2 |
| Artifact | a head names another candidate | `diverged` | — |
| Artifact | the selected version cannot be verified | `diverged`, logged | R4-1 |
| Artifact | expected head, verified digest matches | `current` | — |
| Artifact | expected head, digests differ | `diverged` | R3 |
| Artifact | no head; verified; registered and promoted | `promoted` | — |
| Artifact | no head; an M7 conflict or a registration file failure | the transaction rolls back, then `diverged` | R5 |

Non-episode manifest keys are never Gate C masters. The scanner leaves them out, so the summary has no `skipped` list (R6-4).

A `diverged` or `unreadable` artifact gets no master head written by the backfill; an existing head (for example one that names another candidate) is left unchanged. `serialized_artifact` may leave its authority row at version 0, which is the lock row and is not a promoted master. `verify_masters` lists only rows above version 0 (R6-6).

### Round 6 verification

| Check | Result |
|---|---|
| `test_a_database_head_without_a_projection_is_reported[entry removed / r2 cleared / approval cleared]` (R6-1) | old: SH01 omitted, exit 0; new: exit 2, SH01 diverged, SH02 current |
| `test_a_projection_removed_after_the_scan_is_not_promoted` (R6-2) | old: SH01 promoted from the stale scan; new: exit 2, SH01 diverged with no head, SH02 promoted |
| `test_a_project_that_vanishes_during_all_is_reported_and_the_run_continues` (R6-3) | old: `FileNotFoundError` aborts the run; new: exit 2, `ghost` unreadable, the real project promoted |
| `test_a_media_probe_lost_during_the_run_exits_3` (R6-5) | old: SH01 diverged, exit 2; new: exit 3, `ffprobe` on stderr, no summary |
| R6-4 (the unreachable `skipped` list) and R6-6 (the version-0 lock row) | the dead branch and the summary key are removed; the docstring and the model describe the lock row |
| Backfill tests on SQLite / PG16 (with Gate C/D master authority routes) | 17 passed, 1 skipped / 30 passed |
| M7 unit, scripts/r2, Gate C/D/export routes and `tests/integration/server/services` on SQLite | 1177 passed, 5 skipped. `test_verify_m7_scope_git` fails only on the uncommitted tree; it was rerun after the commit. |
| `ruff`, `basedpyright` (changed files), `lint-imports`, `audit_tests.py --check`, `deptry` | clean |

## Acceptance (own V2 track, amendment 12)

The independent Codex review of V2-02d (`task-mumqz1lr-oy26r0`, reviewed HEAD `68be75bf`) accepted the packet under the amendment 12 stopping rule. It found R6-1 to R6-6 FIXED, and every row of the revised outcome model matches the code. There is one non-blocking finding. N1 said the sentence "gets no master head" overstated the behavior for an artifact with an existing, different head; the sentence above is corrected accordingly.

Two further items are recorded as limits, not defects:

- R6-4 and R6-6 have no distinguishing test (code removal and documentation only).
- `test_a_media_probe_lost_during_the_run_exits_3` exercises the mid-run loss only on a host where `ffprobe` is present at the start.

Verdict (verbatim):

```json
{"status":"V2_02D_ACCEPTED","reviewed_head":"68be75bf943beed2a427d36ea2cd275497fb24ce","blocking_findings":[],"nonblocking_findings":["N1: evidence overstates that every diverged artifact has no master head"],"material_unknowns":["Tests and PostgreSQL concurrency behavior were not freshly executed in this read-only review."]}
```

The authoring agent ran the tests: see the per-round verification tables above and the M8-A evidence logs bound to `b72df36b`.
