# R2 V1 P0 — M7-D H6 recovery closure design

Status: **DRAFT FOR SPONSOR REVIEW**. This document refines H6 implementation
within accepted ADR-0078; it is not M7-D acceptance, an implementation plan,
or authorization to operate a live backup or restore.

Candidate lineage: `feat/r2-m7e-v1-lineage` at
`4ad51b7778a8dbf7430767827106b77515e47221` before this draft.
Research basis: [2026-09-25 M7 primary-source notes](../../research/2026-09-25-r2-m7-h6-h8-primary-source-notes.md).

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
   [PostgreSQL continuous archiving](https://www.postgresql.org/docs/current/continuous-archiving.html)
   and ADR-0078:72-79.

## 4. BackupSet module and persistence interface

The external seam remains one backup module with three operations:
`create_backup_set`, `restore_backup_set`, and
`verify_restored_backup_set`. Callers supply explicit source/target DB and
file roots, deployment and release identity, and operator fence/custody
evidence; the module owns the ordering, inventory, digest, safe-path and
failure-state logic. It returns a versioned, canonical manifest/verdict. A
caller cannot supply an arbitrary project subset for a whole-DB dump.

The forward migration adds an explicit `scope_kind` (`PROJECT_LEGACY` or
`DEPLOYMENT`) and nullable `source_deployment_id` to `backup_sets`. Its ORM
model stops inheriting the non-null `UserOwnedMixin`: it retains an explicit
nullable user FK and project name for legacy rows, and permits both to be null
only for `DEPLOYMENT`, with a database check constraint enforcing the two
shapes. Existing rows migrate to
`PROJECT_LEGACY` without deletion or reinterpretation. New H6 writes use only
`DEPLOYMENT`, a non-empty deployment ID, and one global `backup_set_id`.
`backup_set_media_refs` retains its existing globally unique candidate FK.
The retention lookup keys on `candidate_id` plus an incomplete state and does
not filter by backup-set project, since candidate IDs are globally unique;
legacy and deployment rows both continue to protect referenced candidates.
The candidate deletion interface still verifies the caller's user/project
scope before using this global reference check. Migration tests cover both
row shapes and upgrade/downgrade safety on disposable PostgreSQL.

The manifest revision records the exact database archive digest/size and a
sorted complete inventory with each entry's root kind (project/formal or
candidate-media), relative path, byte size, SHA-256 and, where authoritative,
project, artifact, candidate/object version. It binds source deployment,
release Git/image, PostgreSQL/Alembic and configuration digest. It stores no
DB connection string, plaintext credential, encryption key or absolute path.
An empty required inventory is a typed failure, not a successful backup.

## 5. Capture protocol and crash behavior

1. The operator stops the app, worker, recovery scanner and cleanup writers;
   records the exact deployment/process and storage roots; and confirms all
   writes are quiescent. This is an operational precondition, not something a
   candidate-row count can prove. The H6 module rejects missing fence evidence
   but does not claim it physically stopped an external process.
2. Read all candidate/master/project identities and project-file references
   from the fenced source. Refuse missing owners, divergent master projections,
   paths outside approved roots, symlinks/junctions, duplicate refs with
   unequal bytes, or mutable/unversioned media that cannot be pinned.
3. In a short DB transaction insert one `DEPLOYMENT` PREPARING set and all
   candidate retention refs, then **commit before copying any bytes**. A
   separate transaction must be able to observe the refs. A crash leaves a
   visible PREPARING set that blocks GC until an explicit inspected rejection
   or recovery; there is no silent cleanup.
4. Copy the complete project/formal-file and candidate-media inventory into a
   private, explicit destination. Hash source and destination. Run a
   whole-database custom-format `pg_dump` while the same write fence holds,
   then hash the archive. Re-enumerate the DB and file identities and reject
   any drift. This is defense in depth, not a claim that two independent stores
   acquired a shared transaction snapshot.
5. Canonicalize and seal the manifest only after every source/destination and
   archive check passes. Then transition the *source* backup row to COMPLETE.
   Failed or interrupted sets remain PREPARING or become REJECTED only through
   an explicit inspected state transition. The DB archive may contain the
   PREPARING row because it was taken before the source COMPLETE transition;
   restore verification must recognize that exact captured state rather than
   invent a completed backup row inside the snapshot.

The manifest and archive are integrity checked before restore; digest equality
alone does not authenticate an untrusted archive. Operators may restore only
from a trusted, access-controlled set. PostgreSQL warns that restoring a dump
can execute source-selected code
([`pg_dump` warning](https://www.postgresql.org/docs/current/app-pgdump.html)).

## 6. Credential custody and restore fence

The DB archive is **secret-bearing**. V1 does not use a partial-table dump to
pretend otherwise: `provider_config` can mix secret and nonsecret rows, and
excluding only a few whole tables would make the recovery result ambiguous.
The runbook must remove its incorrect secret-free claim and require an
operator-approved encrypted, access-controlled backup destination, separate
key custody and retention, and a disposable restore environment with no
outbound provider access. The module never prints a DSN/password in argv,
manifests, errors or logs; libpq authentication uses a protected password file
or equivalent verified secret channel, not a password-bearing command
argument. [PostgreSQL libpq password-file rules](https://www.postgresql.org/docs/current/libpq-pgpass.html)
apply. Choosing the actual key manager/storage product and authorizing a live
backup remain operator decisions; absent their evidence, no production
backup/restore or `RECOVERY_VERIFIED` claim is permitted.

Restore first validates manifest schema, identity, complete digests and all
relative paths—including symlink traversal—*before any target mutation*.
Both target DB and project/media roots must be empty and isolated. It restores
the DB and files, then keeps app, worker, provider egress and cleanup disabled
until verification passes. Missing files, wrong release/schema/config,
credential-custody evidence, or any reader/probe failure reject the set;
there is no partial-success verdict or automatic activation.

## 7. Verification interface and acceptance evidence

Verification enumerates all restored projects, manifest entries, formal-file
bindings, candidate objects and approved master heads from the restored DB
and project files. It compares each against the sealed inventory, resolves
each head through `DatabaseMasterResolver` with its legacy projection where
applicable, reads each referenced file through the Host's guarded artifact
adapter, checks size/hash and probes actual media playability. It rejects
unlisted authoritative references as well as listed-but-missing files.
Only after complete closure does a restored set reach VERIFIED; the verdict
reports checked project, formal-file, candidate, master and media counts,
typed reason codes, measured recovery point/RPO/RTO and exact release identity.

The initial test corpus includes at least two projects (the V1 factual and
drama products) plus an unrelated third project to catch one-project-only
inventory bugs. Fault tests cover missing/corrupt formal file, absent or
divergent master, second-project media omission, path traversal/symlink,
concurrent visible GC query, changed file/DB state during capture, process
interruption at each state transition, nonempty/aliased target, archive digest
failure, and a synthetic secret canary absent from logs/manifest while present
only inside protected test archive data. A real disposable PostgreSQL plus
filesystem drill restores to clean targets and runs no-provider Golden A/B
read/review/export. Tests at the affected scopes, migration round trip,
static gates, test audit, the D3-required frontend/website gates, and two fresh
independent reviews bind to the same clean candidate HEAD. Historical M7-D
self-review or an E1 green suite cannot substitute for this evidence.

## 8. Follow-on packets and stop conditions

M7-D remains CHANGES_REQUIRED until this H6 design is approved, implemented
and verified **and** the separately scoped H7 telemetry findings are closed
under the stricter D3 plan. E1 stays unaccepted until its upstream-to-host
mapping, evidence semantics and test-tier issues are repaired on that accepted
base. E2 restore-derived browser/Golden proof and the provider-free release
policy are later packets; all paid outbound paths—not only the 11 async-video
families—must be inventoried and either demonstrably disabled or qualified.

No step here authorizes a live database migration, production backup/restore,
provider call, credential use, paid canary, deployment, release tag or
`PRODUCTION_CANDIDATE`/`PRODUCTION_APPROVED` claim.
