# R2 M7 H6 V1-01: project lifecycle admission protocol options

Date: 2026-09-27
Source HEAD: `97699f6e35ed7c288f80401f2a6a8792d0c29725`
Status: research and candidate design only; no schema, route or capture adapter
is approved by this note.

## Decision to make

V1-01 needs one serialization point for a normalized project identity across
new Task, execution-attempt and backup admissions, published deletion,
archive replacement and whole-tree migration. The existing project-local
`.project.json.lock` moves with the directory; the resource-level generation
lock does not cover all tasks; the signed H6 capture-fence verifier checks
operator quiescence evidence but does not stop a writer. The bounded source
evidence and exact paths are in
[the liveness map](2026-09-26-r2-m7-h6-project-liveness-map.md).

The production Compose file selects `postgres:18-alpine` and uses asyncpg
(`deploy/production/docker-compose.yml:2-24`); the local default is SQLite
(`lib/db/engine.py:27-40`). PostgreSQL 18 documents that row-level locks last
to transaction end and conflict with another update/lock on the same row
([PostgreSQL explicit locking](https://www.postgresql.org/docs/18/explicit-locking.html)).
At default `READ COMMITTED`, a waiting `UPDATE` reevaluates its `WHERE`
predicate on the committed new row version
([PostgreSQL transaction isolation](https://www.postgresql.org/docs/18/transaction-iso.html)).
Those database properties support the candidate below only when *every*
relevant writer participates and holds the same transaction through its
domain-row admission. A
[scratch PostgreSQL 18.6 two-connection probe](../r2/evidence/R2_V1_H6_LIFECYCLE_PG18_PROBE_2026-09-27.md)
confirmed the row-ordering primitive under `read committed`; it did not run
the repo's repositories or lifecycle schema. SQLite tests cannot establish
the production race ordering; repository-level PostgreSQL tests must also
confirm the effective isolation level, since the engine does not set one
explicitly (`lib/db/engine.py:43-60`).

## Candidate A: durable lifecycle row with transactional admission

Create a deployment-scoped lifecycle row keyed by
`(source_deployment_id, normalized_project_name)`. Retain the row forever in
V1 to enforce no name reuse after `RETIRED`. Its proposed fields include an
opaque lifecycle ID, monotonic `version`, state, current command/intent ID,
expected source-tree identity, and timestamps. States should distinguish
`CREATING`, `LIVE`, `DELETING`, `REPLACING`, `MIGRATING`, and `RETIRED`; the
exact schema/state names remain for review. Current project-scoped domain
rows lack a lifecycle FK, so the bootstrap and legacy-row disposition cannot
be inferred from a name match alone.

For every DB-backed work admission, use the **same DB transaction** as the
Task/attempt/backup row write:

1. Execute a single-row conditional `UPDATE lifecycle SET version = version+1`
   for the exact identity with `state = LIVE`, returning the resulting version.
   Zero rows must be converted by the adapter into a typed refusal, never a
   silent zero-row success or unguarded retry against the same project name.
   An expected version or command identity can be included where
   replay semantics require it.
2. Insert the domain row and its command receipt in that transaction, bound
   to the returned lifecycle ID/version or to an immutable admission receipt.
   Commit once. A preliminary filesystem check or migration verdict may run
   before this, but it cannot replace the conditional update.
3. A replay reads the original receipt and returns its original identity;
   it cannot create a new row merely because the project became `RETIRED`.
   The exact receipt/read order requires review against existing command
   replay code.

The conditional update acts as both a state check and a row lock. Incrementing
the version could let a later capture recheck detect intervening admissions,
provided every writer participates and capture binds the exact row/version.
This is an inference from the cited PostgreSQL rules, not a tested repo
implementation. `UPDATE ... RETURNING` is supported by the SQLAlchemy DML
interface ([SQLAlchemy DML](https://docs.sqlalchemy.org/en/20/core/dml.html));
the repo's `TaskRepository.enqueue()` currently commits its own transaction
(`lib/db/repositories/task_repo.py:189-267,337-346`), so an adapter must place
the lifecycle update inside that transaction rather than in the queue's
earlier migration check.

For deletion, first conditionally change `LIVE` to `DELETING` and inspect
active Task statuses, non-terminal attempts, unresolved backup state and any
approved recovery lease in **that transaction**. Roll back the intent if any
blocker exists; otherwise commit the intent *before* recursive filesystem
removal. A racing admission either commits first, after which the deletion
transaction sees its row, or waits for the deletion update and then fails the
`state = LIVE` predicate. This ordering assumes the participating admission
update and row insert commit together and the deletion reads blockers after
acquiring the lifecycle row. The file removal and terminal `RETIRED` marker
are separate steps with an inspectable crash record; a stopped process leaves
`DELETING`, not an inferred success from directory absence.

Archive overwrite requires a separate `REPLACING` intent with old/staged tree
identities and crash reconciliation. A same-name replacement cannot be
assumed to preserve the meaning of old DB content rows. Until that semantic
mapping is approved, a fail-closed V1 option is to reject overwrite for a
governed published identity. New-name import must consult the retained row
and reject `RETIRED`. Whole-tree v5-to-v6 migration similarly requires a
`MIGRATING`/maintenance disposition or a proven stop-the-world window before
its two renames; hidden rollback/staging siblings block capture when
unresolved. These are candidate constraints, not current route behavior.

## Why the other mechanisms are insufficient alone

| Mechanism | Useful part | Missing proof for V1-01 |
| --- | --- | --- |
| Project-local `.project.json.lock` | Reusable formal-write serialization inside a stable tree. | The lock file moves or disappears during deletion/rename; it cannot by itself serialize a DB commit against a whole-tree lifecycle command. |
| Root-stable per-project file lock | Can serialize cooperating filesystem commands across renames without a project-local inode. | It is not atomic with Task/attempt/backup DB commits and does not persist `DELETING`/`RETIRED` after a process stop. It could be a secondary file-operation guard. |
| PostgreSQL advisory lock | Transaction-scoped lock could coordinate participating SQL writers. | An advisory lock alone is not a durable lifecycle record or no-reuse tombstone; the key mapping and every caller still need governance. |
| Signed H6 capture fence | Proves an independently checked operator stop/quiescence window for capture. | The pure verifier does not acquire a runtime lock or reject new admissions; the approved service-stop evidence must cover every writer in its own gate. |
| Conditional lifecycle-row update plus domain write | One durable state check and transaction ordering for DB-backed admissions; a version is inspectable. | Requires a migration/bootstrap, all writer integration, legacy disposition, real PostgreSQL race tests, and a separate filesystem crash protocol. |

## Required race and crash evidence before selection

- Repository-integrated PostgreSQL, two connections: Task commit wins before delete intent;
  deletion sees and refuses it. Reverse order: admission waits, rechecks
  `state = LIVE`, and refuses without a Task row or replay receipt.
- Repeat those orders for attempt planning and backup `PREPARING` admission.
  An intentionally delayed backup media copy cannot hide an uncommitted
  admission from deletion; the new adapter must split/commit the short
  admission phase or otherwise prove safe ordering.
- Hold each process at delete intent commit, partial directory removal,
  absence before terminal marker, overwrite's old-tree rename and new-tree
  install, and v5-to-v6's two renames. Restart may reconcile only the exact
  intent/tree identity and cannot silently release the project name.
- Published legacy directory without lifecycle row; DB-only historical name;
  retired name with a new directory; mismatched deployment/name normalization;
  duplicate command ID; and a writer that omits the lifecycle update must
  each have a typed result.
- Validate the actual repository and migration on PostgreSQL. The scratch
  probe above is evidence for the database primitive only; SQLite unit tests
  may exercise pure state/error mapping but are not a concurrency acceptance
  gate.

## Open contract gates

1. Approve the source of `source_deployment_id`, normalization, bootstrap of
   existing published projects, and signed disposition for legacy DB-only
   names. No row should be minted from a bare directory or stale DB name.
2. Enumerate all project file and DB writers, including direct repository
   callers, generation workers, import, migration, profile/formal writes,
   GC and recovery. Either integrate them into the lifecycle boundary or
   prove they are stopped under the signed capture fence. The current source
   survey is positive and bounded, not an exhaustive allowlist.
3. Select the precise Task/attempt/backup/recovery-lease blockers and retained
   current-head disposition for deletion. The candidate above supplies
   ordering, not a complete retention policy.
4. Decide whether same-name archive overwrite is rejected in V1 or has a
   reviewed mapping for every retained DB authority/evidence row. Decide
   whether migration runs only in maintenance quiescence or gets a durable
   lifecycle intent.
5. Review the transaction API refactor: `TaskRepository.enqueue()` commits
   internally, while attempt planning and backup creation use different
   session boundaries. No production code should be wired from this note
   before one coherent writer protocol and adversarial tests are accepted.

## Bounded direct-writer follow-up

A current-worktree Python source sweep under `lib/`, `server/`, `r2/` and
`scripts/` found the runtime `TaskRepository.enqueue()` call in
`GenerationQueue.enqueue_task()` (`lib/generation_queue.py:459-482`). It also
found direct `Task(...)` construction in the offline legacy SQLite-to-ORM
migration (`scripts/migrate_sqlite_to_orm.py:118-142`). The latter is not a
normal runtime enqueue, but a V1 lifecycle bootstrap/migration run must
classify its imported project names and task statuses before treating them as
admitted live work. `ExecutionAttemptModel` insertion in the inspected
repository is `ExecutionAttemptRepository.plan()`
(`lib/db/repositories/host_hardening.py:188-207`); the bounded source search
found `BackupSetRepository` creation in the legacy `create_backup_set()`
helper (`r2/host_hardening/backup.py:256-285`) and its integration tests.

This is a positive writer lead, not an exhaustive negative claim about
dynamic SQL, other repositories, external tools or future code. The M7 graph
at generation `2026-09-18T10:57:40Z` has metadata-changed repository files,
does not track the new backup module, and excludes `scripts/`; the named
paths were read directly from this worktree. A release-pinned full writer
allowlist and all write directions remain an acceptance gate.
