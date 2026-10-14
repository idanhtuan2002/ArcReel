# Governance activation runbook (ADR-0103)

This runbook turns on human pair review for spatial shots: the review session, the MASTER/REVERSE pair decision and the spatial promotion. Until it is done, those routes return 503 `m8_spatial_review_unavailable` and the Shots page says review is not active.

It is the operator's side of [ADR-0103](../../adr/0103-showrunner-grants-and-spatial-review-custody.md). The record formats and the publication rules come from:
- the [host record and publication contract](../../superpowers/specs/2026-10-12-r2-m8c-host-record-and-publication-contract.md);
- the [startup attestor design](../../superpowers/specs/2026-10-13-r2-m8c-startup-attestor-design.md).

The tools are `scripts/r2/governance_ceremony.py` and `scripts/r2/governance_preflight.py`.

## Roles and places

| Place | What runs there | What it holds |
|---|---|---|
| **Signing machine**: offline, never networked to the host | `governance_ceremony.py keygen`, `registry`, `approve`, `genesis-body`, `sign-checkpoint`, `sign-event` | The two private keys. They never leave this machine. |
| **Host**, as root | `governance_ceremony.py enroll`, `import-event`, `next-body`, `publish`; `governance_preflight.py preflight`, `serve` | The custody root (`archive/` + `read/`), the attestor socket and the database |
| **Application container** | ArcReel | Read-only `read/` and the read-only attestor socket directory; no key and no `archive/` |

Files move between the signing machine and the host on removable media or another channel you control. Only public files and signed records travel; a private key never does.

**Host commands need:**
- effective root;
- the database URL in an environment variable (`--database-url-env`, default `DATABASE_URL`), never on the command line;
- the application **and its in-process worker stopped**, because grant administration is offline (contract, "Initial enrollment").

## 0. Decide the identifiers

Pick these once and record them in the deployment log. Identifiers use the registry grammar: short, no spaces.

- `DEPLOYMENT_ID`, for example `prod-1`.
- `GRANT_KEY_ID`, for example `grant-2026-10`, and `CHECKPOINT_KEY_ID`, for example `checkpoint-2026-10`. They must be different keys.
- `OPERATOR_ID`: an audit label for who ran the ceremony. It is not proof of authority.
- `CUSTODY_ROOT`: an absolute host path that does not exist yet, for example `/srv/arcreel-governance`. Use a root-owned filesystem that is included in your independent backups.
- `ATTESTOR_DIR`: an absolute host directory for the socket, for example `/run/arcreel-attestor`, root-owned with mode `0700`.
- The reviewer scope for each showrunner:
  - `user_id`: `default` in the single-user deployment;
  - `project`: the project name;
  - `principal`: the reviewer's login name, which is the `sub` of their session.

## 1. Create the two keys (signing machine)

```bash
uv run python -m scripts.r2.governance_ceremony keygen --private grant.key --public grant.pub
uv run python -m scripts.r2.governance_ceremony keygen --private checkpoint.key --public checkpoint.pub
```

- **Check:** both `.key` files have mode `0600`. Keep them, and an offline copy, as you would any signing key. The command refuses to overwrite an existing file.
- **Stop if:** either key was ever on a networked machine. Generate new ones.

## 2. Build the verifier registry (signing machine)

```bash
uv run python -m scripts.r2.governance_ceremony registry \
  --deployment-id "$DEPLOYMENT_ID" \
  --grant-key-id "$GRANT_KEY_ID" --grant-public grant.pub \
  --checkpoint-key-id "$CHECKPOINT_KEY_ID" --checkpoint-public checkpoint.pub \
  --out registry.json
```

The output prints the registry digest. Record it.

## 3. Pin the image and approve the deployment

Activation needs an exact image digest, not the floating `arcreel/arcreel:latest`.

1. **On the host,** after pulling the release you will run:

   ```bash
   docker image inspect --format '{{index .RepoDigests 0}}' arcreel/arcreel:<release-tag>
   docker image inspect --format '{{.Os}}/{{.Architecture}}' arcreel/arcreel:<release-tag>
   ```

2. **On the signing machine**, with `registry.json`:

   ```bash
   uv run python -m scripts.r2.governance_ceremony approve \
     --registry registry.json \
     --image-ref 'arcreel/arcreel@sha256:<digest>' --image-platform linux/amd64 \
     --operator-id "$OPERATOR_ID" --out approved.json
   ```

3. **In the deployment's `docker-compose.yml`,** set `image: arcreel/arcreel@sha256:<digest>`. Use the same reference.

- **Stop if:** the running container's image digest differs from `approved.json`. Changing the image later needs a new approval, and the publisher accepts only approval sequence 1. A second approval is a separately reviewed continuity ceremony and is not supported by these tools yet.

## 4. Sign the genesis checkpoint (signing machine)

```bash
uv run python -m scripts.r2.governance_ceremony genesis-body --registry registry.json --out genesis.body
uv run python -m scripts.r2.governance_ceremony sign-checkpoint --key checkpoint.key --body genesis.body --out genesis.json
```

Carry `registry.json`, `approved.json` and `genesis.json` to the host. Leave the keys behind.

## 5. Enroll the genesis archive (host, application stopped)

The database must be at the application's current schema (run the normal migration before this step) and must contain **no** grant yet.

```bash
export DATABASE_URL='postgresql+asyncpg://…'
sudo -E uv run python -m scripts.r2.governance_ceremony enroll \
  --root "$CUSTODY_ROOT" --registry registry.json --approved approved.json \
  --checkpoint genesis.json --operator-id "$OPERATOR_ID"
```

`enroll` performs these steps:
1. Creates `CUSTODY_ROOT` with:
   - `archive/` (mode `0700`): `approved/`, `registries/`, `high-water/`, `checkpoints/`, `.staging/` and `.publisher.lock`;
   - `read/` (mode `0755`).
2. Writes the retained records create-once and the four public copies.
3. Runs the full operator preflight.

- **Check:** the output says `enrolled; checkpoint sequence 1`.
- **Stop if:**
  - `CUSTODY_ROOT` already exists. Enrollment never reuses a tree.
  - The ledger is not empty, because a nonempty ledger needs a separately reviewed import ceremony.
  - Any refusal appears. The command prints only a category; investigate before retrying.

## 6. Grant the first showrunner

1. **Signing machine:**

   ```bash
   uv run python -m scripts.r2.governance_ceremony sign-event \
     --key grant.key --key-id "$GRANT_KEY_ID" --type ISSUE \
     --user-id default --project <project> --principal <reviewer-login> \
     --sequence 1 --expires-at 2027-01-01T00:00:00Z --out issue-1.json
   ```

   Record the printed event digest. The next event for this scope (a REVOKE) names it with `--previous-event-digest`.

2. **Host, application stopped:**

   ```bash
   sudo -E uv run python -m scripts.r2.governance_ceremony import-event --root "$CUSTODY_ROOT" --event issue-1.json
   sudo -E uv run python -m scripts.r2.governance_ceremony next-body --root "$CUSTODY_ROOT" --out next.body
   ```

   After the import, the preflight and the application **refuse to start** until a checkpoint carrying the new grant is published. That is intended: a grant missing from the checkpoint is treated as tampering.

3. **Signing machine:**

   ```bash
   uv run python -m scripts.r2.governance_ceremony sign-checkpoint --key checkpoint.key --body next.body --out checkpoint-2.json
   ```

4. **Host:**

   ```bash
   sudo -E uv run python -m scripts.r2.governance_ceremony publish \
     --root "$CUSTODY_ROOT" --checkpoint checkpoint-2.json --operator-id "$OPERATOR_ID"
   ```

- **Check:** `published; checkpoint sequence 2`, then `sudo -E uv run python -m scripts.r2.governance_preflight preflight --root "$CUSTODY_ROOT"` prints `Governance preflight passed`.
- **If a step was interrupted:** rerun the same `publish` with the same file. The publisher reconciles a half-finished publication from the retained archive and never lowers the high-water.

## 7. Run the startup attestor (host)

The attestor answers each application start with fresh proof of the current archive. Run it as a root service, for example a systemd unit with `Restart=on-failure`:

```bash
sudo -E uv run python -m scripts.r2.governance_preflight serve --root "$CUSTODY_ROOT" --socket-directory "$ATTESTOR_DIR"
```

- `ATTESTOR_DIR` must already exist, owned by `0:0` with mode `0700`. The service creates `attestor.sock` with mode `0600` and refuses an existing socket path.
- **After a crash** (`kill -9` or a host reboot), confirm that nothing is listening (`ss -xlp | grep attestor.sock` shows no process). Remove only `attestor.sock`, then start the service again.

## 8. Start the application in activated mode

Add to the `arcreel` service in `docker-compose.yml`:

```yaml
    environment:
      ARCREEL_GOVERNANCE_READ_DIR: /governance/read
      ARCREEL_GOVERNANCE_ATTESTOR_DIR: /governance/attestor
    volumes:
      - /srv/arcreel-governance/read:/governance/read:ro
      - /run/arcreel-attestor:/governance/attestor:ro
```

- Never mount `archive/` or any key.
- Setting only one of the two variables refuses startup; setting neither keeps normal mode.
- In activated mode the application does **not** run automatic database migrations. Migrate offline before starting.

**Check:**
1. The application starts and is ready. A denied start leaves it unready, and its logs name only a category.
2. Signed in as the granted reviewer through a browser session (an API key is refused by design), open an episode's **Shots** page. The review step offers "Open review".

## 9. Backup and restore drill

The archive is part of the system of record. Back up `CUSTODY_ROOT` with the database, in the same offline window as the M7 backup ([m7-backup-restore.md](m7-backup-restore.md)).

**Drill, on a scratch host:**
1. Restore the database and the archive from the same set. Run `governance_preflight preflight`; it passes.
2. Restore an **older** database with the **current** archive. The preflight and an activated application start must both refuse (the database lacks grants the archive records).
3. Restore the archive alone to an older copy than the database. This also refuses. Recover with the newest retained archive; never hand-edit the high-water.

Record the commands and outcomes as deployment evidence. ADR-0103 activation is not proven until this drill has passed on the real host.

## 10. Revoke and routine grants

- **Revoke:**
  1. Sign `--type REVOKE --sequence <n+1> --previous-event-digest <digest of event n>` without `--expires-at`.
  2. Then run `import-event`, `next-body`, `sign-checkpoint` and `publish` as in step 6.

  Revocation stops new reviews and decisions immediately after the next start. It does not rewrite decisions already made.
- **Re-grant after a revoke:** a new ISSUE with the next sequence.
- **Every grant change** needs the application stopped and a new checkpoint. There is no online grant administration.
- **Key rotation and a new image** both need a new approval sequence, which these tools refuse. Plan that ceremony separately.

## What this runbook does not prove

These remain deployment evidence for the operator to record:
- that the keys were really kept offline;
- the host's root, filesystem and backup topology;
- the image digest running in production;
- the restore drill on the real host.

The tools check every record they write and every archive they read. They cannot prove facts about the host itself.
