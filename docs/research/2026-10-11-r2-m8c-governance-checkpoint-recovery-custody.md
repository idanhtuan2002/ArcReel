# M8-C Governance verification-key and anti-rollback recovery custody

Status: proposed deployment and recovery design research, started 2026-10-11
and reviewed against `8d936f051ffef1f423bf5c56316417001375b953` on
2026-10-12. This is not an activation decision, a key enrollment, a Compose change, a database
migration, or evidence of a completed recovery drill.

## Scope and evidence

This note is limited to the custody needed before the proposed ADR-0103
Showrunner-grant and pair-approval path may be activated. It uses the current
M8-C binding-design worktree initially at
`af9d943a96bb7b039ecfd6b41ad3927674e1e388`; the main-agent review used
`8d936f051ffef1f423bf5c56316417001375b953`.
The codebase-memory graph supplied for this task is stale
(`2026-10-04T09:21:10Z`), does not track `server/services/governance_grants.py`,
and excludes `deploy/production`; source facts below are direct reads rather
than negative graph claims.

License is outside this research scope.

## Present deployment and authority facts

- Production Compose selects `arcreel/arcreel:latest`, passes `.env`, and
  bind-mounts only `.env`, projects, logs, Vertex keys, and Claude state into
  the application container. It declares neither a Governance verification-key
  input nor a checkpoint input ([`deploy/production/docker-compose.yml:18-44`](../../deploy/production/docker-compose.yml)).
  Docker documents that image tags are mutable and a digest is the way to
  identify the same image consistently ([Docker: pin image versions](https://docs.docker.com/build/building/best-practices/#pin-base-image-versions)).
- The current lifespan runs `init_db()` and then performs file migrations,
  starts the HTTP client, assistant service, generation worker, project-event
  service, and recovery scheduler ([`server/app.py:351-483`](../../server/app.py)).
  It contains no Governance key/checkpoint loading or recovery comparison.
- `GovernanceGrantImporter` verifies an event with a supplied 32-byte public
  key, locks the per-scope database head, verifies the next transition, and
  advances the database head in that transaction
  ([`server/services/governance_grants.py:147-227`](../../server/services/governance_grants.py)).
  `CurrentShowrunnerGrantReader` likewise locks and reads that same local head
  ([`server/services/governance_grants.py:230-251`](../../server/services/governance_grants.py)).
  The models retain the raw signed event and current sequence/digest only in
  the database ([`lib/db/models/governance_grant.py:22-78`](../../lib/db/models/governance_grant.py)).
  This is a local integrity mechanism; it supplies no deployment trust anchor
  and cannot distinguish a restored older, internally valid chain from the
  chain that existed immediately before recovery.
- The existing backup procedure describes an unsigned operator attestation and
  says its integrity rests on access control over the backup-set directory
  ([`docs/r2/runbooks/m7-backup-restore.md:216-232`](../r2/runbooks/m7-backup-restore.md)).
  It is therefore not an independent anti-rollback grant-head checkpoint.
- ADR-0103 already requires a pinned image, an operator-custodied verification
  key outside mutable application data, a separately retained monotonic
  grant-head checkpoint, and a recovery check before activation
  ([`docs/adr/0103-showrunner-grants-and-spatial-review-custody.md:20-22`](../adr/0103-showrunner-grants-and-spatial-review-custody.md)).

Ed25519 defines a public verification key and deterministic verification of a
signature against the message ([RFC 8032, sections 3 and 5.1](https://datatracker.ietf.org/doc/html/rfc8032#section-5.1)).
That verifies the provenance of a checkpoint only after the verifier key itself
is obtained from a custody boundary the application cannot rewrite.

## Options

| Option | Assessment |
| --- | --- |
| Store the verifier key and high-water mark in the grant tables, project directory, logs, `.env`, or another existing application mount | Reject. A database/data restore can roll each of these back together, so comparison has no independent reference point. |
| Mount a root-owned host file read-only into the application, but leave it under `projects`, `logs`, `vertex_keys`, or `claude_data` | Reject. Those are mutable app-data roots in the current deployment and do not establish distinct operational custody. |
| Operator-held, root-owned read-only mounts for a public key and a signed checkpoint; the offline issuer retains the private key; a separate operator procedure advances the checkpoint | Candidate for the first Compose deployment, pending the publication and recovery drill. Docker supports read-only bind mounts (`readonly`/`ro`), but that only prevents writes from that mount in the container; it does not make a host compromise or a privileged deployment operator harmless ([Docker bind mounts](https://docs.docker.com/engine/storage/bind-mounts/#use-a-read-only-bind-mount)). |
| External append-only or independently authenticated checkpoint service | Defer. It can offer a stronger separation from the Docker host, but no approved service, identity model, availability objective, or recovery operation exists in this repository. |

Named Docker volumes are unsuitable as the independent checkpoint by themselves:
they persist outside one container's lifecycle, but may be mounted in multiple
containers and may be read-only or read-write according to the mount
configuration ([Docker volumes](https://docs.docker.com/engine/storage/volumes/)).
Persistence is not separate custody.

## Proposed custody boundary and exact gate

### Custody objects

Before enabling any Governance-backed APPROVE path, the operator maintains two
separate host-managed inputs, neither below the Compose project directory nor
inside PostgreSQL, projects, logs, provider-key, or Claude-state storage:

1. `governance-verifiers-v1.json`: the active issuer key ID and exactly one or
   more explicitly versioned Ed25519 public keys. The corresponding private
   key remains offline with the issuing operator. A rotation record is signed
   by a currently trusted key and names the successor key ID; unknown key IDs
   deny.
2. `governance-grant-checkpoint-v1.json`: canonical signed bytes containing a
   format version, deployment/environment identifier, checkpoint sequence or
   epoch, issuer key ID, issuance time, and sorted scope records. Each record
   names the exact `(user_id, project_name, principal)` and its required
   `(head_sequence, head_event_digest)`. The envelope includes the signature
   over the canonical unsigned checkpoint bytes.

Compose should mount these two paths read-only at dedicated runtime locations,
for example `/run/arcreel/governance/verifiers.json` and
`/run/arcreel/governance/grant-checkpoint.json`; it must not derive them from
the current `env_file` or an application-controlled path. The public key is
not treated as a secret. Its immutable selection and the checkpoint's
integrity are the trust properties being protected.

The checkpoint advances only in an operator ceremony after the relevant signed
grant event has been verified and durably imported. The application process
does not write either object. A new ISSUE, REVOKE, key rotation, restore
exception, or deployment-environment change leaves the affected Governance
scope unavailable for approval until an operator publishes the matching,
signed checkpoint through that separate custody path. Publication must also
work for a running container: a read-only bind mount of a single file may keep
referring to the old inode after the host atomically replaces that path. The
deployment packet must choose and drill a publication/mount layout whose
running readers observe complete new objects without exposing partial bytes.

### Startup and recovery gate

For an activation mode that exposes a Governance-backed decision route, load
and verify the external custody inputs before `init_db()` changes the database.
The current `init_db()` runs Alembic, so a DB-head check requires the grant
schema to exist first. The deployment packet must define an offline schema
preflight or a migration sequence that cannot advance grant state before the
full custody check. Insert `verify_governance_custody_before_workers()` after
schema readiness and before file migrations, network clients, and background
workers in the lifespan. It must fail application startup, rather than merely
log or mark a health warning, unless every item below succeeds:

1. Load both dedicated read-only files; reject missing, unreadable, duplicate,
   malformed, unsupported-version, wrong-environment, or unknown-key material.
2. Parse only the bounded, strict outer envelope needed to locate its key ID,
   signature, and signed bytes; verify the signature and canonical encoding
   before trusting or using any scope record. Reject an expired or
   internally inconsistent epoch. The custody operator verifies that a newly
   published checkpoint succeeds the separately retained high-water record;
   the application cannot detect replacement of its entire host-local custody
   input with an older valid file.
3. Fence all grant imports during the full scan, including imports from other
   processes, so scope enumeration cannot miss a newly inserted head. In a
   transaction that makes no writes, enumerate every grant head and every
   checkpoint scope. For each scope, lock/read its head, re-verify every raw
   signed event and predecessor transition from sequence 1 through the head,
   recompute each event digest, and require the database head to be exactly
   the checkpoint's sequence and digest. Reject a database scope absent from
   the checkpoint and a checkpoint scope absent from the database.
4. Record only a non-secret checkpoint fingerprint, key ID, and success/failure
   state in startup evidence. Do not log raw grant bytes, paths outside the
   deployment contract, signatures, or private material.
5. Expose no Governance-backed route and start no worker capable of creating a
   Governance-approved decision until the gate succeeds. If activation mode is
   off, the route must remain absent or deny-by-default; a missing custody
   object must never silently enable it.

Exact equality is intentional. Accepting a database head newer than the
checkpoint creates an interval in which an uncheckpointed issue or revocation
can later disappear in a restore. A new signed event is operationally valid
but unavailable for approval until the separate checkpoint catches up.

### Running-process gate

Startup success is not a lasting authorization. Each Governance-backed new
decision, exact replay, and current approved-pair read must load a complete,
currently signed checkpoint and require the relevant scope's exact sequence
and digest to equal the database head while holding that head's transaction
lock. The current `CurrentShowrunnerGrantReader` checks only local database
history; it needs a separate, reviewed custody verifier before any production
route may use it. Do not cache a startup pass or the checkpoint head as an
authorization result. A committed import with an older checkpoint must make
that scope unavailable immediately, across all application processes; after a
matching checkpoint is published, the next transaction may admit it. A
missing scope in either input, unreadable or partially published checkpoint,
key mismatch, or head mismatch denies. The lock orders the decision against a
concurrent import, and checkpoint publication never advances the database
head. The transaction must read the checkpoint after acquiring the grant-head
lock, or re-read and revalidate it under that lock before committing.

The recovery startup gate still checks every scope and full signed history.
The per-transaction gate checks the current head against the externally
retained checkpoint and does not substitute for that full recovery scan. The
deployment drill must force both import-first and decision-first schedules
with an old checkpoint, across separate application processes, and show that
only decisions serialized before the import may succeed.

The restore procedure is consequently: stop the application and workers;
restore into an isolated target; supply the retained key/checkpoint inputs;
run the same full-chain/equality gate without starting workers; retain the
result with the restore evidence; only then start the pinned application image.
Any mismatch quarantines the restored target. Repair requires an offline issuer
operation and a newer signed recovery checkpoint; copying an older database,
attestation, or checkpoint over the mismatch is not a repair.

## Required recovery drill before activation

The first activation candidate needs a disposable PostgreSQL/Compose drill,
with command output and object fingerprints retained as evidence:

1. Import a signed ISSUE, publish its matching checkpoint, and demonstrate a
   clean gate pass.
2. Import and checkpoint a signed REVOKE; restore a snapshot taken before that
   REVOKE; demonstrate startup quarantine before workers/routes become ready.
3. Restore the matching post-REVOKE snapshot; demonstrate gate success and
   denial of the revoked scope.
4. Replace the checkpoint with an older validly signed checkpoint, alter its
   environment, remove a scope, add an uncheckpointed database scope, corrupt
   an event byte/digest, and replace the verifier with an unknown key. Each
   must fail closed before worker startup.
5. Exercise issuer-key rotation and a deliberately interrupted checkpoint
   publication. The old checkpoint must continue to govern until the new
   complete signed object is atomically installed; partial files and a
   new-event/old-checkpoint combination must deny.
6. Keep the application running while importing an ISSUE or REVOKE. Verify
   new decisions, exact replays, and current approved-pair reads deny for the
   affected scope until the matching checkpoint is visible to every process.
   Exercise publication during a locked reader transaction and verify that
   its observed checkpoint and database head are consistent.

## Limits and unresolved decisions

- A host administrator able to alter the Docker daemon, custody mount source,
  application image, and checkpoint history can defeat a host-local scheme.
  This design detects ordinary application-data/database rollback; it is not a
  defense against that fully privileged adversary. An external independently
  authenticated checkpoint service remains the escalation option if that threat
  is in scope.
- The repository has no approved key-generation ceremony, checkpoint signer,
  atomic host publication mechanism, environment identity source, retained
  checkpoint history location, cross-process import fence, or availability
  policy. Each needs a separately reviewed implementation/design packet.
- Key and checkpoint mounts alone do not make the existing floating application
  image trustworthy. Pin the exact deployment image digest and record it with
  the drill before relying on the gate.
- This note does not define database migrations, production Compose edits,
  grant-import transport, an issuer UI, live key material, or recovery
  activation. Those remain closed pending implementation, adversarial tests,
  independent review of the exact HEAD, and the drill above.
