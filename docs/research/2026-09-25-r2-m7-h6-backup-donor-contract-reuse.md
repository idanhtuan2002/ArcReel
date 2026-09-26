# R2 M7 H6: backup donor and core-contract reuse check

Date: 2026-09-25

Checkout: `feat/r2-m7e-v1-lineage` at
`ca52d6aeea9416238e54b77da1018fb1e913567a`

Status: research only. This note does not select a backup/storage product,
approve the H6 design, or authorize a backup, restore, migration, or release.

## Question and method

Which concrete backup patterns already available to this project are reusable
for H6 V1, how do logical `pg_dump` and physical/PITR differ, and is the staged
core-contract-first packet technically sound?

The supplied graph is the stale `home-anhtuan-content-production-os-m7`
generation `2026-09-18T10:57:40Z`. It reports the current backup implementation
as `not_tracked`, `backup_fence.py` as missing, and the legacy contract as
metadata-changed. Direct reads were therefore used for every H6 and donor claim.
The graph still confirms 21 direct callers of
`r2.contracts.fingerprints.canonical_json_bytes`; current source and tests were
read afterward. The two donor checkouts below were inspected at exact commits,
and their cited tracked files have no local diff.

## Bottom line

**A pure core-contract packet is sound for V1.** It can
freeze strict configuration/manifest/evidence identities, canonical digest
domains, stable object-version references, and adversarial parsing before a DB
migration or effectful backup adapter exists. It is not sound if “core” embeds
`pg_dump` as permanent production policy, treats a local test key or hash as
custody, or emits `RECOVERY_VERIFIED` without an authenticated clean-target
restore.

The live candidate `RecoveryConfigV1` explicitly names `pg_dump` and
`pg_restore`, so this packet is **logical-dump V1**, not mechanism-neutral. That
is coherent with the draft's explicit V1 deferral of PITR, provided the frozen
wire identity makes the logical capture profile unambiguous and a future
physical/PITR profile requires a new reviewed schema/profile rather than
silently repurposing those fields.

The actual donors reinforce that split. The pinned ArcReel host offers a small
write-fenced logical snapshot pattern; the available PIOS checkout offers a
substantially larger physical/WAL/PITR operational pattern. Neither donor
provides H6's database-plus-external-media authority or encrypted immutable
custody as-is. The first V1 code should therefore reuse ArcReel's strict local
contract primitives and keep the database mechanism behind a later typed
profile/adapter boundary.

## Actual donor patterns

### 1. Pinned ArcReel `v0.29.0`: stopped-writer logical snapshot

The pinned host checkout is `/home/anhtuan/content-os-r1-8/work/ArcReel` at
`6ddedc775e7fe5f398b10081ab741985f7dceda7` (`v0.29.0`). Its PostgreSQL runbook
stops ArcReel while PostgreSQL stays up, creates a plain `pg_dump`, archives
`.env`, Compose, projects and runtime directories under the same timestamp,
then restores into a rebuilt empty database and checks health plus selected
projects/media. Exact source:
[`website/docs/ops/deployment.md:345-408`](https://github.com/ArcReel/ArcReel/blob/6ddedc775e7fe5f398b10081ab741985f7dceda7/website/docs/ops/deployment.md#L345-L408).

Reusable pattern: stop application writers, pair DB and file artifacts under
one recovery identity, restore into an empty target, and perform application
checks. Non-reusable as H6 authority: the shared timestamp is not an atomic
cross-store snapshot; the files are not content-inventoried, authenticated,
encrypted, version-locked, or tied to measured RPO/RTO evidence; it is not PITR.

### 2. Available PIOS `fbf9e81a`: physical backup plus continuous WAL

The available checkout `/home/anhtuan/PIOS` is at
`fbf9e81a20ddb06ce475f5a52169a3ccd0efe43a`. It builds PostgreSQL 16 with
pgBackRest, enables `archive_mode`, `archive-push`, and a 120-second
`archive_timeout`, and stores a pgBackRest repository in a local Docker volume
([`infra/postgres/Dockerfile:1-14`](https://github.com/idanhtuan2002/pios_v2/blob/fbf9e81a20ddb06ce475f5a52169a3ccd0efe43a/infra/postgres/Dockerfile#L1-L14),
[`infra/docker-compose.yml:21-50`](https://github.com/idanhtuan2002/pios_v2/blob/fbf9e81a20ddb06ce475f5a52169a3ccd0efe43a/infra/docker-compose.yml#L21-L50),
[`infra/postgres/pgbackrest.conf:5-24`](https://github.com/idanhtuan2002/pios_v2/blob/fbf9e81a20ddb06ce475f5a52169a3ccd0efe43a/infra/postgres/pgbackrest.conf#L5-L24)).

Its narrow adapter exposes `info()` and `backup(full|diff|incr)`; orchestration
records the pgBackRest label, type, size, timeline, LSN range, backup WAL range,
repository WAL horizon and tool-reported version
([`infra/backup/pgbackrest_backend.py:16-87`](https://github.com/idanhtuan2002/pios_v2/blob/fbf9e81a20ddb06ce475f5a52169a3ccd0efe43a/infra/backup/pgbackrest_backend.py#L16-L87),
[`infra/backup/backup_job.py:44-142`](https://github.com/idanhtuan2002/pios_v2/blob/fbf9e81a20ddb06ce475f5a52169a3ccd0efe43a/infra/backup/backup_job.py#L44-L142)). The restore drill mounts the repository read-only into a fresh empty PGDATA
volume, restores with the source image, measures RTO, records image/config
digests, and compares pre-backup/restored/live lower-bound row counts
([`infra/scripts/restore_drill.py:297-392`](https://github.com/idanhtuan2002/pios_v2/blob/fbf9e81a20ddb06ce475f5a52169a3ccd0efe43a/infra/scripts/restore_drill.py#L297-L392),
[`infra/scripts/restore_drill.py:395-473`](https://github.com/idanhtuan2002/pios_v2/blob/fbf9e81a20ddb06ce475f5a52169a3ccd0efe43a/infra/scripts/restore_drill.py#L395-L473)). Its tests provide reusable fixtures for a fake backend, backup identity/LSN/WAL evidence, bounded failure classes, and a static guard preventing default tests from dispatching production backup effects
([`tests/integration/test_backup_job.py:12-92`](https://github.com/idanhtuan2002/pios_v2/blob/fbf9e81a20ddb06ce475f5a52169a3ccd0efe43a/tests/integration/test_backup_job.py#L12-L92),
[`tests/unit/test_restore_drill_evidence.py:23-93`](https://github.com/idanhtuan2002/pios_v2/blob/fbf9e81a20ddb06ce475f5a52169a3ccd0efe43a/tests/unit/test_restore_drill_evidence.py#L23-L93),
[`tests/contract/test_backup_test_isolation.py:94-148`](https://github.com/idanhtuan2002/pios_v2/blob/fbf9e81a20ddb06ce475f5a52169a3ccd0efe43a/tests/contract/test_backup_test_isolation.py#L94-L148)).

Reusable pattern: an effect port; exact backup/LSN/WAL identity; a clean physical
restore using a read-only repository; measured evidence; fake-backend isolation;
and a static no-production-effect test guard. Non-reusable as H6 implementation:
it covers a PostgreSQL cluster, not ArcReel's external project/formal/media
roots; its repository is a mutable local volume; its config has no repository
cipher setting; and the Dockerfile installs pgBackRest without pinning a tool
version. These are bounded source observations, not a judgment about a live PIOS
deployment.

## Official logical-versus-physical boundary

PostgreSQL 18 says `pg_dump` makes a consistent export of one database, but is
generally not the right choice for regular production backups except in simple
cases; it excludes cluster-global roles/tablespaces and restoring can execute
source-superuser-selected code. [PostgreSQL 18 `pg_dump`](https://www.postgresql.org/docs/18/app-pgdump.html)

By contrast, `pg_basebackup` takes a full or incremental physical backup of the
entire cluster and can seed PITR, while continuous recovery requires a base
backup plus a continuous archived WAL sequence. Logical dumps do not contain
the information required for WAL replay. Neither mechanism defines an atomic
snapshot with ArcReel's independent media filesystem.
[PostgreSQL 18 `pg_basebackup`](https://www.postgresql.org/docs/18/app-pgbasebackup.html)
[PostgreSQL 18 continuous archiving/PITR](https://www.postgresql.org/docs/18/continuous-archiving.html)

`pg_verifybackup` validates a physical backup manifest, files/checksums and
required WAL to a bounded extent, but PostgreSQL explicitly says that it cannot
perform every check a server will perform and that test restores plus data
checks are still required. This supports a V1 contract that always represents
verification and restore evidence separately from artifact existence.
[PostgreSQL 18 `pg_verifybackup`](https://www.postgresql.org/docs/18/app-pgverifybackup.html)

**Inference:** retaining the current write-fenced logical dump for the first
disposable contract/drill can be coherent when V1's agreed RPO/RTO and topology
allow it. Choosing physical/PITR changes cluster scope, WAL continuity,
retention, restore targeting and tool/version evidence; it should be a later
profile decision, not silently substituted behind the same wire record.
Because the candidate schema names only `pg_dump`/`pg_restore`, an explicit
logical-profile discriminator (or an equally unambiguous schema identity) is a
design check before freeze. Physical/PITR still needs the same external-media
inventory and application-level recovery mapping.

## Encrypted repository and immutable-storage boundary

The official pgBackRest configuration reference says repository encryption is
client-side, supports `aes-256-cbc`, and defaults to `none`; it separately
documents repository retention. It also notes that versioned S3/GCS/Azure
storage is generally not enabled by default and recommends considering object
locking/soft delete. These are capabilities, not proof that the PIOS donor or
H6 deployment enables them. [pgBackRest configuration reference](https://pgbackrest.org/configuration.html#section-repository)

As one primary-source example of immutable object semantics, S3 Object Lock
applies retention to individual object versions; compliance mode prevents
overwrite/deletion during retention, while governance mode permits explicit
bypass by a specially authorized principal. A legal hold remains until an
authorized removal. Those semantics are distinct from encryption,
authentication, freshness and restore correctness.
[Amazon S3 Object Lock](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html)

**Inference:** H6 core contracts may safely require opaque `repository_id`,
stable `object_ref`/`object_version`, ciphertext size/digest, crypto-profile
ID/digest, retention/hold state and audit references without selecting a
repository. A later adapter must prove those fields against the actual service.
pgBackRest's repository cipher is not interchangeable by assertion with H6's
draft authenticated-encryption/signature/anti-rollback profile; the exact
format, keys, test vectors and storage enforcement remain deployment-bound.

## Canonical primitives and fixtures to reuse

| Existing source | Reuse in H6 V1 | Constraint |
| --- | --- | --- |
| `r2/contracts/fingerprints.py:12-24` | `ensure_json_value` plus sorted, compact UTF-8 canonical bytes; SHA-256 over an explicit whole-record domain | Use this strict R2 function, not a third serializer. `lib/content_digest.canonical_json_bytes` defaults to allowing non-finite values and should not define new authority bytes. |
| `r2/contracts/backup_fence.py:23-79,134-196` | Frozen/extra-forbid models; exact identity, lowercase SHA-256 and integer-v1 validators; duplicate-key, non-finite, size/depth/node and noncanonical-byte rejection | The parser is generic enough to reuse, but its public exception category must remain sanitized. |
| `tests/unit/r2/contracts/test_backup_fence.py:18-201` | Canonical positive record plus adversarial duplicate key, whitespace, schema coercion, unknown field, timestamp, identity, size/depth and secret-redaction cases | Derive a dedicated H6 fixture; do not make production code depend on a test helper. |
| `r2/host_hardening/fence_evidence.py:42-75,91-225` | Independent expectation, exact versioned evidence-reader port, signer port, semantic inspector, writer digest, bounded reads and fail-closed port handling | Preserve separation between self-declared record data and independently supplied expectation/trust. |
| `tests/unit/r2/host_hardening/test_fence_evidence.py:31-180,567-680` | In-memory reader/signature/semantic fixtures; contradictory-but-hash-valid evidence; missing/tampered/final-version and signer/custodian corruption cases | These are disposable conformance fixtures only. |
| `tests/integration/r2/host_hardening/test_backup_integration.py:203-692` and `test_backup_restore_drill.py:123-296` | Empty-target real-PostgreSQL setup, source destruction, media corruption/path/alias cases, restore timing and real repository reads | Expand to deployment-wide project/formal/master/media inventory and actual decode; current one-project fixture is not closure. |

The generic `R2ContractModel` in `r2/contracts/common.py:14-20` is not frozen;
authority evidence should follow the stricter fence model rather than inherit
mutability accidentally. There are currently two canonical JSON helpers with
different default treatment of non-finite numbers. **Inference:** standardizing
H6 authority bytes on the strict R2 helper and pinning golden byte vectors is
safer than adding another helper. If a non-Python signer/verifier becomes part
of the later custody profile, cross-language canonical-byte vectors remain a
required interoperability check.

## Unknowns before any effectful adapter

- The actual production PostgreSQL topology, cluster-global recovery needs,
  approved RPO/RTO and whether logical dump remains adequate.
- The actual repository, immutable-version/retention/hold enforcement, key and
  signer boundaries, audit export, and independently trusted anti-rollback
  ledger.
- A pinned backup tool/image/configuration profile and measured dataset/media
  throughput; the PIOS checkout demonstrates the shape but does not pin the
  installed pgBackRest package version in its Dockerfile.
- The exact mapping between a DB logical/physical recovery target and every
  external ArcReel project/formal/master/candidate version.
- Cross-language canonicalization requirements for any future external
  custody signer/verifier.

These unknowns block a production adapter and recovery verdict, but do not
block a pure V1 configuration/manifest/evidence schema with adversarial fixtures
and no side effects.
