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
