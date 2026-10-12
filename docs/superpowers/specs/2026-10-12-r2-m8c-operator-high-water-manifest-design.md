# M8-C operator high-water and release manifest candidate

Status: sponsor selected an operator-managed host directory as the custody medium on 2026-10-12. The layout and procedure below remain a design candidate; this does not enroll an operator, accept a key rotation, change production Compose, or authorize a restore/cutover.

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

## Selected host-directory boundary

Use one configurable absolute host root outside the Compose project, `pgdata`, `projects`, `logs`, any M7 backup directory and every restore target. `/srv/arcreel-governance` is an illustrative deployment path, not a path created or approved on this machine. The root has two distinct subtrees:

| Host subtree | Contents and access |
|---|---|
| `archive/` | Operator-only approved deployment records, immutable-by-procedure high-water entries, retained exact checkpoint bytes and custody receipts. Root-owned, mode `0700` on directories and `0600` on records; never bind-mounted into the app or PostgreSQL container. |
| `read/` | Only the current public verifier registry, current signed checkpoint, and public copies of the approved deployment record and latest high-water entry. Root-owned, proposed directory mode `0755` and file mode `0644`, with no private key or operator receipt. Bind the **directory** into the app read-only; never mount a single current file, and never give the app a write mount of either subtree. |

The operator's publisher is the only writer. For the proposed root-owned layout it runs outside the application container through an audited root procedure, with an exclusive host-side publication lock. The application must not create the source directory: use Compose long bind syntax with `read_only: true` and `bind.create_host_path: false`, then fail startup if any expected file is absent. Docker's [Compose bind specification](https://docs.docker.com/reference/compose-file/services/) documents both fields. The earlier disposable directory-bind drill demonstrated that separate reader processes reopen the replacement pathname, but production Compose still lacks this mount.

The `read/` approved deployment and high-water records are public *copies* of their latest operator-approved `archive/` counterparts. Before starting or restoring the app, the operator compares both copies byte-for-byte with the retained records and checks the resolved image digest against the deployment record. Inside the app, those copies pin the registry and checkpoint bytes it sees; the app cannot prove its own image digest or detect replacement of `archive/` and `read/` together by a privileged host actor. The deployment record remains stable across ordinary grant transitions; the high-water copy advances with each checkpoint. Publication of the checkpoint and its high-water copy is two pathname replacements, so intermediate mismatches must deny reads/startup. Therefore direct Compose startup without the operator preflight is outside the activated procedure. Host-root compromise, deletion of the whole host and rollback of all copies are outside this host-local guarantee. A separately stored backup of `archive/` and a recorded restore procedure are required for host-loss recovery; the destination, schedule and operator custody of that copy still need to be selected and tested.

The current application image runs as root with `NET_ADMIN` and unconfined seccomp/AppArmor for its sandbox. A read-only bind prevents writes through that mount; it does not create a security boundary against host-root control or container escape. The trust claim is limited to an uncompromised host and the operator's exclusive archive custody.

A disposable local Compose probe used `postgres:16` as a no-port, no-app reader with long bind syntax. `docker compose config --quiet` returned 0. For an existing source directory, the container read `current`, could not create a file under the read-only mount, and exited 0. For a missing source with `create_host_path: false`, `compose run` exited 1 and did not create the source directory. The temporary directory and one-off containers were removed. This proves the selected Compose syntax on the local engine only; it does not test the production service, host ownership, archive durability or signer procedure.

The [bounded reuse audit](../../research/2026-10-12-r2-m8c-host-custody-reuse-audit.md) identifies existing atomic-write, no-follow, fence-expectation and clean-restore primitives and fixed donor revisions. None supplies an independently retained Governance latest-checkpoint anchor as-is.

## Publication and crash ordering

For a new signed ISSUE/REVOKE checkpoint, the operator first verifies the committed database head and its signed chain, checks that the new checkpoint has sequence `N+1`, predecessor equal to retained checkpoint `N`, no removed scopes and no head sequence decrease, and checks exact deployment/key purpose. A scope deletion or sequence reduction requires a separately designed signed recovery exception; no ordinary publisher path admits it.

The operator writes the complete candidate to a sibling in `read/` and fsyncs that file. It then retains and durably fsyncs the high-water entry, exact candidate bytes and affected `archive/` directories **before** changing either public current name. It publishes `read/high-water.json` first, then renames the candidate over `read/grant-checkpoint.json`, fsyncing `read/` after each replacement. These two names cannot be replaced atomically as a pair; any old/new mismatch denies until the operator republishes the exact retained bytes and reruns preflight. Linux [rename(2)](https://man7.org/linux/man-pages/man2/renameat2.2.html) describes atomic replacement of one destination name, while [fsync(2)](https://man7.org/linux/man-pages/man2/fsync.2.html) notes that persisting a directory entry needs an explicit directory fsync. If archive retention fails, publication stops. A crash after durable high-water but before both public renames sacrifices availability until reconciliation or quarantine. The operator never makes the application write the archive or checkpoint. The [proposed record and publication contract](2026-10-12-r2-m8c-host-record-and-publication-contract.md) defines the exact bytes and retry boundary.

On restore, an operator preflight compares the image and registry digests to the approved deployment record, checks the current checkpoint digest/sequence against the latest retained high-water entry, then runs the full-chain PostgreSQL scanner before the app or workers become ready. A lower, divergent or missing current file quarantines the target even when that file has a valid signature. The scanner separately rejects any database head mismatch. The M7 `VERIFIED` backup state remains a prerequisite for its own workflow but is not a substitute for this Governance preflight.

## Open acceptance work

1. The sponsor selected an operator-managed host directory. Resolve its actual absolute path, filesystem, provisioning account, access review, independent backup destination/retention and host-loss restore drill. The ownership/mode and two-subtree layout above are proposed until verified on that host; two-person approval and receipt custody remain undecided.
2. Review the proposed high-water/deployment record wire contract, then implement and verify its offline publisher with adversarial crash/retry tests. Do not use production private keys in repository tests.
3. Define a key-rotation ceremony with continuity from the previous approved registry to the next; the v1 parser alone does not authorize a key switch.
4. Choose a schema/migration preflight that cannot advance grant state before recovery comparison, and pin a production image by digest. The current production Compose still uses a mutable tag.
5. Run the exact Compose restore drill, multi-process runtime equality tests, full affected gates and independent exact-HEAD review before any activation claim.

No license assessment is part of this packet.
