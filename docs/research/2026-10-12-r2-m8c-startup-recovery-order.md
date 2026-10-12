# M8-C startup recovery ordering and schema readiness

Status: source-backed design candidate at `fc93034b9db057f93fa9df0775c2e8628c23d294`, 2026-10-12. No lifespan, migration, route, release mode or worker code changed.

## Current source order

`server/app.py`'s lifespan runs sandbox checks, log migration/handler setup and auth-password setup, then calls `init_db()` before source/project file migrations, session/config migrations, assistant startup, GenerationWorker, ProjectEventService and ExecutionRecoveryScheduler. `lib/db/__init__.py:init_db()` inspects the database, may stamp a pre-Alembic database, then calls `alembic.command.upgrade(..., "head")` in an executor. Thus a Governance recovery check inserted after `init_db()` would happen before workers but **after** schema migration and any data changes a migration might make.

The present Showrunner-grant migration `8f8c4a0e0001` creates grant head/event tables, constraints and FKs; the later review/V2 migrations create custody tables. Those exact current migrations were run on disposable PostgreSQL for the scanner and restore drills. This does not give a standing guarantee about later migrations. A future migration that backfills, deletes or rewrites grant rows could mask a restored older head before a post-`init_db()` scanner compares it to the external checkpoint. The current startup path also treats some later file/config migrations as nonfatal, so a Governance check must have a distinct fail-closed readiness boundary.

## Candidate activation order

Keep the existing automatic migration path for the current non-Governance mode. For a future explicitly enabled Governance mode, require a separate operator migration/preflight phase while the application/workers are stopped and the custody manifest is pinned. That phase must classify every pending migration for grant-state effects and retain exact schema/image/custody evidence. The activated application startup should:

1. Load the operator-approved deployment identity, image and registry/checkpoint digests from a trust input outside app-writable storage; reject missing or divergent inputs before any worker/route becomes ready.
2. Verify schema readiness **read-only** against the image's Alembic head and required grant tables, with no automatic `stamp` or `upgrade` in this path. A missing/newer/older schema denies startup.
3. Acquire the recovery scanner's exclusive cross-process import fence, reopen and verify the current signed checkpoint, enumerate every grant scope, and compare every complete signed chain/head exactly. Any failure aborts lifespan before file/config migrations, network clients, assistant startup and workers.
4. Only then continue the ordinary non-grant startup steps. Every Governance-backed request must still do a fresh transaction-bound checkpointed grant read; startup success is not an authorization cache.

An alternative would be to keep `init_db()` before the scan only while every migration in the activated image is proven grant-state-neutral and that fact is bound to the approved image manifest. That is narrower for an initial version but fragile under future migrations; the offline migration/read-only startup boundary is the preferred candidate for review.

## Required tests and unresolved decisions

- Force a restored pre-REVOKE database with a newer external checkpoint through the **actual lifespan** and assert no assistant/worker/recovery scheduler starts; repeat with missing/bad key, missing schema and stale Alembic version. The existing PostgreSQL restore drill called scanner/reader directly and did not test readiness.
- Prove the activated path performs no Alembic stamp/upgrade or grant write before the recovery check, and that a valid post-REVOKE restore reaches readiness while the revoked scope stays denied.
- Define exactly how the approved manifest and activation flag are supplied, and how a schema/image upgrade is rolled back without installing an older valid checkpoint. This packet does not choose an operator archive medium or authorize migration of a live database.
- Run full affected startup/backend checks and independent exact-HEAD review after implementation. Current production Compose still lacks a pinned image and custody mounts.

No license assessment is part of this packet.
