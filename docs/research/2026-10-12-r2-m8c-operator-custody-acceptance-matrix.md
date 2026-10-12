# M8-C operator custody acceptance matrix

Status: research and test design at `7a986a8cad3a12fd056cc78ac844b7b95384a10b`, amended after the sponsor selected an operator-managed host directory on 2026-10-12. Its exact host path, provisioning, backup and release authority remain undecided. No production file, key, mount, migration or route is changed by this packet.

## Current evidence

The V1 H6 backup set includes a database dump, selected data roots, an unsigned attestation and its own manifest. It captures under an offline fence and requires `VERIFIED` before restored use (`docs/r2/runbooks/m7-backup-restore.md`). It cannot independently establish the latest Governance REVOKE: an older backup and its self-consistent attestation can be restored together. Production Compose currently uses mutable `arcreel/arcreel:latest`, mounts `.env`, projects and logs, and has no verifier/checkpoint mount (`deploy/production/docker-compose.yml`). The M8-C registry parser, checkpoint verifier, file reader, full-chain scanner and checkpointed per-transaction reader exist as internal components; no operator-pinned registry or startup composition supplies their trust inputs.

## Minimum independent trust state

The operator must retain outside the database, application-writable mounts and backup set:

1. An approved deployment record binding deployment ID, exact image digest, canonical registry digest/sequence, active purpose-separated key IDs and the previous approved record ID.
2. A latest high-water record binding that deployment record to the exact checkpoint file digest, signed body digest, sequence, predecessor and signer ID. Keep the exact checkpoint bytes for recovery after an interrupted publication.
3. The decision provenance and access rules for changing those records. A hash chain contained only in replaceable records cannot prevent replacement of the entire chain; the custody medium and operator procedure supply the independent anchor.

The operator release preflight must resolve the actual image digest outside the container and compare it to the approved record; the application cannot self-attest its own image digest from a supplied environment variable. Application startup must compare its trusted deployment identity and the registry/checkpoint bytes it actually sees with the approved values before accepting the database. The full-chain scanner then compares the checkpoint to every local grant head. The per-transaction reader repeats current-head equality on every Governance-backed operation. These checks answer different questions and cannot substitute for one another.

## Acceptance matrix

| State or forced fault | Required result before activation | Evidence needed |
|---|---|---|
| Current approved image, registry, checkpoint and database | Startup may become ready after read-only schema check and full scan; current scoped grants still pass each transaction-bound read | Exact image/manifest/registry/checkpoint digests and PostgreSQL startup result |
| Older pre-REVOKE database with latest REVOKE checkpoint | No worker or route readiness; no Alembic stamp/upgrade or grant write before denial | Actual `pg_restore` into clean target, lifespan probe and row/schema before/after |
| Older checkpoint with current database | No readiness or grant result, even when old checkpoint signature is valid | Archive high-water mismatch plus scanner/reader denial |
| Matching older database and older checkpoint | Operator preflight denies against latest independent high-water before scanner could accept the internally consistent pair | Restore of old backup plus rollback of mounted checkpoint; independent archive unchanged |
| Older or alternate registry containing a valid key | Operator/app pin comparison denies before using the new key; no signer key is selected solely from incoming bytes | Registry digest/sequence mismatch and unknown-key case |
| Different image at same mutable tag | Release preflight denies against approved image digest; no activated app ready | Resolve actual image digest and compare to approved record |
| Missing, unreadable, partial, symlinked or oversized custody file | Fail closed with no sensitive path in error; no readiness or grant result | Loader and lifespan cases, including bind directory replacement in separate processes |
| Crash before candidate file fsync | Current checkpoint remains old and affected new grant is unavailable; archive does not advance | Kill/restart at publisher fault point and inspect current/archive bytes |
| Crash after archive fsync but before current rename | Startup quarantines the old current file; operator can recover exact retained candidate without inventing a new record | Kill/restart and replay from retained candidate |
| Crash after rename but before directory fsync | On reboot, current may be old or new; compare exact bytes to retained high-water and recover/quarantine | Fault injection plus reboot-equivalent remount/restart observation |
| Concurrent import, scan and request | Scanner sees a stable complete scope set; request compares a transaction-locked local head to a fresh checkpoint; commit order is observed | Forced PostgreSQL backend blockers and both orderings |
| Key rotation or rollback of approved record | No implicit acceptance. Require an explicit continuity ceremony bound to the last retained approved state | Old/new key signatures, record sequence, rollback and lost-key tests in a separately accepted packet |

The existing internal restore drill proves only that an old PostgreSQL database is denied against a newer external checkpoint when scanner/reader are invoked directly. The internal service integration test proves denial when a checkpoint lacks the active scope. Neither exercises a production trust archive or application lifespan. The sponsor selected a host directory; its actual failure domain, independent backup, authorized operator, retention and key-rotation ceremony still need definition and evidence. The selected layout and reuse audit are in `docs/superpowers/specs/2026-10-12-r2-m8c-operator-high-water-manifest-design.md` and `docs/research/2026-10-12-r2-m8c-host-custody-reuse-audit.md`.
