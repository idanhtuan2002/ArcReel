# M8-C signed grant-head checkpoint and running-process custody

Status: proposed implementation spec, 2026-10-12. This packet defines a
testable trust-boundary candidate. It does not accept ADR-0103, provide a live
verification key, activate a route, or authorize production migration/restore.

## Outcome and source facts

A restored older grant database must not regain an ISSUE whose later REVOKE was
lost, and a running application must not authorize an uncheckpointed event.
The authority point is the exact signed grant head for each
`(user_id, project_name, principal)` scope. `GovernanceGrantImporter` currently
serializes an import and grant reader on the database head, but the head and
signed event history are stored in that same database. The production Compose
file supplies no independently custodied verifier/checkpoint and uses a
floating application tag. `init_db()` runs Alembic before other startup work.
The [source and primary-document research](../../research/2026-10-11-r2-m8c-governance-checkpoint-recovery-custody.md)
records exact paths, official Docker/RFC references, recovery options and the
host-local threat limit. The earlier [grant/review spec](2026-10-06-r2-m8c-grant-and-review-evidence-design.md)
keeps production APPROVE closed until recovery custody is demonstrated.

## Approach choice and limits

| Approach | Result |
| --- | --- |
| Database-only grant head or backup attestation | Cannot detect restoration of an older internally valid database. |
| Root-owned host custody mounted read-only, with an offline-signed exact-head checkpoint | Candidate for the first Compose drill. The app can read but cannot publish the key or checkpoint; the operator separately retains its high-water history. Requires a verified atomic publication layout for running containers. |
| Independently authenticated append-only checkpoint service | Stronger separation from the Docker host, but no approved service, identity or recovery procedure exists. Keep as the escalation option. |

The host-local candidate detects ordinary application-data/database rollback.
A privileged operator able to replace the image, verifier source and retained
history can defeat it. No claim about that adversary is made.

## Pure signed checkpoint contract

The first implementation slice accepts one explicitly supplied 32-byte
Ed25519 public key and exact key ID. It neither reads files nor signs data.
The wire object is a canonical UTF-8 JSON envelope with exactly `body` and
`signature`, reusing `lib.content_digest.canonical_json_bytes(...,
allow_nan=False)`, strict duplicate-key rejection, unpadded base64url 64-byte
signature, and sanitized errors from the signed-grant contract. The signed
bytes are the canonical `body` bytes, not the outer envelope. The body has
exactly:

- `schema`: `governance.grant_head_checkpoint.v1`, a signature domain distinct
  from `governance.showrunner_grant_event.v1`;
- `deployment_id`: exact nonempty, unpadded identifier obtained from an
  operator-pinned deployment identity, never inferred from project data;
- `checkpoint_sequence`: strict positive integer;
- `previous_checkpoint_digest`: null only at sequence 1, otherwise a
  `sha256:` digest of the preceding checkpoint's canonical signed body;
- `issued_at`: strict UTC-second text `YYYY-MM-DDTHH:MM:SSZ`;
- `signer_key_id`: exact operator-pinned checkpoint verifier ID;
- `heads`: an array sorted strictly by `(user_id, project_name, principal)`.
  Each record contains exactly those three identities, a strict positive
  `head_sequence`, and the canonical `sha256:` `head_event_digest`.

An empty `heads` array represents a valid genesis checkpoint before any grant
is imported. Reject duplicate scopes, unsorted arrays, wildcard/padded/empty
identities, booleans as integers, malformed digests/timestamps, duplicate or
unknown fields, noncanonical JSON, invalid UTF-8, bad signatures and oversize
input. The exact maximum envelope size and scope count must be selected in the
implementation plan and tested against a representative deployment fixture;
the parser must set finite bounds before JSON decoding. Return a typed body,
verified signed bytes, checkpoint digest and a lookup by exact scope only
after signature verification. The digest is `sha256:` over canonical signed
body bytes. No submitted bytes, signatures, scopes or filesystem paths appear
in error strings.

The checkpoint signing key is a separate operational purpose from grant-event
issuance. The first slice takes its key explicitly; a later custody packet
must decide whether distinct Ed25519 keypairs are mandatory, define the
operator-pinned verifier registry and rotation ceremony, and test any key
transition. A signed `signer_key_id` selects only among already trusted keys;
it cannot introduce its own trust anchor.

The [verifier registry and high-water research](../../research/2026-10-12-r2-m8c-verifier-registry-high-water.md)
now proposes distinct purpose-specific keypairs and an operator-approved
registry/image digest in a separately retained release or restore manifest.
That proposal does not accept a registry wire format or key-rotation ceremony.

## Recovery and running-process gates

The operator publishes a new checkpoint only after the relevant signed grant
event commits. It retains the previous checkpoint and verifies that the new
sequence, predecessor digest, environment, scope set and each head advance
form an authorized monotonic successor. Removing a scope or reducing its
sequence is a recovery exception requiring a separate signed procedure. The
application cannot prove that an older valid checkpoint was not substituted
if the entire host-local custody source and retained history are replaced.

Before startup can expose any Governance-backed action, a recovery gate
verifies the pinned image and external key/checkpoint inputs, then scans every
database head and every checkpoint scope. It fences imports from all processes
while enumerating scopes, verifies the complete signed event chain and stored
digests, and requires exact head `(sequence, digest)` equality. No head or
checkpoint scope may be missing on the other side. The current `init_db()`
runs Alembic: the deployment packet must provide schema readiness without
grant-state mutation before this comparison, or move migrations into a fenced
offline preflight. Failure prevents workers and Governance-backed routes from
becoming ready. It is not a health warning.

The [cross-process fence research](../../research/2026-10-12-r2-m8c-grant-import-recovery-scan-fence.md)
proposes a dedicated transaction-level PostgreSQL advisory key: importers
acquire its shared mode before any head insert, and the scanner acquires its
exclusive mode before scope enumeration. Per-scope readers keep their existing
authority lock order and perform fresh checkpoint equality under their
grant-head lock. This remains a candidate until forced PostgreSQL schedules
prove both acquisition orders and rollback behavior.

Every new pair decision, exact replay, current approved-pair read, and any
review-session operation that relies on the current grant must verify a fresh
complete signed checkpoint while holding the relevant grant-head row lock in
the same database transaction. It compares the exact scope's sequence/digest
to that locked head. A process must not cache a startup pass or a checkpoint
head as an authorization result. An import-first transaction leaves the
affected scope unavailable until the operator publishes the matching object;
a decision-first transaction may complete before that import. Multiple app
processes must see the same complete publication. The importer does not write
operator custody. The existing local `CurrentShowrunnerGrantReader` remains
internal until this verifier is integrated and reviewed.

The publication layout is a separate deployment choice. A disposable local
Docker probe recorded in the [research note](../../research/2026-10-11-r2-m8c-governance-checkpoint-recovery-custody.md)
observed `old` after atomic host replacement through a single-file read-only
bind mount, but `new` through a read-only directory bind mount. The first
Compose candidate therefore mounts the operator-held directory read-only,
publishes complete checkpoint files by same-directory atomic rename and opens
the pathname anew in every transaction. The actual Compose drill must prove
that running processes read complete newly published bytes and reject partial
or missing content. Do not treat a startup-only file read as sufficient.

## Ordered implementation and acceptance gates

1. Pure parser/verifier with fixed vectors and adversarial malformed-input
   tests. No file loader, DB access, issuer, route or deployment changes.
2. Operator-pinned verifier registry, atomic publication reader and
   independently retained high-water procedure. Test malformed/old/unknown
   key, interrupted publish and running-container file visibility.
3. Startup full-chain/equality gate with a cross-process import fence. Test
   pre/post-REVOKE restore, missing/extra scope, altered event, older valid
   checkpoint, and denial before worker readiness on disposable PostgreSQL.
4. Transaction-bound scope equality on every Governance-backed caller. Force
   both import-first and decision-first schedules on PostgreSQL, including
   multi-process readers, exact replay and current approved-pair reads.
5. Pinned-image Compose drill, complete affected checks, independent exact-HEAD
   review and explicit activation decision. Production APPROVE, READY and
   recovery cutover stay closed until all gates pass.

No license assessment belongs to this packet.
