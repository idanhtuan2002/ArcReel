# M8-C read-only schema preflight plan

Status: internal prerequisite after `8a1515cb`; no application startup wiring or migration policy change.

**Goal:** verify a PostgreSQL database is already at the single Alembic head shipped with the running image and has the grant head/event tables, without stamping or upgrading it.

**Interface:** `verify_governance_schema_ready(engine: AsyncEngine) -> str` in `server/services/governance_schema_preflight.py`. It rejects non-PostgreSQL engines; resolves the image's Alembic script head from the package location; starts a PostgreSQL read-only transaction; inspects the existing `alembic_version` table and required grant tables; reads exactly one revision and requires exact equality to the script head. Any missing, divergent or ambiguous state raises sanitized `GovernanceSchemaUnavailable`. It makes no schema or data writes and starts no workers.

- [x] Write PostgreSQL tests for migrated head, absent version/grant tables and stale revision; verify failures do not mutate rows/version.
- [x] Run RED at absent API.
- [x] Implement the preflight with a read-only transaction and no call to `init_db`/Alembic upgrade.
- [x] Run focused/affected tests and static/test-audit gates; update handoff and commit.

The actual activated lifespan must still obtain an approved custody manifest, call this preflight and full scanner before workers/routes, and prove denial on restored-old DB. This helper alone is not readiness authority.
