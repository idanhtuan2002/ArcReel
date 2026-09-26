# R2 V1 P0 — M7-D H6 recovery closure design

Status: **DRAFT FOR SPONSOR REVIEW**. This document refines H6 implementation
within accepted ADR-0078; it is not M7-D acceptance, an implementation plan,
or authorization to operate a live backup or restore.

Candidate lineage: `feat/r2-m7e-v1-lineage` at
`4ad51b7778a8dbf7430767827106b77515e47221` before this draft.
This review revision starts from committed draft `92319182f88f5535d21c7ec6b170baadeb1e7c89`.
Research basis: [2026-09-25 M7 primary-source notes](../../research/2026-09-25-r2-m7-h6-h8-primary-source-notes.md).
Custody basis: [2026-09-25 H6 primary-source custody research](../../research/2026-09-25-r2-m7-h6-custody-policy-primary-sources.md).

## 1. Intent and scope

V1 needs a clean-target recovery drill for the *whole deployment state needed
by both selected products*, not a passing checksum for one project's candidate
files. The operator must be able to prove that the restored PostgreSQL data,
project records, artifact manifests, formal files, candidate media and every
approved master agree and that the selected products can be reopened, previewed
and exported without a provider call.

This design covers the H6 backup-set interface, persistence, capture, restore,
verification and runbook. It does not implement PITR, automated maintenance
mode, H7 telemetry closure, E1 upstream/provider attestation, browser/Golden
E2E, paid-route enablement, or production activation. Those remain separate
gates. The sponsor approved the V1 direction of initially enabling no paid
provider route; that choice does not exempt H6 or the later full outbound-route
inventory and enforcement work.

The accepted authority is ADR-0078's one `BackupSet` binding a PostgreSQL
recovery point to immutable media, release/schema/config identity, followed by
clean-target reference probes (`docs/adr/0078-durable-execution-evidence-and-recoverable-production-boundaries.md:72-79`).
Frozen H6 additionally requires project records, Artifact Manifests/formal
files and secure credential policy
(`docs/r2/R2_05_FROZEN_HOST_HARDENING_REQUIREMENTS.md:258-277`).
The M7 design's H6 steps and `VERIFIED` transition remain mandatory
(`docs/superpowers/specs/2026-09-12-r2-m7-host-production-hardening-design.md:553-605`).

## 2. Why the current implementation cannot meet H6

`create_backup_set()` dumps the whole database but enumerates candidate media
for one `(user_id, project_name)` and compares only that candidate count
(`r2/host_hardening/backup.py:224-295`). `verify_restored_backup_set()`
checks Alembic head, counts master rows and hashes only listed media; it does
not traverse DB/project/manifest/master references or probe playback
(`backup.py:349-386`). The Host's `project.json`, formal files and
`.arcreel_artifacts.json` are filesystem state outside that candidate list
(`lib/project_manager.py:289-312`, `lib/artifact_manifest.py:52-58`).

The current `backup_sets` row is project-scoped while its identifier and
media-reference foreign keys are global
(`lib/db/models/host_hardening.py:419-460`). Its retention query filters by
that project's scope (`lib/db/repositories/host_hardening.py:1130-1144`).
The `add_media_ref()` call flushes but does not commit before copying, so a
separate GC transaction cannot rely on seeing the PREPARING fence
(`backup.py:250-269`, `host_hardening.py:1100-1128`). The manifest path fields
are only non-empty strings (`r2/contracts/host_hardening.py:324-348`), then
restore joins them directly to filesystem roots (`backup.py:195-203,315-346`).

A whole-DB dump includes credential-bearing tables unless explicitly altered:
provider, agent, custom-provider and provider-config rows can contain secrets
(`lib/db/models/credential.py:26-35`, `agent_credential.py:31-36`,
`custom_provider.py:44-48`, `config.py:20-24`). The current runbook's
secret-free claim is therefore not supportable
(`docs/r2/runbooks/m7-backup-restore.md:96-103`).

## 3. Considered approaches

1. **Chosen design candidate: deepen the existing H6 module around one
   deployment-scoped `BackupSet`.** Preserve PostgreSQL and Host files as their
   current authorities; make the backup module assemble, verify and restore one
   recovery set from them. Explicitly migrate the project-scoped backup row
   vocabulary while keeping old rows and refs retention-safe. This matches the
   whole-DB dump and accepted H6 scope with one recovery identity. It requires
   a migration and a larger integration fixture, but it avoids a second
   backup catalog.
2. **One backup row/dump per project.** This reuses the current schema but
   repeats a whole-DB dump, introduces multiple backup identities for one
   recovery point, and cannot by itself prove that all files referenced by
   the shared database are present. Rejected for V1.
3. **Physical base backup or PITR now.** PostgreSQL's WAL chain improves DB
   recovery options but does not make external media atomic and needs an
   operational RPO/RTO target not approved for this baseline. Defer until a
   measured need and separate approval. See
   [PostgreSQL 18 continuous archiving](https://www.postgresql.org/docs/18/continuous-archiving.html)
   and ADR-0078:72-79.

## 4. BackupSet module and persistence interface

The external seam remains one backup module with three operations:
`create_backup_set`, `restore_backup_set`, and
`verify_restored_backup_set`. Callers supply explicit source/target DB and
file roots, deployment and release identity, and the typed fence/custody
evidence defined below; the module owns the ordering, inventory, digest,
safe-path and failure-state logic. It returns canonical manifest/verdict
schema version `1`. V1 readers reject unknown or unversioned schemas; a
future version needs an explicit migrator and independent compatibility test. A
caller cannot supply an arbitrary project subset for a whole-DB dump.

The forward migration adds an explicit `scope_kind` (`PROJECT_LEGACY` or
`DEPLOYMENT`) and nullable `source_deployment_id` to `backup_sets`. Its ORM
model stops inheriting the non-null `UserOwnedMixin`: it retains an explicit
nullable user FK and project name for legacy rows, and permits both to be null
only for `DEPLOYMENT`, with a database check constraint enforcing the two
shapes. Existing rows migrate to
`PROJECT_LEGACY` without deletion or reinterpretation. New H6 writes use only
`DEPLOYMENT`, a non-empty deployment ID, one global `backup_set_id`, and a
monotonic `state_version` for compare-and-swap transitions. The forward state
enum adds terminal `DISPOSED`; legacy state values retain their meaning.
An append-only `backup_set_transitions` table stores the unique idempotency
key, expected/new state and version, signed-evidence digest/reference and
transaction time; the row update and transition insert commit together.
`backup_set_media_refs` retains its existing globally unique candidate FK.
The retention lookup keys on `candidate_id` plus an active protected state and does
not filter by backup-set project, since candidate IDs are globally unique;
legacy and deployment rows in PREPARING, COMPLETE or VERIFIED all continue to
protect referenced candidates. REJECTED releases refs only after the audited
disposition transition commits; the new terminal DISPOSED state releases refs
only after the accepted set's independently audited custody disposal and
source transition commit. Neither elapsed time nor a repository delete API
result alone changes retention state.
The candidate deletion interface still verifies the caller's user/project
scope before using this global reference check. Migration tests cover both
row shapes and upgrade/downgrade safety on disposable PostgreSQL. Downgrade
restores the old non-null `user_id`/`project_name` constraints only when no
`DEPLOYMENT` row remains; otherwise it fails closed without dropping rows.

`CustodyOperationRegistryV1` is the independent, durable admission authority
for canonical source/target DB, media and staging root identities. In the
same transactional registry, each source deployment has one versioned capture
slot, each isolated recovery target has one versioned restore slot, and all
slots contend for unique active claims on normalized root/mount identities;
aliases or a second deployment cannot claim an overlapping root. Capture
states are IDLE, CAPTURING and STAGING_UNRESOLVED; restore states are IDLE and
RESTORING. An active slot binds exact set/attempt or restore-request ID,
owner, claimed roots and immutable audit reference. A ledger transaction
atomically claims all relevant roots and CASes the appropriate IDLE slot to
CAPTURING or RESTORING **before** source PREPARING insertion, staging creation,
decrypt or target mutation. A new source capture cannot bypass an unresolved
capture slot with a new `backup_set_id`; a conflicting slot/root claim fails
`BACKUP_CAPTURE_DOMAIN_BUSY`. Crash or lease timeout never clears a claim:
uncertain capture becomes STAGING_UNRESOLVED and remains blocking until signed
disposition. Disposition, source rejection, receipt acceptance, restore
completion and fence release all validate the relevant slot version/owner;
only after audited terminal conditions may CAS return it to IDLE and release
its root claims.

An unresolved source capture does **not** bar a separately approved restore of
an earlier ledger-ACCEPTED set into a disjoint clean target when the restore
lease, target-root claims and no-source-staging-access check all pass. That
restore uses the same registry authority but a separate target slot; it
cannot clear the source quarantine or consume objects from the interrupted
attempt. A target overlapping an unresolved staging/source claim fails
`BACKUP_STAGING_UNRESOLVED`; other claim conflicts fail
`BACKUP_CAPTURE_DOMAIN_BUSY`. An unaccepted set or absent independent ledger
proof fails closed. This preserves disaster recovery if the source DB is lost
before a PREPARING row can be inspected. If the registry itself is unavailable,
admission fails closed. Disposable tests use a transactional fixture;
production needs an approved independently controlled registry adapter, not
an in-process mutex or a check-then-insert sequence.

The manifest revision records the exact database archive digest/size and a
sorted complete physical inventory. A file entry is keyed by approved logical
root and canonical relative path, has byte size and SHA-256, and carries a
storage class (`PROJECT_FILE`, `GLOBAL_ASSET`, or `CANDIDATE_MEDIA`) plus a
sorted set of semantic bindings. Zero bindings means an unreferenced
project/global file; admitted candidate media must have at least one
candidate/master binding. The bindings identify, where
applicable, project metadata, Artifact Manifest/formal claim, profile state,
version index/snapshot, DB global-asset table/row/field, candidate ID,
storage object version (distinct from candidate ID), media kind and
capture-time probe result. Several DB bindings may legitimately name the
same physical file; conflicting observed hashes for one physical identity
fail capture rather than selecting one binding. Directory-presence entries
record exact project/global-root and empty-subdirectory existence without
inventing file bytes or a SHA-256 digest. Absent optional manifests/roots
have explicit presence records, distinct from present empty files/directories.
`GLOBAL_ASSET` is under the approved project root but is not a project:
`_global_assets` is excluded from `ProjectManager.list_projects()` while
DB `assets`/`asset_derivatives` rows can reference its files. Capture binds
those DB references and files, never silently omitting them from a whole-DB
set ([source reconciliation](../../research/2026-09-26-r2-m7-h6-project-inventory-authority.md)).
The capture reader derives `_global_assets` beneath the approved project root
without calling the write-capable `get_global_assets_root()` helper. An absent
root is not silently created; its admissibility depends on the frozen
DB-reference and orphan-file policy below. This revision proposes that an
absent root is valid only when no DB row references it; an empty present root
is a distinct state, and unreferenced regular orphan bytes are retained.
A local immutable object is pinned by its content digest and re-hash under
the write fence; a remote mutable object additionally needs an immutable
object-version ID or equivalent content-addressed read. A master reference
outside the approved root set is a typed `BACKUP_REFERENCE_OUT_OF_SCOPE`
failure, never silently omitted. The manifest binds source deployment, release Git/image,
PostgreSQL/Alembic and the V1 configuration fingerprint described next. It
stores no DB connection string, plaintext credential, encryption key or
absolute path. A source with no admitted project directories or a missing
`project.json` fails `BACKUP_REQUIRED_INVENTORY_EMPTY`. A project with zero formal files is
valid only when its restored DB and Artifact Manifest have zero formal-file
references. The Host adapter legitimately represents an absent, empty
`.arcreel_artifacts.json` as an empty manifest; the inventory records and
verifies that absence, while still copying `project.json`.

### Project-file census and reference closure (V1 proposal)

The source inventory has two different obligations. First, a no-follow
physical census records every regular file and directory under each admitted
project and `_global_assets`. Candidate/master rows separately select the
media objects to capture under approved media roots; this proposal does not
silently expand into an unbounded sweep of unrelated media-store objects.
An unrecognized regular project file is retained as an opaque `PROJECT_FILE`
with no invented formal claim; it is never silently excluded. V1 proposes
capturing even regular lock-named files as opaque bytes: current writers can
derive dynamic `.{target.name}.lock` paths, so a name match alone cannot prove
that an existing file is disposable runtime state. A blanket `*.lock` or
hidden-file glob is never an exclusion. A lock-named symlink, junction, socket,
device or other unsupported entry is a typed reject, not an exclusion. The
entire project-file payload, including `.claude/`, `CLAUDE.md` and
`.arcreel_profile_manifest.json`, falls under authenticated-encryption custody.
Profile sync must not run before restore verification compares the captured
bytes, manifest presence and deletion tombstones. Existing portable archive
export is not the capture adapter because it hides dotfiles and can trim
version history.

Second, a release-pinned reference classifier walks the **known** fields in
`project.json`, episode scripts, `grids/grid_*.json`, Artifact Manifest,
`versions/versions.json`, quarantine drafts and their source selectors,
persisted presentation/subtitle projections,
versioned task submission checkpoints and provider-media staging manifests,
global-asset DB rows, candidate/master rows and other approved DB-to-file
authorities. Each nonempty local reference becomes a binding on an inventoried
file, even when the ordinary `DataValidator` does not check that field (for
example `video_thumbnail`, product originals/sheet or derivative sheets).
It distinguishes an intentionally pending `episodes[*].script_file` from a
missing existing script using the approved ledger predicate, and classifies
`video_uri` by its *value*: local path binds bytes; an approved external URI
gets a typed remote-reference record, never a fabricated local file. Empty,
null, absent and present-empty values retain their distinct source states.
An unrecognized version of a declared reference-bearing schema, an
unsupported declared reference type or a known reference outside approved
roots fails closed. An arbitrary string in an otherwise opaque file is not
assumed to be a file reference; the review must enumerate every authoritative
reference-bearing field and its version before this rule can be implemented.
Opaque physical bytes do not make an unclassified declared reference valid.
Grid records require a read-only, version/shape-aware parser for their
`script_file`, `grid_image_path`, `frame_chain[*].image_path`, and
`reference_images[*].path` fields. The status-dependent pending and required
rules remain a V1-02 approval item; a UI list that skips malformed grid JSON
is not evidence of complete capture.
Presentation and task-checkpoint paths need their own versioned field maps:
an absent optional presentation differs from a present but divergent
projection, and a cleaned terminal task differs from an active checkpoint
whose immutable staged media is missing. The V1-01 task-state disposition and
V1-02 file rule must agree before either is admission authority.
Quarantine-draft `meta.source` can name a project file or select the derived
episode source when null; malformed or obsolete drafts need an explicit
disposition rather than a filename-based exclusion.

The classifier does not call any
write-capable project load, archive repair, profile sync, version restore or
root-creating helper during capture.

The bounded census rejects a source exceeding the approved file-count,
per-file or aggregate-byte limits without silently truncating it. Missing
required local bytes fail `BACKUP_REQUIRED_FILE_MISSING`; unknown reference
semantics fail `BACKUP_REFERENCE_UNCLASSIFIED`. Traversal, absolute alias,
symlink/junction in a declared reference or wrong logical root fails the
existing `BACKUP_REFERENCE_OUT_OF_SCOPE`; an unsupported entry discovered by
the physical census fails `BACKUP_INVENTORY_ENTRY_UNSUPPORTED`. Sanitized
failures identify a binding key or
opaque entry ID, not a secret-bearing absolute path.

The generic physical path interface is separate from Artifact Manifest's
formal-path validator. It admits only canonical relative paths under one
logical root, rejects absolute/drive/URI/traversal aliases, then rechecks
root containment and no symlink/junction at every capture and restore read.
Version index and every recorded snapshot are retained as distinct bindings,
including unselected and rejected-but-retained versions; an absent
`versions.json` is not synthesized. A `versions.json` record whose snapshot
bytes are missing fails
`BACKUP_REQUIRED_FILE_MISSING`, even though the current `add_version()` API
can persist such a record after its source file disappears. No normal
production caller intentionally declares a pending snapshot; an operator
must inspect and repair the source before a new exact-recovery attempt or
leave the attempt rejected. An unreferenced regular file (including a
global-asset orphan or post-purge history snapshot) is captured with an
`UNREFERENCED` disposition, not silently dropped or automatically treated as
corruption. Any DB/JSON reference whose required file is missing is a typed
reject. This preserves actual source bytes while leaving classification of
pre-existing dangling/pending states to the reviewed reference table.

The alternatives are a formal-file allowlist (loses profile/history/opaque
user data), a blind tree copy (cannot prove DB/JSON reference closure), or
this paired census/classifier. The paired option is the V1 recommendation,
subject to the explicit review gate below; it preserves bytes while rejecting
known dangling authority claims. This proposal is based on the [project-tree and file-authority research](../../research/2026-09-26-r2-m7-h6-project-inventory-authority.md)
and [bounded writer/reader map](../../research/2026-09-26-r2-m7-h6-path-writers.md).
It does not settle project lifecycle admission or approve a production
custody profile; both gates remain in §8.

`configuration_digest` is SHA-256 over canonical `RecoveryConfigV1`, not an
arbitrary caller dictionary. Required fields are the source deployment ID;
release image digest and Git SHA; exact PostgreSQL server image digest and
`pg_dump`/`pg_restore` client binary/version identities; exact `ffprobe`/
`ffmpeg` decoder binary/version identities; logical
project/media root IDs; the non-secret, normalized effective production
Compose service/writer inventory and network-egress policy; and the digest of
the provider-route enablement policy (including the V1 no-paid-route setting).
It records the hashes of the release-bundled Host capability registry and
agent-runtime profile as independently checkable inputs. DB-backed provider
settings are already in the database archive and are checked there; secret
values, absolute mount paths and password-bearing environment variables are
never serialized into this fingerprint. Restore compares these logical
authority fields against an independently supplied target/release policy,
allowing remapped empty target paths but not a different route or release
profile. Missing fields or an unapproved source/target mismatch fail
`BACKUP_CONFIGURATION_MISMATCH` before target mutation.

### 4.1. Fence evidence interface

`CaptureFenceEvidenceV1` is a versioned, canonical operator evidence bundle,
not a free-text flag. The privileged operator wrapper creates it; the H6
module verifies it before inserting PREPARING. The pre-capture record requires
`backup_set_id`, `source_deployment_id`, release identity, approved logical DB
and file-root IDs, `writer_inventory_digest`, named custodian principal and
role, UTC `fence_started_at`, UTC `quiescence_confirmed_at`, UTC
`fence_expires_at`, and one evidence item for *each* app, worker, recovery
scanner and GC/cleanup writer in the approved inventory. Each item names the
service/instance, observed stopped/drained state, observation time, evidence
type (`SERVICE_MANAGER_STATUS` or `OPERATOR_COMMAND_TRANSCRIPT`), protected
evidence-store ID, immutable object/version reference, byte size and SHA-256.
The required
`POSTGRES_WRITER_SESSION_CHECK` item records the monitored DB identity,
observed active writer sessions/transactions (zero except the named monitor),
query time and hashed result. The required `ROOT_MOUNT_IDENTITY_CHECK` item
records the approved root IDs, canonical path/device or mount identities,
no-alias/no-symlink result, observation time and hashed result. A mere operator assertion or a
candidate count is not an accepted substitute for these observations.

The custodian signs the canonical start record with an approved operator
signing identity outside the application runtime. V1 uses an Ed25519 detached
signature over the exact canonical JSON bytes (duplicate keys and non-finite
numbers are invalid); the record carries signer key ID and signature, never
the private key ([RFC 8032](https://www.rfc-editor.org/rfc/rfc8032)). The verifier checks its
signature against the release-approved public-key allowlist in
`RecoveryTrustRootV1`, pinned outside the backup directory and not replaceable
by the evidence-submitting caller. The same independently pinned trust root
binds each allowed signer key ID to the exact named custodian principal and
role; a valid signature from another allowlisted custodian is not authority
for this custodian. It also checks the role, exact deployment/set/release
bindings, complete writer inventory, ordering and expiry. **Before inserting
PREPARING**, the module resolves *every* referenced item from the approved append-only evidence
store by exact object version, reads it through a bounded, no-follow path,
checks nonempty bytes, byte size and SHA-256 against the signed record, and
validates its declared evidence type. A signed record with a missing or
tampered underlying status/transcript is missing evidence, not a pass. Missing,
untrusted, malformed, stale or mismatched start proof fails typed
`BACKUP_FENCE_EVIDENCE_INVALID` *before any backup row or file write*.
The signature attests who observed the fence and what evidence was captured;
it is not a claim that the module physically stopped external processes.

After the copy and dump, while writers remain stopped, the same wrapper emits
a signed closure record with UTC `capture_checks_completed_at`, UTC
`fenced_capture_ended_at`, the same identities, and final service/DB/root
evidence digests. The accepted capture window is
`[quiescence_confirmed_at, fenced_capture_ended_at]`; every inventory read,
copy, dump snapshot and final drift check must fall inside it and before
expiry. The operator releases the writer fence only after the manifest is
sealed, the source COMPLETE transaction commits **and** the exact receipt is
ACCEPTED by the independent ledger and the operation-registry claim is
audited/cleared, recording the actual release separately in the operator
audit log. An exceptional aborted capture follows the signed
disposition path in §5 and records a separate fence-release audit; it never
creates an accepted backup.
The manifest binds the digest of both records and the encrypted backup set
contains them as separate evidence artifacts. The module fetches and checks
every closure evidence blob from the same approved store before manifest seal.
Missing/invalid closure proof or underlying blob
fails `BACKUP_FENCE_EVIDENCE_INVALID` and leaves the row PREPARING for inspected
disposition; there is no fabricated window end at capture entry.

## 5. Capture protocol and crash behavior

1. The operator stops the app, worker, recovery scanner and cleanup writers;
   records the exact deployment/process and storage roots; and confirms all
   writes are quiescent through the signed `CaptureFenceEvidenceV1` start
   record (§4.1). The H6 module verifies that evidence before claiming the
   §4 operation-registry slot or mutating backup state, then atomically claims
   the deployment and root identities; it does not claim it physically
   stopped an external process.
2. Read all candidate/master/project identities, project-file references,
   and global-asset DB/file references from the fenced source. Enumerate
   admitted project directories separately from project-scoped DB rows and
   reconcile them under the approved liveness/classification table described
   below; `_global_assets` is an independent inventory role, not a project.
   Run the physical census and reference classifier above, hash every
   project/global-asset/candidate file, and perform the capture-time media
   probe that will be recorded in the inventory. Preserve directory and
   absent-versus-empty presence separately from file hashes.
   Refuse missing owners, divergent master projections,
   paths outside approved roots, symlinks/junctions, duplicate refs with
   unequal bytes, or mutable/unversioned media that cannot be pinned.
3. Under the exact active CAPTURING registry claim, in a short DB transaction
   insert one `DEPLOYMENT` PREPARING set and all
   candidate retention refs, then **commit before copying any bytes**. A
   separate transaction must be able to observe the refs. A crash leaves a
   visible PREPARING set whose media refs continue to block GC without a time
   limit until an explicit inspected rejection; a new backup attempt is a
   separate operation, not a prerequisite for releasing rejected refs. There
   is no timeout-based or silent cleanup. The only source-row transitions are
   `PREPARING -> COMPLETE`, `PREPARING -> REJECTED`, and
   `COMPLETE -> VERIFIED` as a projection of an accepted external verdict,
   plus the exceptional `COMPLETE -> REJECTED` admission-failure transition
   and authorized `COMPLETE/VERIFIED -> DISPOSED` transitions defined below.
   Each transition uses `(backup_set_id, expected_state, state_version)` CAS,
   increments the version exactly once, and carries an idempotency key;
   zero-row or conflicting retries fail `BACKUP_STATE_CONFLICT`. There is no
   `REJECTED -> COMPLETE` or `REJECTED -> VERIFIED` path. `PREPARING -> REJECTED` requires an
   authorized custodian's signed `BackupDispositionV1` audit record naming
   set/deployment, inspection time, reason, inspected files/refs, any issued
   custody receipt and its revocation/disposition, and the disposition
   transaction ID. A PREPARING set is never restore-admissible, even if a
   receipt was issued just before a crash. The state
   transition and audit reference commit atomically; only then may retention
   release its refs. A failed validation cannot self-mark REJECTED and release
   refs without this evidence.
   If a source row reached COMPLETE but ledger acceptance failed permanently,
   the custodian must first CAS the exact PREPARED ledger receipt to ABANDONED;
   the ledger must prove there was no ACCEPTED record, restore admission or
   active restore lease for that set. A signed
   `AdmissionFailureDispositionV1` binds this proof, the set/receipt/version,
   inspection of ciphertext/staging and its disposition, and the operator
   reason. Only then may source `COMPLETE -> REJECTED` CAS and audit insert
   commit together and release GC refs. An unavailable ledger cannot provide
   negative proof; the set remains protected until repair, never timeout-
   rejected. A successfully ACCEPTED COMPLETE set cannot use this path.
   For an ACCEPTED COMPLETE or VERIFIED set, disposal first verifies the
   approved retention deadline and holds, that a newer ledger-accepted
   VERIFIED set remains recoverable for an active deployment, and that no
   restore lease is active. Two distinct
   authorizers sign `CustodyDisposalRequestV1` naming exact set, ledger
   sequence, repository object versions, wrapped-key reference and policy
   version. The independent ledger CASes the set to non-admissible
   `DISPOSAL_PENDING` before any object/key deletion, excluding new restore
   leases. After repository and key-custody deletion plus independent
   verification, a signed `CustodyDisposalReceiptV1` binds request, actors,
   hold/retention checks, every object/key operation and audit ID, and
   verification evidence-store references/versions/sizes/digests. The ledger
   verifies those blobs and CASes to terminal DISPOSED, retaining an immutable
   tombstone, receipt and prior verdict history. Only then may source
   `COMPLETE/VERIFIED -> DISPOSED` CAS and audit insert commit together and
   release candidate refs. A crash between ledger and source commits leaves
   refs overprotected until idempotent reconciliation; missing proof, a hold,
   an active restore lease or unavailable ledger never releases refs. A
   DISPOSED set cannot be restored or become COMPLETE/VERIFIED again.
4. Copy the complete project-file, global-asset and candidate-media
   inventory into a private, explicit destination. Hash source and destination
   for every role. Run a
   whole-database custom-format `pg_dump` while the same write fence holds,
   then hash the archive. Re-enumerate all DB identities/revisions and all
   project, global-asset and candidate-media file identities, directory and
   presence records, binding sets, sizes and SHA-256 hashes against the frozen
   step-2 inventory;
   a same-path content edit is drift too. The end check also re-probes media
   metadata. Any mismatch fails `BACKUP_SOURCE_DRIFT`; no identity-only
   shortcut is accepted. This is defense in depth, not a claim that two
   independent stores acquired a shared transaction snapshot.
5. Obtain and verify the signed §4.1 fence-closure record. Canonicalize and
   seal the *inner* manifest after all source/destination, archive and fence
   checks pass; encrypt and stage the set, verify and dispose plaintext staging,
   then issue and verify the independent §6 custody receipt against that
   finalized manifest digest. The recovery ledger reserves its deployment-
   scoped sequence and stores the signed receipt as PREPARED, not admissible.
   Only then
   transition the *source* backup row to COMPLETE with expected-state/version
   CAS, publish acceptance of that exact prepared receipt/sequence in the
   independent recovery ledger by CAS, and only
   then CAS the registry claim to IDLE and release the writer fence with a
   signed audit. Receipt issuance alone does not permit a
   restore: admission requires the ledger's exact COMPLETE/VERIFIED set and
   custody receipt IDs/versions. If ledger publication fails after the source
   commit, the set stays unavailable for restore pending audited repair; no
   cross-store atomicity is presumed. In a disposable test profile, a fixture
   receipt exercises the same ordering but cannot authorize a production
   completion or verdict. Failed
   or interrupted sets remain PREPARING or become REJECTED only through the
   audited inspected transition above. An abort may release the operator's
   writer fence only after a signed fence-abort record and inspected staging
   disposition; it leaves any unresolved PREPARING/COMPLETE refs protected
   and cannot advertise this set as a recovery point. The registry claim
   remains blocking until the source rejection/admission-repair condition is
   also audited; fence release alone never clears it. The DB archive may
   contain the
   PREPARING row because it was taken before the source COMPLETE transition;
   restore verification must recognize that exact captured state rather than
   invent a completed backup row inside the snapshot.
   The previous independently admitted COMPLETE set remains retained until
   the new set is visible in the recovery ledger; a crash in this publication
   gap cannot be treated as successful replacement of the last recovery set.

The manifest and archive are integrity checked before restore; digest equality
alone does not authenticate an untrusted archive. The §6 custody receipt,
independent trust anchor and authenticated decryption must pass before any
target mutation. Neither successful decryption nor a signature alone proves
freshness without an independently maintained accepted-version record;
public-key recipient encryption alone does not prove who produced the bytes.
PostgreSQL warns that restoring a dump can execute source-selected code
   ([PostgreSQL 18 `pg_dump` warning](https://www.postgresql.org/docs/18/app-pgdump.html)).

## 6. Credential custody and restore fence

The DB archive is **secret-bearing**. V1 does not use a partial-table dump to
pretend otherwise: `provider_config` can mix secret and nonsecret rows, and
excluding only a few whole tables would make the recovery result ambiguous.
The existing production Compose file declares neither an archive repository
nor a key manager (`deploy/production/docker-compose.yml`); no actual operator
retention schedule or signing trust root was evidenced in the inspected
runbook/deployment files. Selecting a product or inventing those values here
would be a false operational decision.

The V1 *custody contract* is nevertheless fixed before implementation:

1. The complete DB dump, project files (including formal, profile, history
   and opaque files), candidate media and protected
   fence evidence are encrypted as one logical set before leaving private
   short-lived capture staging. Production staging must itself be an
   access-controlled encrypted ephemeral volume with owner-only permissions,
   no unencrypted swap/core dump and an explicitly recorded volume/key ID,
   not the existing arbitrary durable `backup_dir`. A crash leaves it
   quarantined; the operation registry refuses a new capture or any operation
   that touches those source/staging roots with `BACKUP_STAGING_UNRESOLVED`
   until an operator inspects and validates its
   sanitization. The interrupted attempt is never resumed: after disposition,
   a new capture needs a new set/attempt ID, fresh fence, DEK and nonce state.
   A signed `StagingDispositionV1` records set/deployment and attempt IDs,
   volume/key identity, disposition action, actor, approval, time, tool/result,
   and the exact sanitized roots and verification observations. Its signed
   record and underlying evidence have independently protected evidence-store
   IDs, immutable object versions, byte sizes and SHA-256 digests. Before
   source COMPLETE or a new attempt, the verifier fetches those exact blobs
   through the bounded evidence adapter, validates signatures, sizes/hashes,
   root identities and the recorded sanitization result, and rejects missing
   or tampered proof as `BACKUP_STAGING_UNRESOLVED`. Disposition CASes the
   same deployment/root registry claim before a fresh attempt can acquire it;
   a per-set backup-row CAS cannot authorize a new attempt. The custody receipt binds
   the disposition record's reference/version/digest; no source COMPLETE
   transition occurs while plaintext staging remains unresolved. Merely
   unlinking a file is not accepted as proof of sanitization.
   Each stored object uses an approved `CustodyCryptoProfileV1` and a fresh
   cryptographically random per-encryption-attempt data-encryption key (DEK),
   with authenticated associated data binding set/deployment/object role/
   schema and provably unique nonce under each DEK. A retry, including after
   a crash, discards the old attempt ID, DEK and nonce state and allocates a
   new attempt only after verified disposition; it may never resume with an
   uncertain key/nonce state. The DEK is wrapped by an
   independently administered, versioned key-encryption key (KEK). Plaintext
   archives/DEKs cannot be left in the durable repository; failure to encrypt
   and verify ciphertext is `BACKUP_CUSTODY_UNSEALED`.
2. The repository holds ciphertext and wrapped-DEK references only, enforces
   versioned immutable objects or equivalent append-only retention, and
   exports stable object/version IDs and write/read/delete audit IDs. Archive
   writer, retention administrator, restore operator, key custodian, manifest
   signer and auditor have distinct least-privilege identities. The normal app
   cannot administer the KEK or delete archives. Restore/decrypt requires a
   time-limited, independently approved request; deletion/key destruction
   requires two authorizers after recorded retention and hold checks.
3. The signer produces a V1 Ed25519 detached signature over the **entire
   canonical `CustodyReceiptV1` body** (all identity, manifest, ciphertext,
   AEAD/nonce/AAD, wrapped-key, admission, audit, retention and hold fields;
   only the signature field is excluded). A trust anchor and latest accepted
   set/version ledger are held outside the mutable archive repository. The
   ledger reserves a strictly increasing sequence per source deployment when
   the receipt enters PREPARED state. That sequence is part of the signed
   receipt body; the ledger advances its latest *accepted* sequence only by
   compare-and-swap after source COMPLETE, binding the signed receipt ID/digest
   and immutable object-version list. Abandoned reservations may leave gaps
   but cannot become restore-admissible. Restore rejects a bad signature,
   unknown/revoked signer, unrecognized object version or rollback before
   decrypting; authenticated decryption rejects modified ciphertext before
   parsing/executing it. SHA-256 inventory checks then catch accidental
   mismatch against the authenticated manifest. `RESTORE_ARCHIVE_AUTH_FAILED`
   covers signature, anti-rollback, tag or bound-context failure. This does
   not claim that a malicious source database is safe to execute. An older
   signed set may be restored only with a separately signed, two-person
   `RecoveryRollbackOverrideV1` naming the target deployment, exact older
   sequence/set, current latest sequence, reason and expiry; the ledger records
   that override before decryption. There is no implicit “latest file wins.”
4. The deployment's approved `CustodyPolicyV1` must name the actual repository
   and location, approved `CustodyCryptoProfileV1` ID/digest, KEK
   boundary/owner, signer/trust-anchor distribution, role
   grants, retention-until and hold policy, archive cadence, and isolated
   restore procedure, plus approved `max_rpo_seconds` and `max_rto_seconds`
   for the exact V1 corpus/deployment. The app implementation can define and test the typed
   interface with disposable test keys, but no production backup/restore or
   `RECOVERY_VERIFIED` claim is possible until this policy and a real drill
   receipt are approved. This is the deliberate staged-implementation choice:
   it replaces the earlier research note's undifferentiated “before
   implementation or release” wording, while retaining the hard operational
   gate. It does **not** mark the H6 implementation or M7-D accepted.

`CustodyCryptoProfileV1` is a separate signed, release-pinned input, not a
free-form suite string from an archive. Before any production adapter code or
archive can be accepted, it must specify an independently reviewed,
interoperable authenticated-encryption format and implementation digest;
algorithm/suite ID, key and nonce/tag sizes, RNG source, per-object/chunk
size bounds and final-length authentication, associated-data encoding,
wrapping format, retry/new-key rule, and published test vectors. The verifier
has an explicit allowlist of approved profile digests outside the archive and
rejects an unknown or absent profile as `BACKUP_CRYPTO_PROFILE_UNAPPROVED`.
No profile is currently pinned in the inspected deployment files. The core
packet may test rejection and interface shape, but may not invent crypto or
call its fixture a production custody adapter. Choosing a vetted format and
proving it with real ciphertext tests is the first gate of the later
deployment-bound packet.

`CustodyReceiptV1` is the named, signed, access-controlled capture/admission evidence
artifact stored in the independently controlled recovery evidence ledger.
The inner manifest binds the `CustodyPolicyV1` ID/digest and its approved
`CustodyCryptoProfileV1` ID/digest, while the receipt
binds the finalized inner-manifest digest; the manifest does **not** hash the
later receipt (which would create a circular digest). `BackupVerdictV1`
references the receipt and its digest. The receipt requires schema version,
set/deployment/release IDs; `CustodyPolicyV1` and
`CustodyCryptoProfileV1` IDs/digests; canonical manifest
digest; every plaintext size/digest and ciphertext object key/version/size/
digest; AEAD suite, exact per-object nonce/tag, canonical AAD schema/version
and AAD digest, and wrapped-DEK reference/KEK version (never raw keys);
staging-disposition evidence-store reference/version/size/digest; signing key
ID/signature and trust-anchor version; admission
actor/time/audit IDs, reserved ledger sequence; and retention-until and hold
state. A separate signed
`RestoreCustodyAttestationV1` binds the receipt ID/digest to restore request,
approver, isolated target, decryption/authentication result and audit IDs;
it is created during the drill, not fabricated at capture time.
`BackupVerdictV1` has `custody_evidence_ref`, `custody_evidence_digest`,
`restore_custody_attestation_ref`, `restore_custody_attestation_digest`,
`external_secret_disposition_ref`, `external_secret_disposition_digest`,
`recovery_ledger_sequence`, `crypto_profile_id`, `crypto_profile_digest`,
verdict signer key ID/signature and
`custody_status` (`NOT_CONFIGURED`, `REJECTED`, `VERIFIED`). Absent, malformed,
untrusted or non-production receipt or restore attestation is
`RESTORE_CUSTODY_UNVERIFIED` and cannot
yield accepted/`RECOVERY_VERIFIED`; a local test fixture is test evidence only.
The receipt's reference is outside the archive so a repository-local forged
copy cannot supply its own trust anchor or accepted-version watermark.

The runbook must remove its incorrect secret-free claim. The module never
prints a DSN/password in argv, manifests, errors or logs; libpq authentication
uses a protected password file or equivalent verified secret channel, not a
password-bearing command argument. [PostgreSQL 18 libpq password-file rules](https://www.postgresql.org/docs/18/libpq-pgpass.html)
apply. Cluster-wide roles/tablespaces and external secret provisioning are
not covered by a per-database `pg_dump`; the selected restore profile must
either prove they are not required for the V1 target or provision and verify
them separately before acceptance.

The V1 source has a concrete external-file dependency: Vertex credential
uploads live in a separately mounted `vertex_keys` directory while
`provider_credential.credentials_path` stores their source absolute path.
Legacy `provider_config` may also hold a path, and the text/video backends
resolve a file directly from `vertex_keys`; the image backend can do the same
when no path is supplied
([inventory research](../../research/2026-09-26-r2-m7-h6-project-inventory-authority.md)).
The protected, signed `ExternalSecretDispositionV1` is the named restore
evidence artifact referenced by the verdict fields above. It binds the exact
backup set, authenticated custody receipt, restore request and isolated target,
release/configuration and route-policy digests, signer/trust-anchor version,
and a complete release-pinned census of DB path references and implicit
resolver-based secret-file selectors. Each entry identifies its source row
and field or backend resolver/route, target logical secret slot, disposition,
and evidence refs/digests; no source absolute path or secret bytes enter the
public inventory or disposition. The verifier obtains the signed artifact and
its accepted version from the independently controlled recovery evidence
ledger, then checks its census against the restored DB, bundled backend map
and effective target route policy. An archive-local copy cannot establish
trust or completeness.

Each dependency is either `PROVISIONED_VERIFIED`, backed by independently
approved target-provisioning and isolated file/readability evidence plus a
verified remapped target binding, or `DISABLED_NOT_REQUIRED`, backed by the
exact disabled-route policy and a no-provider drill covering the explicit
path and implicit resolver routes. A restored absolute source path is never
treated as a usable target credential. Missing or extra census entries,
an enabled route labeled not-required, an unremapped source path selected by
an enabled target route, or failed provisioning/readability/no-provider
evidence rejects with `RESTORE_EXTERNAL_SECRET_UNRESOLVED` before any fence
lift. This contract does
not authorize copying live secrets into the project archive, making a provider
call, or claiming production custody without the §6 policy gate. The proposed
V1 no-paid-route profile permits only `DISABLED_NOT_REQUIRED`; that profile's
effective disablement and drill still require approval. A profile using
`PROVISIONED_VERIFIED` requires a separate design and operational decision.

Restore first authenticates the custody receipt and ciphertext, then validates
manifest schema, identity, complete digests and all relative paths—including
symlink traversal—*before any target mutation*. Both target DB and project/
media roots must be empty and isolated. It restores the DB and files with no
production provider credentials or outbound access, then keeps app, worker,
provider egress and cleanup disabled until verification passes. Missing files,
wrong release/schema/config, custody evidence, or any reader/probe failure
reject the set; there is no partial-success verdict or automatic activation.

## 7. Verification interface and acceptance evidence

Verification first asserts that the restored `backup_sets` row has the exact
`backup_set_id`, `DEPLOYMENT` scope, source deployment ID and captured
`PREPARING` state recorded as `captured_backup_row_state` in the sealed
manifest. `COMPLETE` is the later
*source-side* state and must not be invented inside the snapshot. Missing,
different or already-COMPLETE restored rows fail `RESTORED_BACKUP_ROW_MISMATCH`.

Verification then repeats the project/global-root physical census and the
release-pinned reference classification on the restored DB and project files.
It checks exact directory/presence records, all restored files (including
opaque/unreferenced bytes, profile state and every retained version snapshot),
all semantic binding sets, global-asset rows/files, candidate objects and
approved master heads against the sealed inventory. A restored extra file or
binding is a mismatch, not merely a harmless addition. It resolves each head through
`DatabaseMasterResolver` with its legacy projection where
applicable, reads formal files through the Host's guarded artifact adapter
and media through the bounded candidate store, checks size/hash and probes
actual media playability. For every
playable video/audio candidate, the strict probe must recognize the expected
container and stream kind, produce finite positive duration and decode the
entire selected media stream with a no-network, bounded-time local decoder;
capture and restore must use the pinned decoder version and match the exact
canonical probe-result digest, including integer-millisecond duration and
stream metadata, recorded in the manifest. Still-image
media must parse and fully decode pixels with nonzero dimensions. Unsupported
kind, missing `ffprobe`/decoder, `None` from the existing permissive duration
helper, nonzero decoder exit or timeout is `RESTORED_MEDIA_UNPLAYABLE`, never
a skipped acceptance check. The probe records tool/version and result digest
([FFprobe format/stream inspection](https://ffmpeg.org/ffprobe.html),
[FFmpeg decoding](https://ffmpeg.org/ffmpeg.html)).
It rejects unlisted authoritative references as well as listed-but-missing files.
An absent/present-empty mismatch, changed opaque file, changed profile
tombstone, omitted historical snapshot or newly unbound local path fails
`RESTORED_INVENTORY_MISMATCH`. No profile sync, archive repair or version
materialization runs before this comparison.
Only after complete closure may the independent recovery-evidence ledger
record `VERIFIED` for the set. If the source DB still exists, its backup row
may reflect that verdict as a projection; the restored snapshot's row remains
PREPARING. The verdict reports checked project, project-file, profile,
version-index/snapshot, formal-binding, global-asset, candidate, master and
media counts, typed reason codes, measured recovery
point/RPO/RTO, exact release identity and the following timing evidence
references/digests. Before a drill, an independent drill authority signs
`RecoveryDrillRequestV1` with
the exact scenario, target deployment/set, corpus, `CustodyPolicyV1` ID/digest
and RPO/RTO targets. At simulated cutover, **before approval, retrieval,
provisioning or any recovery action**, that authority appends a signed
`RecoveryFailureEventV1` with event ID, request ID, UTC failure time and
monotonic-clock reading to the independent evidence ledger. Neither the
operator nor verifier may choose a later failure time after observing restore.
The ledger's immutable object/version, size and SHA-256 for both records are
fetched and verified; missing, late, mutable or mismatched records fail
`RECOVERY_MEASUREMENT_INVALID`.

The recovery point is the signed quiescence-confirmation time, accepted only
when the dump and final no-drift check remain within that fence. Drill RPO is
the signed failure-event time minus this recovery point. Live RPO instead uses
an independently recorded actual incident time, never dump completion. RTO
begins at that same failure event and ends only when the signed readiness
verdict records that approval, repository retrieval, isolated provisioning,
authentication/decryption, DB/file restore, verification and no-provider
Golden read/review/export all passed. The verdict reports these phase times;
`technical restore duration` is only a diagnostic and cannot replace RTO.
Both measured values must be present, nonnegative and no greater than the
approved targets bound by `CustodyPolicyV1`; otherwise the verdict rejects
with `RECOVERY_RPO_EXCEEDED` or `RECOVERY_RTO_EXCEEDED`. UTC source/failure
timestamps require signed clock-synchronization observations covering both
hosts and the event window; elapsed RTO uses one evidenced monotonic clock
domain or a signed cross-host clock bridge with bounded error charged against
the target. An absent target, unverifiable timestamp/order or unreliable
clock is `RECOVERY_MEASUREMENT_INVALID`, not a pass.

The initial test corpus includes at least two projects (the V1 factual and
drama products) plus an unrelated third project to catch one-project-only
inventory bugs. V1-01 fault cases include interrupted HTTP creation after
minimal `project.json`, unpublished Agent creation, DB-only legacy evidence,
delete intent before and after partial directory removal, a retired name
reused, archive import into a retired name, overwrite import stopped after
renaming the old target to `.import-backup-*` or after installing the new
tree, v5-to-v6 migration stopped between its two directory renames or before
hidden rollback cleanup, and active work starting against the deletion or
replacement boundary. Task-state cases include a queued/running/cancelling
Task without a matching non-terminal attempt, the converse, and contradictory
task/attempt terminal state; the deletion gate must classify each without
using one table as a proxy for the other. A task enqueue that passes its
migration check before deletion but commits afterward, an attempt plan that
commits after deletion intent, and a backup `PREPARING` insert racing with
deletion must all be refused or serialized by the same lifecycle admission
boundary. The exact
expected result for each case follows the approved lifecycle contract.
Fault tests cover missing/corrupt formal file, absent or
divergent master, second-project media omission, a DB-referenced global
asset omitted or missing, a DB project reference classified as live by the
approved liveness table without an admitted project directory (distinct from
an intentionally deleted project's historical row), path traversal/symlink,
concurrent visible GC query, changed file/DB state during capture, process
interruption at each state transition, nonempty/aliased target, archive digest
failure, missing/stale/forged start or closure fence evidence, missing/
tampered underlying evidence blobs, two new attempts racing on one deployment
or aliased root, new-attempt-versus-disposition registry CAS, refusal to admit
a PREPARING restore, a source-loss drill where unresolved staging blocks a
new capture but an earlier accepted set restores to a disjoint target (and
an aliased target rejects), an audited PREPARING disposition, interrupted plaintext
staging with verified cleanup, missing or tampered staging-disposition
evidence, a restored row that is missing/wrong/COMPLETE,
zero-formal-file project, out-of-root master reference, a DB credential-file
reference or implicit Vertex resolver without a signed disabled/provisioned
disposition, an omitted selector, a falsely disabled enabled route, unknown
manifest
version, missing/wrong configuration field, absent receipt, forged/rolled-back
signed receipt, wrong key and tampered ciphertext before target mutation, and
a receipt whose unsigned security field is changed, a wrong/stale ledger
sequence, missing or wrong crypto profile binding, late/forged failure event,
RPO/RTO over target or missing target, a VERIFIED set held by retention/hold,
last recoverable set, active restore lease, missing disposal evidence or
ledger-to-source disposal crash, and a synthetic media file whose size/hash
are valid but whose stream cannot
decode. A synthetic secret canary must be absent from logs/manifest while
present only inside protected test archive data. A real disposable PostgreSQL plus
filesystem drill restores to clean targets and runs no-provider Golden A/B
read/review/export. Tests at the affected scopes, migration round trip,
static gates, test audit, the D3-required frontend/website gates, and two fresh
independent reviews bind to the same clean candidate HEAD. Historical M7-D
self-review or an E1 green suite cannot substitute for this evidence. All
failure codes above are stable enum values with sanitized detail fields, not
free-form path-bearing strings or a `reason:path` encoding.

The inventory fault subset additionally covers absent versus present-empty
Artifact Manifest, profile manifest, version index and `_global_assets` root;
modified/project-only profile files and a deletion tombstone; an unknown
regular file retained byte-exactly; an unknown declared reference type rejected;
retained regular lock file versus unknown hidden-file retention; post-restore
lock acquisition; an unsupported
filesystem entry; pending versus dangling episode script; local versus
external `video_uri`; missing `video_thumbnail`, product original and
derivative sheet; two DB bindings for one global-asset file; a referenced
global-asset file missing while orphan bytes are retained; selected,
unselected and rejected-but-retained version snapshots; post-purge orphan
snapshot; same-path content drift; and file-count/size-limit rejection. Grid
cases include a pending record with no composite, a ready record whose
composite is missing, a missing split-frame or reference-image target, and
malformed grid JSON that the UI list would skip.
They also include optional presentation absence versus divergent persisted
media paths, an active checkpoint missing staged bytes, and a terminal
checkpoint after legitimate staging cleanup. Draft cases include a named
source file, a null selector with missing derived source, and a corrupt
envelope retained by the physical census. Diagnostic cases include a
`.migration_failure.json` record whose repair pointer names a rejected input,
and stale `storyboards/generation_failures.json` unit IDs; neither may be
silently promoted to media lineage or dropped from the exact physical tree.
These fixtures must exercise capture and clean-target restore through the
same inventory interface, not only a standalone path parser.

## 8. Follow-on packets and stop conditions

M7-D remains CHANGES_REQUIRED until this H6 design is approved, implemented
and verified **and** the separately scoped H7 telemetry findings are closed
under the stricter D3 plan. E1 stays unaccepted until its upstream-to-host
mapping, evidence semantics and test-tier issues are repaired on that accepted
base. E2 restore-derived browser/Golden proof and the provider-free release
policy are later packets; all paid outbound paths—not only the 11 async-video
families—must be inventoried and either demonstrably disabled or qualified.

The H6 work separates a disposable **core contract** packet (migration,
fence/manifest/verdict interfaces, complete inventory, authenticated-custody
test port, strict restore verification and fault corpus) from a
**deployment-bound custody** packet (approved repository/key/signing profile,
real policy/receipt, operator evidence, and clean-target drill). Passing the
first packet is not H6 closure or `RECOVERY_VERIFIED`; E1 remains blocked until
the second packet and the rest of M7-D have independent acceptance.

Before the inventory/manifest V1 schema or capture adapter is frozen, the
project-inventory research gate must approve an exact table of project-scoped
DB row types, their live-versus-historical predicates, deletion/tombstone or
retirement semantics, and typed handling of filesystem-only and DB-only
identities. The [bounded source table](../../research/2026-09-26-r2-m7-h6-project-liveness-table.md)
finds no current DB project-liveness registry and leaves deletion, retirement
and name reuse as explicit decisions; it is not an approved predicate. The
HTTP create route can leave a minimal `project.json` before complete metadata
is saved, so file existence alone cannot prove publication. The gate must
classify this interrupted-create state and supported historical schemas.
Archive import with `overwrite` can move an old project to a hidden sibling
and install another tree under the same name
(`server/services/project_archive.py:1956-1987`); the lifecycle contract must
also fence and reconcile this replacement route and reject import into a
retired name under any no-reuse policy. The v5-to-v6 migrator similarly swaps
the whole project through hidden staging/rollback siblings and can leave a
target-name gap on process loss
(`lib/project_migrations/v5_to_v6_asset_namespace.py:584-614`);
read-only capture must recognize and reject unresolved swap state without
running startup reclaim. The
gate must also approve the `GLOBAL_ASSET` binding identity (asset or
derivative row ID, reference field and media kind), duplicate/null references,
orphan-file policy, and absent-root behavior. This draft proposes exact
physical-file retention with multi-binding records, an absent root only when
no DB reference exists, and captured (not silently discarded) orphan bytes.
It also needs a release-versioned reference field map, bounded lock-writer
map for the fence and a post-restore lock-use test,
approved census bounds, profile/secret custody disposition, and explicit
approval of the proposed all-retained-version-history rule. Current project deletion only
removes the directory, so unconditional DB-name/directory set equality is not
the rule. Until the liveness table and these inventory decisions and tests
are approved, step 2 is a draft acceptance obligation, not an implementable
production admission rule.

The H6 implementation includes a separate revision of
`docs/r2/runbooks/m7-backup-restore.md`: replace the false secret-free claim,
document the signed fence start/closure and writer inventory, custody and
key-recovery procedures, staging sanitization and interrupted-attempt restart,
operation-registry claim/disposition, independent ledger admission/abort,
dual-authorized disposal and timing evidence, clean-target/no-egress
restore, and the inspected PREPARING/exceptional COMPLETE-to-REJECTED
dispositions with their audit evidence. The runbook now carries an interim
warning about the current secret-bearing, disposable-only mechanism; that
warning is not the future procedure. Version-1 manifest/verdict compatibility,
exact PostgreSQL image/client and decoder
pins (the current production Compose uses a floating `postgres:18-alpine`
tag), and migration downgrade tests belong to the
same packet; a documentation-only correction is not H6 acceptance.

No step here authorizes a live database migration, production backup/restore,
provider call, credential use, paid canary, deployment, release tag or
`PRODUCTION_CANDIDATE`/`PRODUCTION_APPROVED` claim.
