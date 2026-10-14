# ADR-0103 governance activation on V2 staging (2026-10-14)

Runbook: `docs/r2/runbooks/governance-activation.md`. Code: `r2-v2/main` `e4cab2fe`.

## Sponsor authorization

The sponsor explicitly authorized the agent to run the runbook end to end:
- to generate the real keys;
- to issue the first grant;
- to install the attestor as an enabled systemd service.

The sponsor ran the single root script `~/arcreel-v2-staging/governance-activate.sh` with sudo.

## Identifiers

| Item | Value |
|---|---|
| Deployment | `staging-v2` |
| Grant key id | `grant-2026-10`, public `8mevnfv1OG5Ha-21L6p0VqCiBQDEWyuFHVIDLNJzk4s` |
| Checkpoint key id | `checkpoint-2026-10`, public `QvKbZzIuRTPcZcg38kDciCPMDCLgwy-9XwptLwW0Mg0` |
| Registry digest | `sha256:a4ea157a53c7952f93eab59ecfdf29c6f8400ef1507681015ab73938b7c6ecc4` |
| Approved image ref | `arcreel-v2-staging-src@sha256:0b4523c7508282871320f46e7ad8554f7f92b653b280d98b632bdc298849bef9` (digest of `git archive e4cab2fe`) |
| Grant | ISSUE seq 1, scope `default` / `du-an-01-649c62c1` / `admin`, expires `2027-04-01T00:00:00Z` |
| Event digest | `sha256:7bef730be436dece1cebe09ec47a02224b43116804e7c296bdda44f62517abee` |
| Custody root | `/srv/arcreel-governance` |
| Attestor | `arcreel-attestor.service` (enabled), socket `/run/arcreel-attestor/attestor.sock` |
| Keys and signed files | `~/arcreel-v2-staging/governance-keys/` (dir 0700, keys 0600) |

## Steps and outcomes

1. **Database backup and schema migration.**
   - Backup: `backups/pre-governance-20261014T081848Z.dump`.
   - `alembic upgrade head` moved the schema from `901c4a0e0001` to `913c4a0e0001`.
2. **Offline steps:** `keygen` ×2, `registry`, `approve`, `genesis-body`, `sign-checkpoint`, `sign-event` (ISSUE). All passed.
3. **Root script** (log: `~/arcreel-v2-staging/governance-activation.log`). Steps 3–6 ran with the timestamps shown.
4. `enroll` printed `enrolled; checkpoint sequence 1` (08:24:23Z).
5. Grant import and checkpoint 2 (08:24:24Z):
   - `import-event`, `next-body` and `sign-checkpoint` passed;
   - `publish` printed `published; checkpoint sequence 2`;
   - preflight printed `Governance preflight passed`.
6. **Archive backup:** `backups/governance-archive-20261014T082430Z.tar.gz`.
7. **Attestor service:** `systemctl is-active` and `is-enabled` both report active/enabled; the socket is `srw------- root root`.
8. **Activated application start** (uvicorn on 127.0.0.1:1251, data `~/arcreel-v2-staging/data`):
   - result: `Application startup complete`, `/health` ready;
   - probe: `POST /api/v1/projects/du-an-01-649c62c1/m8/spatial/review-sessions` with `target_id=activation-probe` returned **HTTP 409** `m8_spatial_source_conflict`, not 503 `m8_spatial_review_unavailable`;
   - the 409 means the activated grant reader is installed; the probe target does not exist;
   - the app was stopped afterwards, and no root-owned files remain in the data dir or the worktree.

## Deviations from the runbook (accepted for staging)

- The keys were generated and are stored on this networked development machine, not on an offline signing machine.
- The agent created the keys and signed the grant under sponsor authorization. This is not a separate human signer.
- Staging runs from source via `uv`, not from a container image. The approval pins the source-tree digest. The image ref is recorded, not enforced at runtime.
- Root code (ceremony CLI, attestor) runs from the user-writable worktree instead of a root-owned checkout.
- The archive backup is on the same disk as the database backup. It is not an independent custodian.
- The app runs as root only when activated. Normal staging runs stay non-root and unactivated.

## Not yet proven

- **Step 9, the restore drill:** older DB plus newest archive must refuse, and re-importing the events must pass.
- **A real reviewer flow in the browser:** grant `admin` on `du-an-01-649c62c1`, which needs bound shot targets and live spatial analysis.
- **Revocation:** step 10.
