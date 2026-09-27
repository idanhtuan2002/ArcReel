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

### Candidate task-state gate for a quiescent H6 capture

The current Task active set is `queued`, `running`, `cancelling`
(`lib/db/repositories/task_repo.py:31,54-61`). A running video task can be
between local staging, checkpoint persistence and provider job-ID persistence.
On restart, `classify_video_resume_state()` treats checkpoint-without-job as
unresumable, while a valid checkpoint/job pair is `READY` for provider polling
(`lib/reference_video/execution_checkpoint.py:997-1016`). The resume executor
does not reopen staged provider inputs and removes staging on exit
(`server/services/resume_executor.py:96-166,232-239`). Worker restart cancels
`cancelling` tasks, marks unresumable running tasks failed, and dispatches
eligible submitted jobs (`lib/generation_worker.py:1115-1299`). A task marked
`failed` may later return to `running` through artifact-download retry
(`lib/db/repositories/task_repo.py:665-717`). These are execution behaviors,
not a lifecycle capture predicate.

Candidate V1-01 rule: a project with any `queued`, `running` or `cancelling`
Task blocks exact quiescent capture until a reviewed fence proves those tasks
terminal or a separate in-flight recovery protocol is accepted. Do not infer
capture eligibility from `READY`, `provider_job_id`, worker inactivity or
staging-directory presence. The fence must also prevent a failed-to-running
retry from entering between the task census and DB dump. Terminal task rows
and their checkpoints remain historical DB bytes; any project-local staging
left behind gets an explicit physical-census/orphan disposition, not a
checkpoint-based requirement to reconstruct or delete it. Fixtures must race
capture with enqueue, first submit, cancel, orphan recovery and
artifact-download retry, including a checkpoint/job pair with no staging.
This gate is a design candidate pending complete writer enumeration and
sponsor review; it does not authorize a production capture path.

The current retry writer is a separate admission seam: the HTTP
`/tasks/{task_id}/retry-download` route calls `GenerationQueue`, then
`TaskRepository.retry_artifact_download()` commits the `ApiCall` reopen and
Task `failed -> running` update before the worker dispatches polling
(`server/routers/tasks.py:192-207`; `lib/generation_queue.py:872-874`;
`lib/db/repositories/task_repo.py:665-717`). A future V1-01 lifecycle check
must participate in that same repository transaction; a route-only check
would leave a race and a post-commit dispatch failure can leave `running`
without an in-process poller. This is a positive writer finding, not a
complete task-writer inventory.

A bounded literal search for `update(Task)`, `insert(Task)`, `delete(Task)` and
`Task(` under `lib/`, `server/`, `r2/` and `scripts/` also found a direct
worker SQL write outside `TaskRepository`: `_requeue_single_task()` commits a
guarded `running -> queued` update using `safe_session_factory()`
(`lib/generation_worker.py:758-799`). The repository's manual
`requeue_running()` operation can perform the same transition for a batch
(`lib/db/repositories/task_repo.py:1220-1257`). Neither route admits new task
identity, but both mutate the active-task census and therefore must be
stopped or included in the signed capture fence. The direct-worker write is
easy to miss if lifecycle integration reviews only `TaskRepository` methods.
This search covers those literal Python forms in the stated paths, not dynamic
SQL, external jobs, or all status transitions.

### Bounded Task writer and capture-fence matrix

The current-worktree Task writer paths below are distinct transaction seams.
`ACTIVE_TASK_STATUSES` is `queued`, `running`, `cancelling`; a zero active-row
count at one instant is not a writer fence. Every listed writer needs either
participation in an approved lifecycle transaction or proof that the signed
capture window stops it. The latter must include worker threads and operator
scripts, not only HTTP admission.

| Write family | Current source and write boundary | Capture implication |
| --- | --- | --- |
| New queued task, including dedupe/receipt path | `TaskRepository.enqueue()` constructs `Task(status="queued")` and commits its task/receipt transaction (`lib/db/repositories/task_repo.py:220-337`). `GenerationQueue.enqueue_task()` is the normal runtime caller (`lib/generation_queue.py:459-482`). | Admission must fail or wait while a capture fence owns the project identity; checking the route before repository commit is insufficient. |
| Claim and local requeue | `claim_next()` commits `queued -> running` (`lib/db/repositories/task_repo.py:526-613`); worker `_requeue_single_task()` commits `running -> queued` directly; repository `requeue_running()` commits a batch (`lib/generation_worker.py:758-799`; `lib/db/repositories/task_repo.py:1220-1257`). | All states remain active, but DB row versions and worker ownership change. Include direct worker SQL and any use of the manual rescue method in the fence. |
| Cancel, cascade and terminal settlement | `cancel_task()` commits queued cancellation or `running -> cancelling`; `finalize_cancelled()` commits the final transition and may cascade; `cancel_all_queued()` commits a project-wide update; success/failure methods commit terminal changes and dependent failures (`lib/db/repositories/task_repo.py:616-664,714-765,834-865,922-1003,1143-1168,1177-1218`). | Terminalization can change both Task and event/dependent rows while files are being finalized or removed; a fence cannot rely only on blocking new tasks. |
| Failed download retry | The repository reopens `ApiCall` and commits `failed -> running` before worker dispatch (`lib/db/repositories/task_repo.py:665-712`; `server/routers/tasks.py:192-207`). | A previously terminal row can become active after a census unless the retry transaction participates in the lifecycle fence. |
| Same-status execution facts | `persist_execution_checkpoint()` commits the pre-submit checkpoint with a running/no-job guard; `persist_provider_job_id()`, payload merge and provider projection also commit independently (`lib/db/repositories/task_repo.py:1030-1134`). | An unchanged `running` status or active-row count does not prove a stable backup DB image or matching staging tree. Version/fence checks must cover these row values. |
| Offline legacy import | `migrate_sqlite_to_orm.py` inserts Task rows carrying imported statuses (`scripts/migrate_sqlite_to_orm.py:118-142`). | Exclude the importer from a live capture by a signed maintenance stop or integrate its project identities into bootstrap; ordinary runtime enqueue rules do not cover it. |
| Schema migration and downgrade | Two Alembic downgrades directly cancel duplicate active tasks; an endpoint migration backfills provider columns without changing status (`alembic/versions/e167b56a3e79_add_resource_type_column_to_tasks_for_.py:28-64`; `alembic/versions/7f2c4d8a91b3_scope_task_dedup_by_user.py:53-81`; `alembic/versions/b3f9c07ae214_split_task_endpoint_and_base_url.py:31-58`). | A live schema migration or downgrade is outside the ordinary repository admission paths. The capture protocol must require a proven maintenance stop and compatible schema pin, not treat it as an invisible background writer. |

This table is a bounded positive source inventory for the shown Python paths,
not a complete release allowlist. It does not prove that every SQL writer,
file finalizer, process or deployment job participates. The project/deployment
identity and signed stop protocol remain open V1-01 gates.

### Attempt and backup-row writer leads

`ExecutionAttemptModel` enforces a terminal timestamp exactly for
`SUCCEEDED`, `FAILED_BEFORE_ACCEPTANCE`, `FAILED` and `CANCELLED`; every other
state, including `NEEDS_OPERATOR`, is non-terminal
(`lib/db/models/host_hardening.py:42,50-81`;
`r2/contracts/host_hardening.py:20-33,98-105`). The repository can insert a
`PLANNED` row, advance worker/provider/operator/cancel state, or change its
lease version without changing state (`lib/db/repositories/host_hardening.py:188-235,265-402,446-725`). The service built by
`build_execution_attempt_service()` passes `session.commit` and commits
planning, leasing and transitions in separate phases around provider work
(`server/services/execution_attempts.py:99-114`;
`r2/host_hardening/execution.py:111-188`). A V1-01 capture predicate cannot
equate a terminal Task with a terminal attempt, or infer no writer from an
unchanged attempt state. Candidate quiescent capture blocks every non-terminal
attempt in the scoped project and requires the fence to stop new planning,
lease, observation and operator writes; the exact retention and recovery
disposition remains a review gate.

`BackupSetModel` allows `PREPARING`, `COMPLETE`, `VERIFIED` and `REJECTED`
(`lib/db/models/host_hardening.py:419-438`). The existing M7-B
`BackupSetRepository` insert and media-ref methods only flush; `mark_state()`
updates the row without committing (`lib/db/repositories/host_hardening.py:1100-1128`).
The legacy `create_backup_set()` helper inserts `PREPARING`, then copies media
and runs `pg_dump` before marking `COMPLETE` or `REJECTED` in the supplied
session (`r2/host_hardening/backup.py:256-334`). Its own docstring requires
application/worker stop. Thus another transaction cannot be assumed to see
that helper's `PREPARING` row while it copies. The H6 adapter needs a separately
committed, fenced admission or equivalent reviewed ordering; the legacy
helper is reuse evidence, not the approved production V1 capture protocol.
No rule here treats a historical `COMPLETE` or `VERIFIED` row as proof that
the source project is live.

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

## Legacy bootstrap and deployment identity: bounded decision matrix

The candidate lifecycle key needs an authoritative `source_deployment_id`
before any existing name can be registered. `RecoveryConfigV1` parses a
caller-supplied logical ID and fingerprints canonical configuration bytes
(`r2/contracts/recovery_config.py:81-102,130-139`); it does not establish that
the value belongs to the running DB and project root. In a bounded literal
search of `lib/`, `server/`, `r2/` and `deploy/`, no runtime resolver for that
binding was found. This is an unresolved trust anchor, not a claim that no
external deployment registry exists. A proposed bootstrap must bind an
independently controlled deployment identity, DB identity and project-root
identity in signed, reviewable evidence; it must reject a caller-selected ID
that conflicts with that binding.

`ProjectManager.normalize_project_name()` strips surrounding whitespace and
accepts only ASCII letters, digits and hyphens
(`lib/project_manager.py:97,315-322`). A filesystem census must preserve each
raw entry name before applying normalization: a raw name that changes under
normalization, fails validation, collides after normalization, is a symlink,
or is hidden must be classified explicitly, never silently dropped.
`list_projects()` merely returns visible directories and does not validate
metadata (`lib/project_manager.py:388-390`).

| Observed source state before lifecycle rows exist | Candidate bootstrap treatment | Required evidence or unresolved decision |
| --- | --- | --- |
| Exact valid name, ordinary directory, complete supported `project.json`, no unresolved sibling/intent | Propose `LIVE`, subject to independent review of the full census and DB references. | Capture the exact tree identity and metadata bytes; check completeness and current migration verdict without a write. `project_exists()` or schema version alone is insufficient. |
| Directory with only minimal metadata, missing/corrupt metadata, or unpublished Agent creation | Hold as `UNPUBLISHED_OR_DAMAGED`; do not mint `LIVE` or infer `RETIRED`. | HTTP creation writes a minimal `project.json` before full metadata (`server/routers/projects.py:687-716`; `lib/project_manager.py:400-438`). Distinguishing interrupted creation from later damage requires inspection. |
| Complete older schema or unresolved migration verdict/swap sibling | Hold for migration disposition; do not mutate it during the census. | `project_schema_is_current()` checks only the strict version (`lib/project_schema.py:10-27`); `DataValidator.validate_project_dir()` checks payload but does not establish publication (`lib/data_validator.py:734-748`). Startup migration can write backups, migrate and reclaim swaps (`lib/project_migrations/runner.py:166-191,242-269`). |
| DB rows with exact name but no admitted directory | Hold as `LEGACY_DB_ONLY`; retain the rows and refuse liveness inference. | An inspected, signed row-level disposition across all users and current heads is needed. Filesystem absence does not prove historical retirement; see the [liveness map](2026-09-26-r2-m7-h6-project-liveness-map.md). |
| Directory and DB rows with the same name but conflicting ownership, deployment or unresolved historical identity | Hold as `IDENTITY_CONFLICT`. | Filesystem project names are global while domain rows may be user-scoped. Review all scoped row IDs and their meaning before binding them to one lifecycle identity. |
| Hidden import backup, migration staging/rollback sibling, deletion/replacement intent, or retained retired name | Block bootstrap and capture for the affected identity. | Inspect the exact command/tree lineage; do not run startup reclaim during a read-only census or treat a present directory as fresh creation. |

The table is a proposal for review, not an implemented admission algorithm.
An approved bootstrap would first stop every project writer under a signed
fence, then produce a reproducible manifest of raw root entries, normalized
names, file identities, DB row IDs/states across users, migration verdicts,
hidden siblings and preexisting intents. It would bind that manifest and the
deployment/root identities to a reviewer disposition before inserting any
rows. A crash or rerun must compare the same manifest/command digest and
refuse changed inputs; a batch insert cannot guess `LIVE` from a directory or
`RETIRED` from absence. The exact signed format, bootstrap transaction,
failure taxonomy and independent review are still open gates.
