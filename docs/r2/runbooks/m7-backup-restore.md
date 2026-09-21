# M7-D Backup and Restore Runbook

Operator instructions for creating a database+media backup set
(`r2.host_hardening.backup.create_backup_set`) and restoring it into a
disposable or recovery target (`restore_backup_set` /
`verify_restored_backup_set`). This is the mechanism proven by
`docs/r2/evidence/R2_M7_D_RECOVERY_VERIFIED.json`.

## Preconditions (write fence)

`create_backup_set` proves, but does not itself enforce, that no candidate
was created/promoted/deleted while it ran (it fails closed with
`InconsistentRecoveryPointError` if the project's candidate count changes
mid-run). For a real production backup:

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
    database_url="postgresql+asyncpg://...",   # full DSN, never logged or stored
    media_root=Path("/data/media"),            # the live media root
    backup_dir=Path("/backups/bset-2026-09-21"),  # must not alias media_root
    source_deployment_id="prod-1",
    release_git_sha="<git rev-parse HEAD>",
    release_image_digest="sha256:...",
    configuration={"...": "..."},              # your own config fingerprint
    now=datetime.now(UTC),
)
```

`backup_dir` afterward contains `database.dump` (a `pg_dump --format=custom`
archive) and `media/` (a checksummed copy of every candidate object). Persist
`manifest` (e.g. as JSON) alongside `backup_dir` -- `restore_backup_set` and
`verify_restored_backup_set` both need it.

**Never store a raw `database_url` (with password) in the manifest, in
`backup_dir`, or in any log.** `create_backup_set` never does this itself;
do not add logging around it that would.

## Restoring into a target

The target database and target media root **must both already be empty** --
`restore_backup_set` refuses (`NonEmptyRestoreTargetError`) otherwise, and
refuses (`SourceTargetAliasError`) if the target media root is the same path
as `backup_dir`.

```python
from r2.host_hardening.backup import restore_backup_set, verify_restored_backup_set

await restore_backup_set(
    manifest=manifest,
    backup_dir=Path("/backups/bset-2026-09-21"),
    target_database_url="postgresql+asyncpg://...",  # a fresh, empty database
    target_session=target_session,                    # bound to that database
    target_media_root=Path("/restore/media"),          # a fresh, empty directory
)

verdict = await verify_restored_backup_set(
    manifest=manifest,
    session=target_session,
    media_root=Path("/restore/media"),
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
- Credentials are never part of a backup set: restoring one does not restore
  any provider API key or other secret. Re-provision those separately.
