# M7-D Backup and Restore Runbook

Instructions for a **disposable drill of the current mechanism**, not an
approved production backup or H6 recovery-closure procedure. They describe
creating a database+media backup set
(`r2.host_hardening.backup.create_backup_set`) and restoring it into a
disposable clean target (`restore_backup_set` /
`verify_restored_backup_set`). The historical
`docs/r2/evidence/R2_M7_D_RECOVERY_VERIFIED.json` records a human/self
override, not independent acceptance of the current H6 requirement. The
[H6 closure design](../../superpowers/specs/2026-09-25-r2-v1-m7d-recovery-closure-design.md)
is a draft, not implemented behavior.

**Secret-bearing archive:** this function dumps the whole PostgreSQL database
to an unencrypted `database.dump`, including rows that may contain provider
API keys and other credentials. Its media copy and manifest are also local
files; the implementation does not encrypt, sign or place them in an immutable
custody repository. Use only disposable source data and credentials in a
restricted, short-lived test location. Do not use this runbook for a production
backup or restore; a production procedure requires approved custody,
implementation and the remaining H6 acceptance gates.

## Preconditions (write fence)

`create_backup_set` expects an operator write fence but does not enforce it.
It fails with `InconsistentRecoveryPointError` if the selected project's
candidate count changes mid-run. That count check cannot detect every
creation/deletion pair, promotion, DB or file edit, or prove a
deployment-wide consistent snapshot. For a disposable drill:

1. Stop the application server and `GenerationWorker` (or otherwise pause
   traffic) before starting the backup. This is a manual step -- V1 does not
   include an automated maintenance-mode toggle.
2. Confirm no background job (recovery scanner, cleanup cron) is mid-write.

## Creating a backup set

```python
from pathlib import Path
from datetime import UTC, datetime
from r2.host_hardening.backup import create_backup_set

manifest = await create_backup_set(
    session=session,                          # bound to the source database
    user_id="...", project_name="...",
    backup_set_id="bset-2026-09-21",           # unique, operator-chosen
    database_url="postgresql+asyncpg://...",   # disposable credential only
    media_root=Path("/disposable/media"),      # disposable source media
    backup_dir=Path("/disposable/backups/bset-2026-09-21"),
    source_deployment_id="disposable-1",
    release_git_sha="<git rev-parse HEAD>",
    release_image_digest="sha256:...",
    configuration={"...": "..."},              # your own config fingerprint
    now=datetime.now(UTC),
)
```

`backup_dir` afterward contains `database.dump` (a `pg_dump --format=custom`
archive) and `media/` (a checksummed copy of the selected project's candidate
objects). Both may contain sensitive data. Persist
`manifest` (e.g. as JSON) alongside `backup_dir` -- `restore_backup_set` and
`verify_restored_backup_set` both need it.

**Never store a raw `database_url` (with password) in the manifest, in
`backup_dir`, or in any log.** The current implementation passes source and
target URLs to `pg_dump`/`pg_restore` as subprocess arguments; do not supply
production passwords or assume that excluding URLs from the manifest protects
process arguments.

## Restoring into a target

The target database and target media root **must both already be empty** --
`restore_backup_set` refuses (`NonEmptyRestoreTargetError`) otherwise, and
refuses (`SourceTargetAliasError`) if the target media root is the same path
as `backup_dir`.

```python
from r2.host_hardening.backup import restore_backup_set, verify_restored_backup_set

await restore_backup_set(
    manifest=manifest,
    backup_dir=Path("/disposable/backups/bset-2026-09-21"),
    target_database_url="postgresql+asyncpg://...",  # a fresh, empty database
    target_session=target_session,                    # bound to that database
    target_media_root=Path("/disposable/restore/media"),  # a fresh, empty directory
)

verdict = await verify_restored_backup_set(
    manifest=manifest,
    session=target_session,
    media_root=Path("/disposable/restore/media"),
    now=datetime.now(UTC),
    measured_rpo_seconds=...,   # your own measured timing, not assumed
    measured_rto_seconds=...,
)
assert verdict.accepted, verdict.reason_codes
```

`verdict.accepted` is `False` if the restored schema's Alembic head does not
match the manifest, or if any media file is missing, wrong-sized, or
digest-mismatched -- `verdict.reason_codes` names each failure.

## Client/server version compatibility

`pg_dump`/`pg_restore` are libpq client tools: their major version must be
compatible with the target PostgreSQL server's major version. A newer
client can emit session setup an older server rejects (observed: a PG18
`pg_restore` unconditionally sends `SET transaction_timeout = 0`, a GUC
PG16 does not have, failing the restore with a nonzero exit even though the
data itself would have restored correctly). Keep the `postgresql-client`
package installed on any host that runs these functions tracking the actual
PostgreSQL server's major version.

## Operational limits (V1)

- No point-in-time recovery (PITR): a backup set is a snapshot at its
  `recovery_target` timestamp, not a continuous log. PITR is an optional
  production-candidate profile for a later milestone, never assumed here.
- No automated write-fence: see Preconditions above.
- The whole-database dump includes credential-bearing tables. A restore can
  reintroduce captured secrets; use disposable credentials and keep the
  restored target isolated from production egress. The draft H6 design requires
  a separately approved encrypted custody and isolated-restore procedure.
