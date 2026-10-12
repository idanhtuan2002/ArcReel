# M8-C operator high-water and release manifest candidate

Status: proposed recovery/operations contract at `fa91ff4050984c646eeb8a45015882a3c9120ab0`, 2026-10-12. It does not enroll an operator, accept a key rotation, change production Compose, or authorize a restore/cutover.

## Evidence and boundary

The M7 backup set already records a release image digest, manifest digest, restore verdict and unsigned operator attestation (`docs/r2/runbooks/m7-backup-restore.md`). Its attestation protects consistency within one backup set but explicitly relies on access control over that same set. It cannot be the independent grant high-water: restoring an older valid backup could restore an older grant ledger and that backup's own attestation together.

The pure M8-C registry parser returns an untrusted content digest; the checkpoint verifier authenticates one signed body under a caller-supplied key; the recovery scanner checks one externally supplied checkpoint against every local signed grant chain. The candidate image now packages those modules, and a temporary Compose bind demonstrated pathname replacement visibility. None of these pieces proves that the supplied registry key or checkpoint is the latest operator-approved one.

The Update Framework's versioned root-update rules provide a useful continuity comparison: a new root version is checked against the previously trusted one, and version `N+1` plus old/new authorized signatures establish a chain (<https://theupdateframework.github.io/specification/v1.0.36/#update-the-root-role>). M8-C is not adopting TUF; its host-local operator record is the retained trust state. Keeping only a counter in the mutable checkpoint directory would allow the same rollback as the database.

## Candidate records

Maintain a root-owned, operator-only archive outside PostgreSQL, the application image, app mounts, backup-set directories and any restored data root. It contains an approved deployment record and an append-only sequence of checkpoint high-water entries. The application receives only a read-only registry/checkpoint directory; no private signing key or archive write path enters its container.

An approved deployment record pins:

- exact deployment ID and candidate image digest, with image repository/architecture for human audit;
- SHA-256 digest and sequence of the canonical verifier registry;
- active grant-event and checkpoint key IDs and their purpose separation;
- operator approval identity/time and a unique deployment record ID.

Each checkpoint high-water entry pins:

- deployment record ID, deployment ID and registry digest;
- checkpoint sequence, canonical signed-body digest, previous checkpoint digest, signer key ID and issued-at time;
- exact source checkpoint file digest and bytes retained in the archive;
- validation result for every prior scope and changed head, including the signed grant event chain supplied to the offline signer;
- prior high-water entry digest and an operator custody receipt.

The entry must be canonical and digest-linked. The operator archive's ownership/retention and offline approval are the trust anchor; a self-hash or sequence field in a replaced archive is not independent protection. A separate append-only service remains the stronger option if privileged host replacement is in scope.

## Publication and crash ordering

For a new signed ISSUE/REVOKE checkpoint, the operator first verifies the committed database head and its signed chain, checks that the new checkpoint has sequence `N+1`, predecessor equal to retained checkpoint `N`, no removed scopes and no head sequence decrease, and checks exact deployment/key purpose. A scope deletion or sequence reduction requires a separately designed signed recovery exception; no ordinary publisher path admits it.

The operator writes the complete candidate to a sibling in the custody directory and fsyncs that file. It then appends and durably fsyncs the high-water entry and archive directory **before** publishing the candidate as current. Finally it renames the candidate over `grant-checkpoint.json` in the same directory and fsyncs that directory. If the archive step fails, publication stops. If the process crashes after durable high-water but before rename, the current checkpoint is old and the affected grant scope stays unavailable; recovery compares the archive to the current file and resumes publication of the retained candidate or quarantines. If rename succeeds but its directory fsync does not, the retained high-water still detects an older current file after reboot. The operator never makes the application write the archive or checkpoint.

On restore, an operator preflight compares the image and registry digests to the approved deployment record, checks the current checkpoint digest/sequence against the latest retained high-water entry, then runs the full-chain PostgreSQL scanner before the app or workers become ready. A lower, divergent or missing current file quarantines the target even when that file has a valid signature. The scanner separately rejects any database head mismatch. The M7 `VERIFIED` backup state remains a prerequisite for its own workflow but is not a substitute for this Governance preflight.

## Open acceptance work

1. Select an actual archive medium and authorized operator procedure. Define file ownership/mode, backups, two-person approval if needed, and how receipt authenticity survives host loss. No local file choice is accepted by this packet.
2. Define a strict high-water/deployment record wire contract and offline publisher with adversarial crash/retry tests. Do not use production private keys in repository tests.
3. Define a key-rotation ceremony with continuity from the previous approved registry to the next; the v1 parser alone does not authorize a key switch.
4. Choose a schema/migration preflight that cannot advance grant state before recovery comparison, and pin a production image by digest. The current production Compose still uses a mutable tag.
5. Run the exact Compose restore drill, multi-process runtime equality tests, full affected gates and independent exact-HEAD review before any activation claim.

No license assessment is part of this packet.
