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
