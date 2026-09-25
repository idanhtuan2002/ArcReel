# R2 M7-D H6: snapshot, archive crypto, and playability source check

Date: 2026-09-25

Checkout: `feat/r2-m7e-v1-lineage` at `8bdbf76b1e2d00378d026361ff8806bf7f706db2`

Status: research only. This note does not approve the draft H6 design, select a
custody product, or authorize a production backup/restore. License is out of
scope.

## Question and repository boundary

This check targets the snapshot, encrypted-archive, key-lifecycle, and local
media claims in the draft H6 closure design. Direct source reads were required:
the supplied code graph predates this worktree and does not track the current
backup implementation.

The current helper copies one project's candidate files and then runs
`pg_dump --format=custom` with no schema/table/data exclusions
(`r2/host_hardening/backup.py:289-301`). Its drift check compares only that
project's candidate count (`backup.py:303-308`), and restore verification checks
file existence, size, and SHA-256 but does not parse or decode media
(`backup.py:238-253`). The draft proposes a write fence plus complete final
drift check (`docs/superpowers/specs/2026-09-25-r2-v1-m7d-recovery-closure-design.md:330-338`), authenticated custody before mutation
(`:372-377,525-532`), and metadata probe plus whole-stream local decode
(`:543-561`).

## Primary-source findings

### 1. What `pg_dump` consistency does and does not prove

1. PostgreSQL says a `pg_dump` is internally consistent: it represents one
   database snapshot from the time the dump starts, even while the database is
   in concurrent use. That is a database property; PostgreSQL makes no claim
   that separately copied Host/media files share the snapshot.
   [PostgreSQL 18, SQL Dump](https://www.postgresql.org/docs/18/backup-dump.html)
2. The tool covers one database, not the whole cluster. Cluster-wide roles and
   tablespaces require separate treatment. With no schema selection, it dumps
   all non-system schemas; foreign-table data is not included unless explicitly
   requested, and unlogged table data is always omitted when dumping from a
   standby. The H6 production profile therefore needs an evidenced source
   topology and recovery-scope statement rather than treating “whole DB” as
   “whole PostgreSQL cluster.”
   [PostgreSQL 18, `pg_dump`](https://www.postgresql.org/docs/18/app-pgdump.html)
3. PostgreSQL exposes explicit schema/table/table-data exclusions. Because the
   current command uses none, it does not intentionally exclude ordinary
   credential-bearing application tables. Introducing exclusions would create
   a partial dump, and PostgreSQL warns that selected-schema/table dumps do not
   automatically include dependencies or guarantee a clean standalone restore.
   [PostgreSQL 18, selection and exclusion options](https://www.postgresql.org/docs/18/app-pgdump.html#APP-PGDUMP-OPTIONS)
4. Parallel `pg_dump` uses synchronized snapshots so its worker connections see
   the same data set. `--snapshot` can synchronize another database session,
   and `--serializable-deferrable` changes database-transaction semantics, but
   none synchronizes PostgreSQL with an external filesystem. The draft's
   operator fence and final DB/file drift comparison are therefore separate
   required evidence, not features supplied by `pg_dump`.
   [PostgreSQL 18, parallel dump and snapshot options](https://www.postgresql.org/docs/18/app-pgdump.html#APP-PGDUMP-OPTION-J)
5. Restoring a dump executes code selected by source superusers; partial restore
   does not remove that risk. A custom archive can be rendered for inspection
   with `pg_restore --file`, but inspection/authentication policy remains an H6
   restore-boundary decision.
   [PostgreSQL 18, `pg_dump` warning](https://www.postgresql.org/docs/18/app-pgdump.html)

### 2. Suitable authenticated encryption shape and its hard constraints

1. AES-GCM is a suitable primitive for a versioned archive profile: NIST
   defines GCM as authenticated encryption with associated data. Its security
   depends critically on never repeating an IV under the same key. NIST has
   announced a revision of SP 800-38D but, as checked here, the 2007 document is
   still the final publication; the production profile must pin the approved
   algorithm/tag/IV rules it actually implements rather than cite “AEAD” alone.
   [NIST SP 800-38D](https://csrc.nist.gov/pubs/sp/800/38/d/final)
   [NIST revision notice](https://csrc.nist.gov/news/2024/nist-to-revise-sp-80038d-gcm-and-gmac-modes)
2. The official `cryptography` API documents 128/192/256-bit AES-GCM keys, a
   recommended 96-bit IV, a 128-bit tag, authenticated associated data, and
   `InvalidTag` on altered ciphertext or wrong key/IV/AAD. It also caps the
   one-shot `AESGCM.encrypt()` input at `2^31 - 1` bytes. Therefore a whole-set
   implementation cannot assume that reading an arbitrary database/media
   archive into one `AESGCM` call is a production-safe format.
   [`cryptography` AES-GCM API](https://cryptography.io/en/latest/hazmat/primitives/aead/#cryptography.hazmat.primitives.ciphers.aead.AESGCM)
3. The lower-level `Cipher(AES, GCM)` interface supports incremental processing,
   but its official warning is decisive: decrypted bytes have no integrity
   guarantee until tag finalization succeeds. A viable candidate profile is
   envelope encryption with a fresh DEK per capture attempt, unique 96-bit IVs
   per encrypted object/invocation, full-length tags, and canonical non-secret
   set/object/profile identity as AAD. Restore must decrypt into quarantined
   staging, successfully finalize/authenticate, and only then expose plaintext
   to `pg_restore`; piping pre-finalization plaintext into `pg_restore` would
   violate the draft's authenticate-before-mutation rule.
   [`cryptography` GCM mode](https://cryptography.io/en/latest/hazmat/primitives/symmetric-encryption/#cryptography.hazmat.primitives.ciphers.modes.GCM)
4. Chunked AEAD is an alternative only after a framing profile defines chunk
   ordering, total count/length, per-chunk unique nonce construction, AAD, and a
   final manifest commitment. Independently valid chunks alone do not detect a
   truncated, reordered, or rolled-back archive. This is an inference from the
   AEAD and nonce requirements, not a pinned H6 format.

### 3. Key custody, rotation, and archive integrity

1. NIST says a symmetric data-encryption key must remain available as long as
   its ciphertext may need decryption; archived DEKs should be wrapped by an
   archive-encryption or key-wrapping key. It also requires archived-key
   confidentiality and integrity protection and defines cryptoperiods to limit
   exposure. SP 800-57 Rev. 5 remains final; Rev. 6 is currently a draft.
   [NIST SP 800-57 Part 1 Rev. 5](https://csrc.nist.gov/pubs/sp/800/57/pt1/r5/final)
   [NIST SP 800-57 Rev. 6 draft status](https://csrc.nist.gov/pubs/sp/800/57/pt1/r6/ipd)
2. Consequence for rotation: a KEK version cannot be retired or destroyed while
   any retained backup still depends on it, unless every dependent wrapped DEK
   has been durably rewrapped and restore-tested under the replacement. Deleting
   the old KEK first is data loss; merely changing the “current key” does not
   rotate old archives. This is a direct lifecycle inference from NIST's
   retention rule.
3. Consequence for compromise: rotating or rewrapping later does not undo
   disclosure of ciphertext/plaintext already exposed under a compromised key.
   The profile needs key-version inventory, compromise/revocation response,
   auditable rewrap or re-encryption, recovery copies, and periodic restores.
4. AES-GCM authenticates to holders of the symmetric DEK; it does not by itself
   establish an independent producer identity or freshness. The draft's
   separate signing trust root and accepted-version ledger are therefore not
   redundant with the GCM tag. Signing-key custody/rotation and old public-key
   retention must also preserve verification of still-retained receipts.

### 4. What local media evidence can prove

1. `ffprobe -show_format` and `-show_streams` report container and stream
   metadata; `-show_frames`/`-count_frames` can inspect frames. These outputs
   support a canonical metadata result, but a metadata-only probe is not proof
   that the selected stream decodes to end of file.
   [FFprobe documentation](https://ffmpeg.org/ffprobe.html)
2. FFmpeg documents `-xerror` as stop/exit on error, and a null muxer discards
   decoded output. Thus a bounded `ffmpeg -xerror ... -f null -` pass over the
   explicitly selected stream is suitable additional local-decode evidence.
   [FFmpeg documentation](https://ffmpeg.org/ffmpeg.html)
3. Network denial must be explicit: FFmpeg says all protocols are allowed by
   default and provides `protocol_whitelist`. The H6 probe profile must pin the
   executable/build, selected stream(s), allowed local protocols/demuxers,
   timeout/resource limits, command result, and canonical metadata/decode
   digest. Even that proves local parse/decode under that pinned build, not UI
   rendering, audio-device output, or subjective playback quality.
   [FFmpeg protocol whitelist](https://ffmpeg.org/ffmpeg-protocols.html#Protocol-Options)

## Decision-critical production blockers and bounded core work

The sources support pure contracts and adversarial fixtures for snapshot scope,
AEAD metadata/AAD, key references, tag failure, and probe/decode receipts. They
do **not** supply the deployment facts needed for production authority.

Production custody and `RECOVERY_VERIFIED` remain blocked on:

- the actual single-database/cluster topology, standby/primary source, and
  separately provisioned roles/tablespaces/foreign or unlogged data;
- a reviewed, version-pinned ciphertext/framing implementation with test
  vectors, large-object limits, nonce allocation, authenticated staging, and
  failure-safe plaintext disposal;
- the real repository, KMS/HSM boundary, DEK/KEK ownership, key backup,
  rotation/rewrap, compromise/revocation, signing-key, retention, and audit
  procedures, with named independent principals;
- pinned `pg_dump`/`pg_restore` and FFmpeg builds plus an isolated no-egress
  clean-target drill that authenticates before mutation and records full local
  decode, application/reference checks, RPO, and RTO.

No product or crypto library is selected by this note. In particular, the
repository currently has no H6 crypto implementation or pinned `cryptography`
dependency; the API documentation above establishes constraints, not an
implementation decision.
