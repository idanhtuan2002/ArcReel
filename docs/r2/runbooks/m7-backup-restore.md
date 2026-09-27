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
| `manifest.json` | Release/schema identity, recovery point, per-table row counts, file inventory with SHA-256 digests, sanitized-table list, excluded entries, the non-secret configuration and its digest, fence evidence. |
| `state.json` | The set's lifecycle ledger: `PREPARING → COMPLETE → VERIFIED`, or `REJECTED` when capture fails. It is bound to the manifest digest. |
| `verdict.json` | The last restore target's automated checks. A failing target never changes the set's state. |
| `golden-evidence.json`, `attestation.json` | The Golden read/review/export evidence and the attestation that moved the set to `VERIFIED`. |

**Credentials never enter a set.** The following are handled at capture:

- **Credential columns blanked.** Blanked columns are
  `provider_credential.api_key/access_key/secret_key/credentials_path`,
  `agent_anthropic_credentials.api_key` and `custom_provider.api_key`.
- **Credential values blanked.** Values are blanked for `provider_config`
  rows marked `is_secret`. They are also blanked for `system_setting` keys
  whose final segment is a credential word: `api_key`, `secret`,
  `access_key`, `private_key`, `password`, `credential(s)`, `token`,
  `access_token`, `auth_token` or `refresh_token`. Counters such as
  `max_tokens` keep their values.
- **URL credentials stripped.** `user:password@` userinfo is removed from the
  `base_url` columns and from `provider_config` values.
- **Secret files excluded.** At the top of the `data` root, the capture
  excludes `.system_config.json`, `.system_config.json.bak`, the legacy
  `.arcreel.db*` SQLite files and `logs/`.
- **CLI credential files excluded.** A file named `.credentials.json` (the
  Claude CLI's OAuth store) is never captured, at any depth of any root.
- **Credential directory not captured.** `vertex_keys/` is not a root; do not
  add it.
- **Passwords kept off command lines.** Database passwords reach `pg_dump` and
  `pg_restore` through `PGPASSWORD` in the child environment, never on the
  command line.

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
- a sequence advanced;
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

## 3. Verify the restored target

```bash
uv run python -m scripts.r2.deployment_backup verify \
  --backup-dir /backups/bs-… \
  --target-root data=/srv/arcreel-restore/projects \
  --target-database-url-env ARCREEL_RESTORE_TARGET_URL \
  --target-release-git-sha "$(git rev-parse HEAD)" \
  --restore-target-id drill-2026-09-27-a
```

Verification checks the following:

- that the target release matches the set;
- the Alembic head;
- the exact per-table row counts;
- that no credential value is left in any sanitized column;
- every restored file's size and digest;
- that each `project.json` parses and every Artifact Manifest entry points to
  an existing file;
- that every resource's `current_version` (its selected master) names an
  existing version record, and that every version file exists;
- that every `assets`/`asset_derivatives` path resolves;
- that each selected media version decodes with `ffprobe` (`ffprobe` is
  required).

The result is written to `verdict.json`. The exit code is non-zero unless
`checks_passed` is true. A failing target leaves the set `COMPLETE`, so it can
still be restored into another clean target.

## 4. Golden review/export, then attest

Passing checks are not `VERIFIED` by themselves. On the restored target, run
the no-provider Golden A/B read, review and export for both V1 products. Record
the results as `GoldenRestoreEvidence` JSON, with this shape:

- `backup_set_id` and `manifest_digest` of this set;
- `restore_target_id`, the same label that was given to `verify`;
- `passed`;
- one product entry per product, each with `project_name`, `reviewed` and
  `export_digest`.

Product names must be distinct projects captured in this set, and at least
two are required.

Then attest:

```bash
uv run python -m scripts.r2.deployment_backup attest \
  --backup-dir /backups/bs-… \
  --golden-evidence golden-evidence.json \
  --measured-rpo-seconds <incident time − recovery_point> \
  --measured-rto-seconds <incident time → Golden export passed>
```

`attest` refuses in any of these cases, and the set stays `COMPLETE`:

- the recorded verdict did not pass for this manifest;
- the evidence belongs to another set, or to a different restore target than
  the verdict;
- fewer than two distinct products of this set passed read/review/export.

When it succeeds, it writes `attestation.json` and moves the set to
`VERIFIED`.

Only after `VERIFIED` should you start the restored application for use. Then:

1. Re-enter provider credentials in Settings.
2. Re-upload the Vertex credentials file if it is used.
3. Re-enter the Agent credentials.

Keep the restored target from reaching paid providers until credentials are
re-entered on purpose.

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
- **Attestation trusts the operator.** It records operator-supplied evidence
  and checks its consistency with the set and the recorded verdict; it does
  not sign anything. Its integrity rests on access control over the
  backup-set directory. A `VERIFIED` state without its matching
  `attestation.json` is refused at restore.
- **Golden run is not built in.** `attest` records Golden A/B evidence
  produced on the restored target; the tool does not run the Golden flow
  itself. The browser/operator workflow checks remain the E2 packet.
