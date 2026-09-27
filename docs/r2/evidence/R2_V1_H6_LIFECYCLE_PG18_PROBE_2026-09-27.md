# R2 V1 H6 lifecycle-row PostgreSQL ordering probe

Date: 2026-09-27
Source branch/HEAD before probe: `feat/r2-m7e-v1-lineage` at
`c49a31f6`.
Purpose: test one database property used by the
[V1-01 candidate](../../research/2026-09-27-r2-m7-h6-project-lifecycle-protocol-options.md),
not accept a project lifecycle implementation.

## Isolated setup

An already-local `postgres:18-alpine` image was run as an ephemeral container
with `--rm --network none`, no host port and no user-supplied volume. It reported
`server_version=18.6` and `transaction_isolation=read committed`. The
container was stopped; `docker ps -a --filter name=codex-h6-v101-probe-20260927`
returned no entry afterward. No application database, project tree or provider
was accessed.

The only schema in its scratch `probe` database was:

```sql
CREATE TABLE lifecycle (
  name text PRIMARY KEY,
  state text NOT NULL,
  version integer NOT NULL
);
CREATE TABLE tasks (
  id text PRIMARY KEY,
  project_name text NOT NULL,
  status text NOT NULL
);
INSERT INTO lifecycle VALUES ('demo', 'LIVE', 1);
```

Before each case, `TRUNCATE tasks` and `UPDATE lifecycle SET state='LIVE',
version=1 WHERE name='demo'` reset the scratch state. Two separate `psql`
processes ran concurrently inside the container; a 0.25-second launch offset
placed the second process after the first had acquired the row lock. The
first transaction held its lock with `pg_sleep`, solely to make the ordering
observable.

Admission used one transaction with a conditional update and an insert from
its `RETURNING` row. Cases 2 and 3 also used `RETURNING id` on the insert to
show whether a Task was written:

```sql
BEGIN;
WITH admitted AS (
  UPDATE lifecycle
     SET version = version + 1
   WHERE name = 'demo' AND state = 'LIVE'
   RETURNING name
)
INSERT INTO tasks (id, project_name, status)
SELECT 'task-case', name, 'queued' FROM admitted;
COMMIT;
```

Deletion intent used `UPDATE lifecycle SET state='DELETING',
version=version+1 WHERE name='demo' AND state='LIVE'`, then read active Task
rows in the same transaction. Each run recorded `clock_timestamp()` before
and after the blocked update.

## Observations

| Order | Measured UTC timestamps and SQL result | Meaning within this probe |
| --- | --- | --- |
| Admission update and Task insert, then deletion intent | Admission lock at `01:39:05.689159`; deletion starts `01:39:05.938737`; admission reaches commit at `01:39:09.692809`; deletion update returns at `01:39:09.694491` and its next query counts `1` queued Task. Deletion transaction was rolled back for this probe. | Deletion waited for the same lifecycle row, then saw the Task committed by the earlier transaction. |
| Deletion intent, then admission | Deletion holds `DELETING` at `01:39:23.488090`; admission starts `01:39:23.738485`; deletion reaches commit at `01:39:27.491602`; admission returns at `01:39:27.493726` with `INSERT 0 0`. Final lifecycle is `DELETING`, version `2`, Task count `0`. | A waiting conditional admission did not insert after the committed state change. |
| Deletion intent rolled back, then admission | Deletion holds the row at `01:39:40.892945`; admission starts `01:39:41.143285`; after deletion rollback, admission returns `task-c` at `01:39:42.894765` with `INSERT 0 1`. Final lifecycle is `LIVE`, version `2`, Task count `1`. | A waiting admission resumed against the unchanged live state after rollback. |

These observations support the candidate's *database ordering* under
PostgreSQL 18.6 `READ COMMITTED`. They match PostgreSQL's documented rule
that a waiting `UPDATE` checks its `WHERE` predicate again on the committed
row version
([PostgreSQL 18 transaction isolation](https://www.postgresql.org/docs/18/transaction-iso.html)).

## Limits and next proof

- The probe used two scratch tables and SQL, not the repo's SQLAlchemy
  repositories, Alembic migration, command receipts, task queue or HTTP
  delete route. It did not simulate provider calls or filesystem removal.
- `INSERT 0 0` is a database result, **not** an application-level refusal.
  The eventual adapter must check exactly one admitted row and produce a typed
  failure with no Task/receipt; silent zero-row success would be a defect.
- No Task terminal transition, attempt plan, backup `PREPARING` row or
  concurrent archive/migration writer was included. Each needs the same
  integration-level two-connection proof after the writer protocol exists.
- The test proves nothing about ungoverned file writers, legacy project
  bootstrap, DB-only rows, no-name-reuse enforcement, signed capture-fence
  coverage, crash recovery, or exact restore authority. Those are separate
  V1-01/H6 gates.
