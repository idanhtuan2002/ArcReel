# M8-C activated lifespan quarantine test plan

Status: source-backed plan at `75ef8f1016f6d567621497334d8b54c080879b93`; no startup implementation or test was added.

## Verified seam and coverage limit

In the current worktree `server/app.py:352-375`, `lifespan` performs environment/sandbox/log/auth setup, then unconditionally calls `init_db`. `init_db` may stamp or upgrade the schema, so it cannot precede the Governance restore comparison in an activated mode. Project/source/config migrations follow at `server/app.py:381-446`; telemetry/release setup and the HTTP client follow at `:448-454`; assistant, GenerationWorker, ProjectEventService and ExecutionRecoveryScheduler start at `:455-483`; route readiness starts only at the `yield` inside `remote_mcp_host.run` at `:485-486`.

The root graph generation is `2026-09-27T03:07:32Z`. Its `server.app.lifespan` snippet omits the current telemetry, release, event-stream and recovery-scheduler steps, even though `check_index_coverage` reports a matching root-file hash. This plan uses the exact worktree source read for ordering. Graph coverage on the root project does not establish freshness of this linked worktree.

## Candidate activated branch

The trust-input selection must be decided first. Once approved, add a narrow branch before `init_db` which resolves the operator-approved deployment record, validates actual registry/checkpoint bytes and their pinned digests, calls `verify_governance_schema_ready` read-only, then calls `GovernanceGrantRecoveryScanner.verify` with the fixed directory reader. Any failure must abort before `init_db`, project/config migrations, HTTP client startup, assistant or worker/scheduler startup, and before lifespan yields. Normal mode can retain its existing migration path. Activated mode must not call automatic stamp/upgrade after the scan; offline migration is a prerequisite. The branch must also construct and inject the checkpointed grant reader for every activated Governance-backed service.

The image digest is checked by the operator release preflight outside the container against the approved record. Supplying a digest string to the process is not image self-attestation. Application startup can verify only the approved trust input it receives and the custody bytes it reads; the release procedure must keep these boundaries separate.

## Required executable cases

1. Build a disposable PostgreSQL database at exact Alembic head; import signed ISSUE, capture a real `pg_dump`, import REVOKE and publish the newer signed checkpoint outside the dump. Restore the old dump to a clean database and invoke the **actual activated lifespan** against it. Assert the failure reason is sanitized; `init_db`, source/config migration, shared HTTP client, assistant startup, GenerationWorker start, ProjectEventService start, ExecutionRecoveryScheduler start and `remote_mcp_host.run` are not called; no response readiness occurs. Compare grant rows and Alembic version before/after.
2. Repeat denial with valid current DB but old signed checkpoint, missing checkpoint, malformed registry, wrong pinned registry digest, missing approved manifest and stale schema revision. The schema cases must not stamp or upgrade.
3. Use a current post-REVOKE database and matching latest checkpoint: lifespan may yield after gate success, but the revoked scope remains denied in a transaction-bound service call. Verify clean shutdown of started services.
4. Force importer-first and scan-first PostgreSQL ordering with backend PIDs/blocker evidence across startup. The scan must see a stable complete scope set; no partial startup may occur while it waits.
5. Run the current normal-mode startup tests unchanged; assert the activated branch never silently falls back to local-only grant verification or the normal `init_db` path when an input fails.

The existing `tests/unit/server/test_app_startup_migration.py` patches `init_db` and asserts project migration, so it is only a normal-mode characterization. The direct scanner/reader restore drill and service injection tests are prerequisites, not substitutes for these lifespan cases. Exact production Compose custody mount, archive medium, key rotation, full affected gate and independent exact-HEAD review remain open.
