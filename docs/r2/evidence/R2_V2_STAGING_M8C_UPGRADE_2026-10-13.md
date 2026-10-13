# V2 staging: M8-C schema upgrade (2026-10-13)

Sponsor-approved. Steps, in order:

1. **Rehearsal on a copy.**
   - Staging (`arcreel-v2-staging-pg`, PostgreSQL 16, at `c9e1f4a2b701`) was dumped and restored into a disposable PostgreSQL 16 container.
   - The run on that container: `alembic upgrade head`, then `downgrade c9e1f4a2b701`, then `upgrade head`. All three passed and ended at `8c8c4a0e0001 (head)`.
   - All 82 existing tables kept identical row counts. The 8 new `m8_*` tables were created empty.
   - The container and dump were removed.
2. **Offline backup before the change.**
   - No staging server or worker was running.
   - Backup set `bs-20261013T091121Z` under `~/arcreel-v2-staging/backups/`:
     - state `COMPLETE`;
     - manifest `sha256:33b7c70ad9fd6c7369fd7a2ad5f3b3347be9cdf6e0befb3142e3f41f76aa11f8`;
     - captured at alembic `c9e1f4a2b701`;
     - 82 tables, 51 files;
     - release `c24ed8f9`.
   - The PostgreSQL 16 client wrappers live in `~/arcreel-v2-staging/pgbin`. The V1 trial wrappers do not mount the staging directory.
   - The backup set has **not** been restore-verified (`verify`/`attest` not run).
3. **Upgrade.** `alembic upgrade head` on staging: `c9e1f4a2b701 → 8a8c4a0e0001 → 8b8c4a0e0001 → 8c8c4a0e0001 (head)`.
4. **Canary not run.**
   - `qualify_route --provider gemini-aistudio --media text` stopped before any provider call with "API key is required".
   - The staging `provider_config` table is empty. The baseline came from the V1 no-provider backup.
   - The sponsor deferred live provider calls.

To roll back: restore `bs-20261013T091121Z` into an empty database with `scripts.r2.deployment_backup restore`, or run `alembic downgrade c9e1f4a2b701` (the M8 tables hold no rows).
