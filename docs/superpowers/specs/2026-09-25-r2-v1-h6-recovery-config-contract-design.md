# R2 V1 H6 recovery configuration wire contract

Status: **implementation candidate**, not sponsor acceptance or production
backup authority. This is the first independently reviewable core packet under
the [H6 closure design](2026-09-25-r2-v1-m7d-recovery-closure-design.md).
It does not change the disposable `BackupSetManifest` or
`create_backup_set()` interface, migrate persistence, choose a custody
product, or authorize capture/restore.

## Decision and alternatives

The legacy backup takes an arbitrary `configuration: dict` and hashes it.
That cannot establish which source/release/tool/route configuration was
captured. V1 gets a separate, exact, canonical `RecoveryConfigV1` record.
Extending the unversioned drill manifest in place would silently change its
callers; migrating the database first would couple persistence to an undefined
digest. A separate pure contract lets us verify the fingerprint before either
operation is wired to it. The production entrypoint must later require an
independently approved expected digest; a caller cannot approve its own
configuration by supplying both sides of the comparison.
The `pg_dump`/`pg_restore` fields make this explicitly a logical-dump profile;
the wire discriminator is `backup_mechanism="logical_pg_dump_v1"`. Physical
backup or PITR requires a new reviewed profile/schema, not reinterpretation
of V1 fields. This choice follows the
[pinned donor comparison](../../research/2026-09-25-r2-m7-h6-backup-donor-contract-reuse.md).

## Wire format and digest domain

The UTF-8 JSON record is at most 1,048,576 bytes. It has no duplicate keys,
non-finite numbers, unknown fields or alternate whitespace/key order: bytes
must equal `r2.contracts.fingerprints.canonical_json_bytes(decoded)`. Schema
version is JSON integer `1`, never boolean, float or string. All fields below
are required; there are no defaults. Logical IDs match
`^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$`; they are not paths, URLs,
credentials or mount names. Tool-version strings are 1–256 printable
characters with no leading/trailing whitespace. SHA-256 values use lowercase
`sha256:` plus 64 hexadecimal digits. Rejection is `RecoveryConfigInvalid`
with a safe category, never the submitted value.

`configuration_digest` is `sha256:` plus SHA-256 of the **entire validated
canonical record bytes**, including `schema_version` and every nested item.
It is not a digest of a caller-chosen subset or of normalized output after
parsing. The record contains no secret value, DSN, absolute mount path, raw
Compose environment variable or signing key. This schema restriction alone
does not prove a caller supplied truthful tool/configuration identities; the
later operator capture adapter must collect and attest them.

| Required field | Wire type and meaning |
| --- | --- |
| `schema_version` | integer `1` |
| `backup_mechanism` | exact string `logical_pg_dump_v1`; no physical/PITR interpretation |
| `source_deployment_id` | exact logical source identity |
| `release_git_sha` | lowercase 40-hex commit ID |
| `release_image_digest` | SHA-256 container image digest |
| `postgres_server_image_digest` | SHA-256 PostgreSQL server image digest |
| `pg_dump`, `pg_restore`, `ffprobe`, `ffmpeg` | `ToolIdentityV1` each: exact nonempty `version` and SHA-256 `binary_digest` |
| `db_root_id`, `project_root_id`, `media_root_id` | three distinct logical root IDs; physical target paths may later be remapped |
| `service_inventory` | nonempty sorted `ServiceIdentityV1` list defined below |
| `writer_inventory_digest` | SHA-256 of the canonical sorted `(kind, instance_id)` pairs for app, worker, recovery scanner and GC writers; exactly the domain consumed by the existing fence verifier |
| `effective_compose_digest` | digest of the protected, non-secret normalized effective production Compose projection |
| `network_egress_policy_digest` | digest of the approved source egress-policy projection |
| `provider_route_policy_digest` | digest of the approved route-enablement projection |
| `paid_routes_enabled` | JSON `false` in V1; `true` is unsupported |
| `capability_registry_digest` | SHA-256 of the release-bundled Host registry |
| `agent_runtime_profile_digest` | SHA-256 of the release-bundled agent-runtime profile |

The projection algorithms and actual collection/attestation for the Compose,
egress, route, registry, tool, and service identities are a dependency of the
later capture adapter packet. A syntactically valid digest here is only a
declaration; this parser cannot establish that it describes a running system.
Do not admit production capture until those projections are frozen and
independently checked against the deployment.

`ServiceIdentityV1` has exact `service_id`, `kind` (`postgres`, `app`,
`worker`, `recovery_scanner`, `gc_cleanup`, or `other`), image SHA-256
`image_digest`, strict boolean `can_write`, and a nonempty sorted unique
`instance_ids` tuple. The full list is sorted by `(service_id, kind)` and
must not repeat either a service ID or `(kind, instance_id)` pair. Exactly
one `postgres` item and at least one writer item for each of `app`, `worker`,
`recovery_scanner`, and `gc_cleanup` are required. Those four kinds must
have `can_write=true`; `postgres` must also have `can_write=true`. Extra
nonwriters may be present but cannot use one of the four writer kinds.
The digest excludes `postgres`, whose DB-session proof is a separate item
in `CaptureFenceEvidenceV1`.

For example, the exact writer-digest input for one instance of each kind is
`[["app","app-1"],["gc_cleanup","gc-1"],["recovery_scanner","scan-1"],["worker","worker-1"]]`.
Its digest is
`sha256:b57fb25e3a2aa2b588f820b8e34a81366cfeda8c58eb4d2bcfad6dac282927e4`.
This is sorted by the pair, not by Compose declaration order. A source fence
record with a different writer digest cannot admit capture. The fence
`file_root_ids` order is `(project_root_id, media_root_id)`.

## Comparison and rollout

The capture code later compares `configuration_digest` against a release-
approved, independently supplied `RecoveryConfigV1` digest before any backup
row/file write. Restore later compares the manifest's bound digest against
the independently supplied source/release policy **before target mutation**;
it may use different physical empty target paths but not a different release,
route policy, tool profile or logical source identity. A missing record,
unknown version or mechanism, unsorted/duplicate service inventory, changed digest field,
`paid_routes_enabled=true`, or caller-supplied `database_url` field is a
typed `BACKUP_CONFIGURATION_MISMATCH`, not a warning.

This packet implements parsing and fingerprinting only. The inner manifest,
inventory, verdict, migration, capture orchestration, crypto profile and
deployment custody are separate dependent packets. No field in this record
is by itself evidence that the encrypted archive exists or is authentic.

## Verification focus

Tests must pin canonical byte parsing, full-record digest sensitivity,
missing/unknown/secret-bearing fields, strict version/boolean/digest forms,
root aliasing, sorted/unique service instances, complete writer kinds, and
the exact fence-writer digest domain. The disposable H6 backup and fence
contract tests must remain unchanged and green. A source-only unit fixture
cannot count as production configuration evidence.
