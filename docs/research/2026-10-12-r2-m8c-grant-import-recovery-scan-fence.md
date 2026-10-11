# M8-C cross-process grant-import fence for recovery scans

Status: proposed transaction design research, 2026-10-12. No importer,
startup, migration, key, Compose or production behavior is changed here.

## Source and database facts

`GovernanceGrantImporter.import_event` verifies submitted bytes, then starts a
database transaction and inserts the scope head before locking it and
appending the event (`server/services/governance_grants.py:160-227`). The
current reader locks only one exact head
(`server/services/governance_grants.py:230-251`). A startup recovery scan must
compare *every* database scope to the external signed checkpoint; row locks on
the heads already returned by an enumeration do not fence insertion of an
entirely new scope.

The bounded direct source search of `server/`, `lib/` and `r2/` found grant
head/event model construction and head advancement only in the importer. Test
fixtures and external/privileged database writes are outside that claim. The
codebase-memory graph is stale for this module; its coverage report marked
`server/services/governance_grants.py` missing from the indexed generation, so
these findings rest on direct source reads and the bounded search.

PostgreSQL documents that `READ COMMITTED` is its default and separate
statements can observe different committed sets
([transaction isolation](https://www.postgresql.org/docs/current/transaction-iso.html#XACT-READ-COMMITTED)).
It also documents transaction-level advisory locks, shared/exclusive modes,
automatic release at transaction end, and separate 64-bit versus pair-of-32-bit
lock key spaces
([advisory lock behavior](https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS),
[advisory lock functions](https://www.postgresql.org/docs/current/functions-admin.html#FUNCTIONS-ADVISORY-LOCKS)).
Existing repo advisory locks in `lib/db/repositories/advanced_creative.py:152-159`
and `lib/db/repositories/task_repo.py:619-627` use a single 64-bit hashed text
key. Advisory locks are cooperative: a raw SQL writer that omits the protocol
is not fenced by this mechanism.

## Options and proposed lock order

| Option | Assessment |
| --- | --- |
| Lock only enumerated grant-head rows | Reject: a new scope has no row in that set and can commit during the scan. |
| Table-level `LOCK` against grant-head writes | Possible, but broad and coupled to DDL/ordinary queries; it needs a separate operational analysis before use. |
| Dedicated transaction-level advisory fence | Candidate: importer takes shared, startup scanner takes exclusive, while per-scope head locks retain their existing concurrency. |

Reserve one fixed two-integer advisory key for this authority, for example
`(0x4D384743, 1)` (`M8GC`, version 1). Its key space does not overlap the
repository's one-bigint advisory locks. Put the constant and both acquisition
functions in one reviewed module; do not compute a scope-dependent hash for
the global scan fence. PostgreSQL transaction-level acquisition must happen
inside the same transaction that performs the import or scan:

1. Importer: after parsing/verifying the submitted signed event and starting
   its transaction, acquire **shared global fence first**, then insert or lock
   the scoped head, recheck its chain, append the event and advance the head.
   The shared lock is held through commit/rollback. Different scopes may
   import concurrently; the exact head still serializes same-scope imports.
2. Startup/recovery scanner: acquire **exclusive global fence before** reading
   the checkpoint or enumerating any database head. Then read one complete
   verified checkpoint, enumerate the DB scope set, lock rows in sorted exact
   scope order, verify each full signed chain and require exact scope/head-set
   equality. Hold the exclusive lock until the comparison result is fixed.
   If the scan fails, startup remains closed.
3. Ordinary transaction-bound grant readers retain their existing source-lock
   order and per-scope grant-head lock. They do not acquire the global fence;
   otherwise a reader that holds other authority rows before the grant head
   could invert the scanner/importer order. They independently compare the
   locked scope head to a fresh signed checkpoint before authorizing.

The exclusive scanner waits for in-flight shared importers to finish; new
importers wait for the scanner. Under `READ COMMITTED`, enumeration after the
exclusive acquisition sees imports committed before its statement began.
Because compliant importers cannot insert during the exclusive hold, it cannot
miss a concurrently inserted scope. The importer must acquire the global
shared lock *before* any head insert or row lock. A scan against a live DB
cannot protect against privileged raw SQL writes that ignore the protocol;
restore operations therefore still require a stopped/quarantined target and
restricted database write authority.

## Required proof before use

- On disposable PostgreSQL, hold a first import's shared fence and prove the
  scanner's exclusive acquisition waits on that backend PID; after commit,
  the scanner enumerates the new scope and rejects an old checkpoint.
- Hold the scanner's exclusive fence before enumeration and prove a new-scope
  import waits before its first head insert; after release, import commits and
  that scope remains unavailable until its checkpoint advances.
- Prove two different-scope importers can hold shared fences concurrently;
  prove rollback releases a shared lock and leaves no empty committed head.
- Force a normal reader during both schedules to detect any lock-order cycle.
  Use `pg_blocking_pids`, bounded timeouts and task cleanup in `finally`.
- Production recovery gate must fail closed if the database lacks the required
  PostgreSQL fence semantics. SQLite unit tests may exercise the pure
  checkpoint contract but cannot stand in for this cross-process proof.

This packet does not resolve the operator-held key registry, atomic directory
publication, startup Alembic ordering, full-chain scanner implementation,
restore drill, or production activation. Those remain separate gates under
the [checkpoint custody spec](../superpowers/specs/2026-10-12-r2-m8c-governance-checkpoint-custody-design.md).
