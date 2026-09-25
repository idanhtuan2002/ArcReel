# R2 M7 H6: V1 whole-database archive custody policy research

Date: 2026-09-25

Status: research only; this note does not select a vendor, approve an
architecture, or change the existing M7-D mechanism. The companion H6 design
selects a staged core-implementation path with a hard production custody gate.

## Question and boundary

What is the smallest practicable, vendor-neutral custody policy for a V1
whole-database archive that can preserve confidentiality, detect tampering,
support an isolated restore, and leave reviewable evidence? This is about the
archive produced after the existing backup operation, not a claim that the
current local backup directory is production-ready custody.

## Current repository facts (verified at `92319182`)

- `r2/host_hardening/backup.py` writes a custom-format `pg_dump` archive and
  copies media into a caller-supplied `backup_dir`; it calculates SHA-256 for
  each media object and checks those values after a restore. It does not
  encrypt the archive, upload it, manage an encryption key, or sign a
  manifest.
- `BackupSetManifest` carries source/release/schema/configuration references
  and media digests, but has no archive-ciphertext digest, encryption-suite,
  key reference, storage-version reference, signature, retention, or custody
  evidence fields (`r2/contracts/host_hardening.py`).
- The runbook requires an operator write fence, retains the manifest next to
  `backup_dir`, and restores only to an empty database and empty media root.
  It explicitly says V1 has neither PITR nor an automated write fence
  (`docs/r2/runbooks/m7-backup-restore.md`).
- `deploy/production/docker-compose.yml` pins `postgres:18-alpine` and maps
  `./pgdata` as a host path. The production compose file and
  `deploy/production/.env.example` contain PostgreSQL/application settings but
  no KMS, object-store endpoint/bucket, archive repository, immutability,
  backup credential, or retention setting.

This is a bounded inspection of the files above plus the M7-D runbook and
backup/contracts implementation; `deploy/` and `docs/r2/runbooks/` were
outside the supplied graph coverage, and the supplied graph generation was
not current for this worktree. The absence statement is therefore limited to
those inspected paths, not the whole repository or a deployment environment.

## Primary-source findings

1. A hash is an integrity primitive, not confidentiality. NIST identifies
   hashes and digital signatures as backup-integrity mechanisms, while CP-9
   separately requires protecting backup confidentiality, integrity, and
   availability. Its CP-9(8) enhancement specifically calls for cryptographic
   protection against unauthorized disclosure *and* modification at primary
   and alternate storage locations. [NIST SP 800-53 Rev. 5, CP-9](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-53r5.pdf)

2. Authenticated encryption is suitable for the archive bytes when its
   construction's operational requirements are met. NIST defines GCM as
   authenticated encryption/decryption and says it can detect accidental and
   unauthorized modification; it also warns that an initialization-string
   uniqueness breach can nearly eliminate its assurance. Thus a plain SHA-256
   sidecar must not be treated as a substitute for encryption, and an AEAD
   design must durably enforce its nonce rule. [NIST SP 800-38D](https://nvlpubs.nist.gov/nistpubs/legacy/sp/nistspecialpublication800-38d.pdf)

3. Key protection is part of the control, not an implementation detail. NIST
   says the protection of information depends on the keys and their lifecycle,
   including secure generation, storage, distribution, use, and destruction.
   It also describes split-knowledge handling so no individual can acquire all
   key shares, and requires separately distributing such shares. [NIST SP
   800-57 Part 1 Rev. 5](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-57pt1r5.pdf)

4. Retention and disposal need affirmative control and evidence. CP-9(7)
   calls for dual authorization to delete or destroy backup information. NIST
   current media-sanitization guidance separately requires verification of
   the chosen sanitization operation and validation that its outcome is
   effective; cryptographic erase depends on the cryptographic/key-management
   pedigree and preconditions, so a delete API result alone is insufficient.
   [NIST SP 800-53 Rev. 5, CP-9(7)](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-53r5.pdf)
   [NIST SP 800-88 Rev. 2, §§3.2, 4.5](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-88r2.pdf)

5. A restore is an execution boundary, not merely a file read. PostgreSQL
   warns that restoring a dump executes arbitrary code chosen by source
   superusers. Its documentation also says `pg_dump` is generally not the
   right tool for regular production backups and that a dump omits cluster-wide
   roles/tablespaces. [PostgreSQL 18: pg_dump](https://www.postgresql.org/docs/18/app-pgdump.html)
   [PostgreSQL 18: pg_restore](https://www.postgresql.org/docs/18/app-pgrestore.html)

6. Restore assurance should be measured, not assumed. NIST CP-9 calls for
   testing backup reliability/integrity and sample restoration; CP-10 requires
   recovery to a known state within defined RTO/RPO-aligned periods. [NIST SP
   800-53 Rev. 5, CP-9 and CP-10](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-53r5.pdf)

## Candidate V1 policy for decision-owner review

This is an enforceable policy proposal, not a vendor or product selection.

### Archive construction and integrity

1. Treat the database dump, media tree, and canonical manifest as one archive
   set. Produce a canonical manifest digest and a ciphertext/object digest for
   every stored archive object.
2. Encrypt every archive object before it enters the custody repository with a
   versioned AEAD suite. A V1 implementation using AES-GCM must allocate a
   unique nonce for each `(data-encryption-key, encryption invocation)` and
   store the nonce and authenticated associated-data schema in the signed
   outer custody receipt. The inner manifest binds the approved crypto
   profile ID/digest but does not hash the later receipt.
3. Bind immutable, non-secret context as AEAD associated data: archive-set ID,
   source deployment ID, database/media object role, manifest schema version,
   and creation time. Reject a decrypt/restore if those values or any
   authentication tag fail.
4. Retain SHA-256 digests for inventory and verification, but do not call a
   matching hash proof of confidentiality, provenance, freshness, or
   rollback-resistance. A hash is valuable only when the expected value is
   independently protected.
5. Create a detached, asymmetric signature over the entire canonical custody
   receipt body, including the manifest digest and custody-object references.
   Store its public-key identity and
   verification policy outside the mutable archive repository. AEAD shows that
   a holder of the DEK did not alter ciphertext undetectably; the detached
   signature and an independently distributed verifier key establish the
   archive's expected origin. Detecting replay of an older *validly signed*
   set additionally requires an independently maintained accepted-version
   ledger or monotonic watermark; the signature alone cannot prove freshness.

### Key ownership, separation, and access

1. Generate a random data-encryption key (DEK) per encryption attempt; never write a
   plaintext DEK, database URL, or storage credential to the archive, manifest,
   application log, or Git.
2. Wrap the DEK under a versioned key-encryption key (KEK) held by a
   separately administered key-management boundary. The archive repository
   receives ciphertext and wrapped-DEK metadata only; it has no decrypt
   permission. The normal application/runtime identity has neither archive
   deletion permission nor unrestricted KEK administration.
3. Define distinct least-privilege roles: archive writer; repository retention
   administrator; restore operator; key custodian; auditor. A break-glass
   decrypt/restore requires a time-limited request, a distinct approver, and
   immutable audit evidence. Deletion or KEK destruction requires two qualified
   authorizers, consistent with CP-9(7).
4. Keep the manifest-signing private key separate from the KEK. A signing key
   proves origin; a KEK protects confidentiality. Neither role should silently
   grant the other role's authority.

### Retention, repository, and disposal

1. Before admitting V1, choose a repository that can enforce: independent
   access identities; at-rest encryption of the submitted ciphertext; immutable
   object version/retention or an equivalent append-only control; an auditable
   read/delete history; and export of a stable object/version identifier.
2. The retention schedule, legal/organizational hold status, and earliest
   destruction time must be recorded per archive set. An archive is not
   deletable until retention/hold checks pass and dual authorization is
   evidenced.
3. Disposal evidence must identify each custody object and wrapped DEK, the
   policy decision, both authorizations, operation result, and verification
   result. Do not claim cryptographic erasure solely from a delete API result;
   it is acceptable only after the selected key-management and repository
   behavior have been verified for the actual deployment.

### Isolated restore and trust bootstrap

1. Restore only into a separately provisioned, network-restricted recovery
   environment with fresh database, media root, credentials, and no production
   outbound provider credentials. It must not mount the production archive
   repository with write/delete permission.
2. Before decrypting, use a trusted bootstrap record to verify the detached
   signature, signer key identity, signer-status/revocation policy, manifest
   digest, repository object/version IDs, and retention/hold status. The
   bootstrap record is configuration-controlled and distributed independently
   of the archive repository; a repository-local copy is insufficient for
   rollback detection.
3. Before executing `pg_restore`, inspect the non-plain archive or otherwise
   establish that the trusted signed source is authorized. This complements,
   but does not weaken, PostgreSQL's warning about arbitrary source-superuser
   code.
4. Preserve the existing empty-target and path-alias protections. After restore,
   run the existing schema/media verification plus explicit application health,
   access-control, and no-production-side-effect checks; record measured RPO
   and RTO. Do not promote the restored system solely because a file digest
   matches.

### Minimum evidence artifact fields

The following fields make the policy testable without placing secrets in the
artifact:

| Group | Required fields |
| --- | --- |
| Identity | `custody_receipt_id`, `backup_set_id`, `archive_set_id`, manifest schema/version, source deployment ID, source Git SHA, image digest, PostgreSQL version, Alembic head, capture start/end UTC |
| Contents | canonical-manifest digest, database plaintext digest/size, media inventory digests/sizes/count, ciphertext digest/size for every object, repository object key and immutable version ID |
| Encryption | approved crypto-profile ID/digest, AEAD suite/version, per-object nonce/IV and tag, AAD schema/version and digest, DEK identifier (never value), KEK logical ID/version, wrapped-DEK digest/reference, encryption timestamp |
| Origin and bootstrap | detached-signature algorithm/value, signer key fingerprint/version, verifier trust-anchor ID/digest and distribution version, signer status checked-at time |
| Custody and retention | repository identity/region or equivalent location class, admission actor/identity, retention-until, hold state, write/read/delete audit-event IDs, delete authorizer identities and decision IDs |
| Restore | request/approval IDs, isolated target identity, verified object-version IDs, verifier identity/result/reason codes, archive-inspection result, schema/media/application/access/no-side-effect checks, measured RPO/RTO, operator/auditor attestation IDs |

## Inferences and options

- **Inference:** the current custom dump plus media directory and local
  manifest are a recoverability mechanism, not sufficient custody. The code's
  SHA-256 checks address object-level corruption after restore, but none of the
  inspected files protects the archive at rest, makes stored versions immutable,
  or provides an independently trusted provenance/freshness record.
- **Option A:** client-side envelope encryption (the policy above) gives the
  clearest separation between repository access and decrypt authority, at the
  cost of implementing nonce/key/signature lifecycle correctly.
- **Option B:** a repository's server-side encryption may be an additional
  storage control, but it is not alone evidence of independent decrypt
  authority, tamper provenance, or rollback protection. It must still meet the
  stated capability and evidence requirements.
- **Option C:** a split-knowledge recovery path can reduce single-person key
  custody risk, but it adds recovery-operability burden. It is a deployment
  decision, not required to begin with a separately administered KEK boundary
  and dual-authorized break-glass flow.

## Exact unresolved deployment facts (must be answered before production adapter and RECOVERY_VERIFIED)

The typed core and disposable conformance fixtures can be designed and
implemented against the V1 custody contract without treating the values below
as known. A production custody adapter, live backup/restore, and
`RECOVERY_VERIFIED` remain blocked until these facts are evidenced. This
distinguishes contract implementation from operational acceptance; it is not
permission to call the current unencrypted local backup production-ready.

1. Which actual custody repository is approved, its account/tenant and region,
   and whether it can enforce immutable object version/retention, legal holds,
   audit export, and a separately authorized delete path.
2. Which actual key-management boundary is approved; whether KEKs can be
   non-exportable, versioned, disabled/revoked, audited, and authorized
   separately from archive storage; who owns each administrative role; and
   which reviewed ciphertext format/implementation and test vectors are
   pinned as `CustodyCryptoProfileV1`. A generic “AEAD” label is not an
   implementation profile.
3. Which identities will write, read for restore, delete, administer retention,
   administer keys, sign manifests, and audit evidence; whether one human or
   workload identity can combine prohibited permissions; and the approved
   break-glass path.
4. The retention, hold, recovery-point, recovery-time, archive cadence, and
   evidence-retention values. The current runbook supplies no production values.
5. The production database topology and complete recovery scope: single database
   versus cluster-wide roles/tablespaces, media location, secrets/provisioning,
   and whether `pg_dump` remains acceptable despite PostgreSQL's regular-
   production-backup warning.
6. The isolation boundary for a recovery environment, including network egress,
   production credential denial, data-classification/privacy obligations, and
   the approver who may authorize a restore drill or an actual recovery.
7. The trust-anchor distribution/revocation process and the signing-key custody
   service. Without it, a detached signature cannot provide an independently
   bootstrapped provenance decision.

## Primary source list

- [NIST SP 800-38D: Galois/Counter Mode](https://nvlpubs.nist.gov/nistpubs/legacy/sp/nistspecialpublication800-38d.pdf)
- [NIST SP 800-53 Rev. 5: Security and Privacy Controls](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-53r5.pdf)
- [NIST SP 800-57 Part 1 Rev. 5: Recommendation for Key Management](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-57pt1r5.pdf)
- [NIST SP 800-88 Rev. 2: Guidelines for Media Sanitization](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-88r2.pdf)
- [RFC 8032: EdDSA/Ed25519 signatures](https://www.rfc-editor.org/rfc/rfc8032)
- [PostgreSQL 18: pg_dump](https://www.postgresql.org/docs/18/app-pgdump.html)
- [PostgreSQL 18: pg_restore](https://www.postgresql.org/docs/18/app-pgrestore.html)
