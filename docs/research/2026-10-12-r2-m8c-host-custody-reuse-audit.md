# M8-C host custody reuse audit

Status: source-backed reuse decision from worktree `b5efdb00389fc7e1b862c0a150b7152174b475e5`, after the sponsor selected an operator-managed host directory. This is a bounded audit of custody publication and restore seams, not approval to operate a host archive or activate Governance.

## Current repo seams

| Existing source | Reuse decision | Exact limit |
|---|---|---|
| `lib/json_io.py:72-96` `atomic_write_bytes` | Reuse same-directory tempfile, byte-preserving write, file `fsync`, `os.replace` and cleanup pattern for a scoped operator publisher. | It does not `fsync` the parent directory, perform no-follow descriptor opens, enforce a bounded canonical record, lock concurrent publishers or retain high-water before replacing current. Calling it alone cannot establish crash-durable anti-rollback custody. |
| `lib/artifact_manifest.py:1444-1479` `_atomic_replace` and its integration tests | Reuse descriptor-relative open/replace, `0600` file mode, symlink-swap and failure-injection test patterns. | It belongs to project artifact authority and does not `fsync` the directory. Do not make Governance custody depend on project manifest state or its lock. |
| `r2/host_hardening/project_tree_census.py:64-121` | Reuse bounded no-follow directory/file identity and post-read validation patterns for operator preflight. `GovernanceCheckpointFile` already adapts the same kind of read constraint for its fixed file. | A project-tree census assumes a separate offline backup fence; it does not say which checkpoint is latest or authorize a key. |
| `r2/host_hardening/fence_evidence.py:42-124` | Reuse the trust split: independent expected deployment/image/key identities versus bytes supplied by a record or reader. | Its `FenceExpectationV1` is for backup capture, not a Governance high-water wire record or signing-key rotation. |
| `r2/host_hardening/deployment_backup.py:455-478` and `docs/r2/runbooks/m7-backup-restore.md` | Reuse clean-target restore, exact manifest digest, offline fence and separate verdict/evidence conventions. | Its state and unsigned attestation live inside one rollback-capable backup set. Its `_write_json` calls `atomic_write_bytes`, so it does not add directory fsync or an independent latest-state anchor. Do not put Governance `archive/` under a named backup root. |
| `r2/contracts/governance_verifier_registry.py`, `r2/governance/checkpoint_signature.py`, `server/services/governance_grants.py` | Reuse the existing canonical registry parser, signed checkpoint verifier, full-chain scanner and transaction-bound reader. | The caller-supplied keys and checkpoint bytes are still data until checked against the operator-approved archive/public copy. No runtime caller is wired. |

The root graph at generation `2026-09-27T03:07:32Z` found `atomic_write_bytes` and `_atomic_replace`; `check_index_coverage` recorded no gap for those root files, but the new Governance modules in this worktree have missing graph freshness. Every listed behavior was checked in current worktree source. The claim is bounded to the files above.

## Previously researched donors, rechecked at fixed commits

| Donor and fixed revision | Reusable behavior | Boundary for M8-C |
|---|---|---|
| ArcReel host `v0.29.0` at `6ddedc775e7fe5f398b10081ab741985f7dceda7`, `website/docs/ops/deployment.md:345-408` | Stop app writers, preserve matching database/files under one backup identity, restore to an empty database and perform health/project checks. The checkout still resolves to that exact SHA and has no tracked diff. | Its backup lives under the Compose project and includes `.env`; a shared timestamp and local archive do not provide a separate Governance latest-checkpoint anchor. |
| PIOS at fixed `fbf9e81a20ddb06ce475f5a52169a3ccd0efe43a`, `infra/backup/pgbackrest_backend.py:16-87` and `infra/scripts/restore_drill.py:300-365` | Narrow effect port, test/production isolation, fixed command arguments, clean disposable restore with a read-only repository, and measured restore evidence. The fixed commit was re-read with `git show`; the live PIOS checkout is now `0187e348` with two unrelated untracked files, so its current state is not substituted for the pin. | It protects PostgreSQL backup execution and a repository mounted read-only into the restore container. It does not bind external Governance verifier keys or high-water to a separately approved host record. |
| DramaClaw `b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83` as recorded in `docs/research/2026-09-13-r2-m8-reuse-first-comprehensive-research.md` | File-lock, atomic JSON replacement and failure-injection ideas for Canvas persistence may inform test cases. | This turn did not reopen the donor checkout or run its fixture; the prior packet says its backend JSON storage is not a production authority for R2. Do not claim parity or transplant it into the Governance archive. |

## Reuse decision before implementation

Compose one scoped operator publisher/preflight around the repo's current canonical/signed contracts and tested read primitives. Reuse the local atomic-write and no-follow patterns, but extend publication with an exclusive operator lock, canonical bounded records, durable archive-before-current ordering, directory `fsync`, crash/retry tests and an independently retained latest record. Use PIOS/ArcReel restore patterns only as test scaffolding. No donor directly implements the selected host-local Governance trust boundary. Fixture parity and exact failure semantics must be proven before accepting any adapted donor behavior.

No license analysis is part of this audit.
