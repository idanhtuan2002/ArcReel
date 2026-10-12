# M8-C operator verifier registry and checkpoint high-water

Status: research and design candidate at `07cb6fc28cbd0ab6524381a3544cac16cbd81d48`, 2026-10-12. No key enrollment, registry parser, signer, production mount or activation is accepted here.

## Current boundary

The production image is selected by mutable `arcreel/arcreel:latest` and the `arcreel` service has no Governance custody mount (`deploy/production/docker-compose.yml:18-44`). `GovernanceCheckpointFile` can reopen one fixed name in an injected directory, but no application caller supplies a production path. The pure checkpoint verifier takes an explicit deployment ID, key ID and 32-byte key (`r2/governance/checkpoint_signature.py`); the scanner takes those values and an injected loader (`server/services/governance_grants.py`). Neither can establish that a supplied key is an operator trust anchor or that a signed checkpoint is the latest one.

The application image currently runs as root and receives `NET_ADMIN` with unconfined seccomp/AppArmor for its agent sandbox (`Dockerfile`, `deploy/production/docker-compose.yml`). A read-only bind mount blocks writes through that mount, but is not a substitute for pinning the image or for host-side custody. Docker describes read-only bind mounts as restricting container writes and notes that read-only handling of submounts is best effort: <https://docs.docker.com/engine/storage/bind-mounts/>. The earlier disposable mount probe observed same-directory rename through a directory mount and stale content through a single-file mount; the actual application Compose layout has not been drilled.

## Trust-anchor candidate

Keep a small, bounded, canonical `governance-verifiers-v1.json` in a dedicated root-owned host directory mounted read-only as a directory. It would contain exact schema, deployment ID, registry sequence, and exactly one active grant-event verifier and one active checkpoint verifier, each with purpose-specific key ID and 32-byte Ed25519 public key. Require distinct key IDs and public keys for those two purposes. The offline private keys and the host registry publication procedure remain outside the application. No signer key may be selected from a submitted grant or checkpoint without matching this already loaded registry.

The registry itself is an **operator-pinned file**, not self-authenticating merely because it is JSON. The deployment/restore manifest must record its digest and the pinned image digest; the operator must compare them to a separately retained approved manifest before starting the image. Loading a registry from `.env`, PostgreSQL, `projects`, logs, or any app-writable root would collapse the boundary. The application must reject unavailable/malformed/duplicate/noncanonical registry bytes, wrong deployment ID, unknown or repeated key IDs, and malformed key lengths. A first implementation can support exactly one active key per purpose and fail closed on a key change; rotation needs a separate accepted ceremony.

The Update Framework is an external **comparison**, not a library selected for this project. Its versioned specification requires trusted root metadata before using new keys, a contiguous version transition and signatures authorized by both old and new trust sets for root-key rotation: <https://theupdateframework.github.io/specification/v1.0.36/#update-the-root-role>. Those checks rely on retained trusted state. Copying only an N+1 counter into the same rollback domain as the registry would not provide the continuity property here.

## Checkpoint high-water candidate

For each successfully published checkpoint, the offline operator retains a distinct evidence record outside the database, application mounts and the backup set: deployment ID, registry digest, checkpoint sequence, checkpoint body digest, predecessor digest, exact publication time and signer key ID. The operator checks that a successor has sequence `N+1`, predecessor digest equal to the retained `N` body digest, no scope removal or sequence decrease, and each changed head is supported by its signed grant chain. Publish the complete candidate to a sibling file, fsync the file and directory, then atomically replace the fixed current pathname in the same directory. Retain the old checkpoint and high-water record for rollback investigation. An interrupted pre-rename publication leaves the old complete checkpoint visible; any grant imported after that old checkpoint remains unavailable to Governance decisions until publication succeeds.

On restore, compare the mounted registry/checkpoint digests and checkpoint sequence to the independently retained operator record before running the full database scan. A lower or divergent current file quarantines the restore even if its signature is valid. The application scanner then verifies exact full-chain equality. The app alone cannot prove that a privileged host operator has not replaced the entire registry, checkpoint directory, image and retained record together; that remains the host-local threat limit.

## Unresolved gates

1. Pin the verifier registry wire schema and deployment identity source, then test parser rejection and key-purpose separation. An operator-approved digest and image pin must come from a release/restore manifest outside app-controlled storage.
2. Define the offline signer and high-water evidence format, retention location, authorized operator roles, crash/retry behavior and distinct key-rotation ceremony. A single current registry file does not prove old-to-new continuity.
3. Drill actual Compose directory mount and running multi-process reads with complete/partial publication, including a replacement during a locked grant transaction.
4. Wire the pinned registry and reader into startup and transaction authority only after the above are accepted; then run the disposable restore and exact-HEAD review. Production APPROVE/READY remains closed.

No license assessment is part of this research.
