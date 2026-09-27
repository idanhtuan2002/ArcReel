# V1 Deployment Backup and Restore Runbook

This is the V1 H6 procedure (ADR-0078, ADR-0090). It uses one **whole-deployment
backup set**: one PostgreSQL recovery point plus every regular file under the
deployment's data roots, captured under an **offline fence**. The mechanism is
`r2.host_hardening.deployment_backup`. The operator entry point is
`scripts/r2/deployment_backup.py`.

The historical `docs/r2/evidence/R2_M7_D_RECOVERY_VERIFIED.json` described the
earlier project-scoped mechanism. That mechanism has been removed, and the
file is not evidence for this procedure.

## What a backup set contains

A backup set is one directory:

| Path | Content |
|---|---|
| `database.dump` | `pg_dump --format=custom` of the whole database. Data of credential-bearing tables is excluded. |
| `sanitized/<table>.copy` | A binary COPY of each credential-bearing table, with its credential columns blanked. |
| `files/<root>/…` | Every regular file under each named root, digest-checked on copy. |
| `manifest.json` | Release/schema identity, recovery point, per-table row counts, file inventory with SHA-256 digests, sanitized-table list, excluded entries, fence evidence. |
| `state.json` | The set's lifecycle ledger: `PREPARING → COMPLETE → VERIFIED` or `REJECTED`, bound to the manifest digest. |
| `verdict.json` | The last clean-target verification result. |

**Credentials never enter a set.** The following are handled at capture:

- **Credential columns blanked.** Blanked columns are
  `provider_credential.api_key/access_key/secret_key/credentials_path`,
  `agent_anthropic_credentials.api_key` and `custom_provider.api_key`. Blanked
  values are `provider_config.value` for `is_secret` rows and
  `system_setting.value` for keys matching
  `api_key|apikey|secret|token|password|credential`.
- **Secret files excluded.** At the top of the `data` root, the capture
  excludes `.system_config.json`, `.system_config.json.bak`, the legacy
  `.arcreel.db*` SQLite files and `logs/`.
- **Credential directory not captured.** `vertex_keys/` is not a root; do not
  add it.

A set still holds project content (scripts, prompts, media). Store it with
access control as sensitive data. It is not "secret-free".

## Data roots

- **`data` (required).** The application data directory: `ARCREEL_DATA_DIR`,
  or `projects/` in the Compose deployment. It holds every project,
  `_global_assets/` and runtime state files.
- **Optional extra roots.** Name any other directory the deployment persists
  and wants restored, for example the Agent session store mounted at
  `claude_data`. A directory that is not named is not captured.

Capture refuses symlinks, sockets and other non-regular entries under a root
(`UNSUPPORTED_FILE_ENTRY`); resolve them before retrying.

## 1. Create (offline fence)

1. **Stop the application and worker.** Stop the application server; the
   generation worker runs in-process. V1 has no automated maintenance mode.
2. **Drain the queue first.** Capture refuses while any Task is `queued`,
   `running` or `cancelling`. Let work finish, or cancel it, before stopping
   the application.
3. **Run the capture:**

   ```bash
   export ARCREEL_BACKUP_SOURCE_URL='postgresql://…'   # never passed on argv
   uv run python -m scripts.r2.deployment_backup create \
     --backup-set-id bs-$(date -u +%Y%m%dT%H%M%SZ) \
     --backup-dir /backups/bs-… \
     --root data=/srv/arcreel/projects \
     --database-url-env ARCREEL_BACKUP_SOURCE_URL \
     --deployment-id prod-1 \
     --release-git-sha "$(git rev-parse HEAD)" \
     --release-image-digest sha256:… \
     --configuration-json /srv/arcreel/non-secret-config.json
   ```

The command fails closed, and marks the set `REJECTED` with
`OFFLINE_FENCE_VIOLATED`, in any of these cases, whether seen before or after
the copy:

- another client session is connected to the database;
- a Task is active;
- the database write counter moved;
- the data-root file fingerprint changed.

On success it prints the manifest digest and recovery point. Restart the
application afterwards.

## 2. Restore into a clean target

The target database must have no tables. Every target root must be an empty
or absent directory that does not overlap the backup set. Restore first checks
the ledger state (`COMPLETE`/`VERIFIED`), the manifest digest and the digest
of every payload file. It changes nothing if any of these checks fails.

```bash
export ARCREEL_RESTORE_TARGET_URL='postgresql://…/fresh_empty_db'
uv run python -m scripts.r2.deployment_backup restore \
  --backup-dir /backups/bs-… \
  --target-root data=/srv/arcreel-restore/projects \
  --target-database-url-env ARCREEL_RESTORE_TARGET_URL
```

Restore runs `pg_restore` pre-data and data, then loads the sanitized tables,
then runs post-data, so constraints are validated against the complete data.
It prints the elapsed seconds; record them for the RTO.

## 3. Verify, then re-enter credentials

```bash
uv run python -m scripts.r2.deployment_backup verify \
  --backup-dir /backups/bs-… \
  --target-root data=/srv/arcreel-restore/projects \
  --target-database-url-env ARCREEL_RESTORE_TARGET_URL \
  --measured-rpo-seconds <incident time − recovery_point> \
  --measured-rto-seconds <restore start → verify end>
```

Verification checks the following:

- the Alembic head;
- the exact per-table row counts;
- that no credential value is left in any sanitized column;
- every restored file's size and digest;
- that each `project.json` parses and each `versions/versions.json` version
  file exists;
- that every `assets`/`asset_derivatives` path resolves;
- that each selected (current) media version decodes with `ffprobe`
  (`ffprobe` is required).

The result is written to `verdict.json`, and `state.json` moves to `VERIFIED`
or `REJECTED`. The exit code is non-zero unless the set is `VERIFIED`.

Only after `VERIFIED` should you start the restored application. Then
re-enter provider credentials in Settings, re-upload the Vertex credentials
file if it is used, and re-enter the Agent credentials. Keep the restored
target from reaching paid providers until credentials are re-entered on
purpose.

## Client/server version compatibility

`pg_dump`/`pg_restore` must be compatible with the server's major version. A
newer client can emit session setup that an older server rejects. For example,
PG18 `pg_restore` sends `SET transaction_timeout = 0`, which PG16 lacks. Keep
the installed `postgresql-client` on the server's major version. The Compose
deployment uses the floating `postgres:18-alpine` tag; pin the exact image
digest in the deployment before relying on restores across upgrades.

## Limits (V1)

- **Planned downtime.** The offline fence stops the application for the
  duration of capture.
- **Snapshot only.** A backup set is a snapshot at `recovery_point`. There is
  no PITR.
- **Credentials re-entered by the operator.** Credentials are re-entered after
  restore; there is no encrypted credential custody.
- **Golden review/export is separate.** The no-provider Golden A/B review and
  export on the restored target, and the browser checks, belong to the E2
  packet. They are not part of `verify`.
