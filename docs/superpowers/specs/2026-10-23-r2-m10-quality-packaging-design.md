# M10 V2 — Quality Evidence and Product Packaging

Status: **HELD — RESEARCH AUDIT REQUIRED**, not a schema freeze or implementation release.
Authoring base: `28b93411dc908a4616093ee4b8c9276cfeb75e19`.
Product base: `r2-v2.0.5`, `4bd70525dc2a4e5a0e05c57381a90a35301ec169`.

The user explicitly requires review of all related research, decisions and donors
before further design/implementation. Cross-worktree inspection recovered the
existing M10 research, ADR-0082, specification and two plans at original commit
`50f1e9b41b570ae08a4c242fc8905e8eaeb1fbb6`. They are absent from this release
tree and remain proposed, but contain substantial prior review remediation.
This exploratory draft must not replace them or be used as an implementation
basis. Its package-first scope, assessment completeness, waiver bound, authority
and bootstrap proposals need disposition against that corpus before revision.

## 1. Intent and scope

Give an operator a repeatable way to assess an already approved V2 final,
record a human quality decision and obtain a verified package of the exact
video, metadata, captions and thumbnail reviewed. Export produces a local
downloadable artifact. It does not authorize uploading or claim delivery.

The first packet supports the existing Western explainer final, with local
technical probes and human semantic assessment. Platform-specific Short and
`zh-shuang` profiles require their own corpus and qualification. There is no
universal creative score or auto-approval threshold.

User instruction: preserve and pause M9; proceed with M10 on released V2.
M9 remains paused, unmerged and unaccepted. M10 consumes existing approved-master
and candidate infrastructure, not unfinished M9 source acquisition or Greenlight.

The implementation release must contain an explicit, bounded sequencing
amendment to ADR-0080 and its architecture acceptance contract: permit this
export-only M10 packet on the pinned V2 release while M9 is paused. It must
retain all authority/quality/review gates and prohibit consuming planned M9
behavior. This draft proposes that amendment; it does not claim it accepted.
If the amendment is not accepted, research/design remain valid and code release
stops with `POST_M8_PREREQUISITE_NOT_ACCEPTED`.

## 2. Evidence and proposed approach

Sources: [start](../../research/2026-10-23-r2-m10-v2-start.md),
[inventory](../../research/2026-10-23-r2-m10-v2-reuse-inventory.md),
[current seam research](../../research/2026-10-23-r2-m10-v2-quality-packaging-seams.md),
[ADR-0080](../../adr/0080-post-m8-north-star-closed-loop.md).

Recommended approach: extend the shared M8 revision kernel with a typed
PackagingCandidate while introducing a separate M10 packaging selection.
Reuse verified media snapshots, host authentication, canonical bytes and
command receipts. M10 selection never invokes `HostSlotAuthority.promote()`
or `MasterAuthorityUnit` writers.

Alternatives considered:

- A standalone package-revision store avoids shared-contract edits, but
  duplicates existing revision/CAS/replay mechanics and contradicts ADR-0080's
  shared-kernel direction. Reserve it for a separately accepted redesign.
- Extending the existing artifact promotion path directly would change an
  ApprovedMaster and its M7 receipt. A package selection has different authority
  and cannot be implemented as that operation with a different label.

All new choices below are author proposals pending acceptance, not prior user
decisions. No provider or new dependency is selected.

## 3. Authority and identity

| Object | Owner and invariants |
| --- | --- |
| ApprovedMaster | Existing Gate C/M7 authority; M10 reads and verifies only |
| QualityProfile | Human-authored immutable policy version, exact digest and cohort |
| QualityRun | Append-only observations; probe/assessor output grants no authority |
| QualityDisposition | Server-recorded human PASS, REWORK or WAIVE over exact evidence |
| PackagingCandidate | Immutable metadata/member plan in shared candidate revisions |
| PackagingSelection | M10 authority, CAS on a separate PACKAGING_SLOT head |
| ExportBundle | Verified immutable local bytes and receipt for one selection |
| PublishApproval | Existing Gate D/M11 scope; a package receipt cannot synthesize it |

All identities include user/project scope. The server resolves scope and issuer
from CurrentUser and project access. A request cannot supply its authority role,
forge another issuer or replace the resolved master binding. Probe processes
have no disposition or selection interface and receive no credentials.

Use the existing GateAuthorization custody pattern for human decisions. This
requires a deliberate operator action; an automatically issued model assessment
is not a human decision. Separate authority means separate operation/permissions,
not a new requirement for two different human operators.

Canonical hashing reuses the host canonical JSON implementation. New M10
objects use distinct domain names and schema version 1; the product remains
V2. Existing M8 serialized bodies and digest vectors remain unchanged.
Readers recompute immutable bodies and compare identity columns/digests.

## 4. Immutable contracts

### QualityProfile

Fields: profile ID/version, schema version, cohort, locale, artifact class,
technical rules, ordered required assessor specifications, semantic rubric,
waivable finding codes, maximum disposition age, source references, author and
creation time. Rules specify units and rational/decimal representation; no
NaN, implicit rounding, platform-name defaults or unversioned magic thresholds.

An append-only profile head determines the effective version. A replacement
version requires new runs and decisions for current readiness; it never rewrites
historical evidence. The initial explainer profile is local export policy,
not a claim about current YouTube/TikTok limits.

### PackagingCandidate and assessed subject

The immutable payload contains the exact approved-master key/version/candidate/
digest and approval identity, cohort/profile reference, title/description/tags,
ordered chapters, member roles, MIME types, stable relative paths, sizes and
byte digests for video/captions/thumbnail. Required optional assets are explicit:
an omitted optional member differs from a promised missing member.

The payload contains no QualityRun, disposition, selection receipt or generated
archive digest. This breaks the cycle: a package exists before its assessment.
Its assessed-subject digest binds the entire payload, lineage and member closure.
Metadata is data only; no shell arguments, arbitrary paths or probe expressions.

Add PACKAGING to the shared candidate payload union and PACKAGING_SLOT to the
closed target vocabulary through a reviewed M8 schema amendment. Broaden the
SQL candidate-kind constraint accordingly. Preserve all existing variants and
golden digests; older clients must fail on unknown kinds rather than coerce them
to FORMAT. The M8 artifact endpoint explicitly rejects packaging targets.

### QualityRun

Fields: run ID, command ID, scope, complete master binding, profile body/digest,
package revision/payload/subject digests, assessor identities and implementation
versions, input/output evidence digests, per-finding codes/severity/spans,
resource receipts and start/completion times. A run is sealed only when every
required assessor has a terminal typed result and referenced evidence exists.

Assessor outcomes: PASS, FINDINGS, ERROR or NOT_APPLICABLE. The latter requires
an explicit profile applicability rule and reason. Missing results, timeouts or
unavailable evidence are incomplete/error states, never successful zero scores.
Preserve disagreements and individual findings; no averaged score grants PASS.

Required first-profile assessors: deterministic media inspection/decode,
deterministic package-integrity/metadata checks and an authenticated human
semantic rubric. The same human may later issue the disposition explicitly.
The immutable run contains their recorded assessment, not a model-generated
impersonation. Automated semantic/model adapters are outside the first packet.

### QualityDisposition

Fields: decision ID, scope, exact master/profile/run/subject/package digests,
decision, issuer authorization, reason, issue/expiry times, expected decision
head version and explicit waived finding codes. Default validity is 24 hours,
maximum seven days; preview validity remains 15 minutes, maximum one hour.
Server time determines expiry. REWORK cannot be used for selection. PASS
requires complete evidence without blocking findings. WAIVE requires nonempty
reason, exact findings and profile permission for each waived code.

Integrity failures, missing bytes, malformed contracts, scope mismatch,
incomplete/error assessors and stale authority are never waivable. A new
effective profile, active run, package revision, master or decision head
invalidates current readiness. Old decisions remain append-only history.

### PackagingSelection and ExportBundle

A preview binds candidate revision/head version, full payload digest, exact
master/profile/run/disposition, target packaging slot and expected selection
head version. Selection records that closure atomically with a receipt and
increments only the M10 packaging head. It cannot target ARTIFACT_SLOT,
PRODUCTION_BINDING or a host manifest artifact key.

Export receipt binds selection ID/version/digest, canonical member manifest,
archive SHA-256/size, builder/runtime identity and immutable object reference.
It does not contain a provider ID, upload status or publication approval.

## 5. Technical probes and cost order

Order: schema/scope/current master → verified private member snapshots → cheap
metadata/integrity checks → complete decode/audio checks → human semantic review.
Hard prerequisite failure prevents later work. Record why each required check
did not run; do not seal an incomplete run as passing.

Reuse `verified_snapshot`, `media_facts` and `decode_errors` behavior where it
matches. The existing `run_process().communicate()` is not a resource bound.
The M10 adapter must cap retained diagnostics, bytes, pixels, duration, process
wall time and concurrency, kill/reap on cancellation and record the exact
tool version. Caller/profile data cannot extend host ceilings or construct argv.

First packet accepts local approved MP4 video; no URL, playlist, protocol input,
arbitrary filter or external subtitle reference. Restrict demuxers/protocols and
run without network access. File size/pixel/duration prechecks are necessary
but do not replace decoder resource isolation. Diagnose absent ffmpeg, invalid
JSON, nonfinite facts, decode errors and oversized output separately.

Checks cover full decode, dimensions/ratio/FPS/duration, selected video/audio
streams, explicit audio intent, promised member presence/digests, chapter bounds
and caption timing. Audio measurements inspect each selected stream, not just
container labels. Black/solid frames are evidence for review, not universal
creative failure. Do not use VMAF without a named reference; no VMAF is required
for the first export-only packet.

## 6. Persistence, replay and concurrency

Reuse shared M8 candidate heads/revisions for PackagingCandidate. Add M10-owned
profile versions/heads, run drafts/sealed runs/heads, human assessments,
dispositions/heads, packaging previews/selections/heads, export jobs/receipts
and command receipts. Database names and physical indexes belong to the plan;
these logical ownership and atomicity requirements do not.

The M8 command table permits only its existing operations. Use M10 command
receipts for new operations, rather than inserting unsupported operation names
or widening M8 semantics incidentally. Key: user/project/actor/operation/command.
Bind the complete request digest. Identical replay returns its stored immutable
result; a changed body is a conflict. Historical receipt replay never asserts
that its artifact remains currently exportable.

Proposed global lock order for M10 writers:

1. Scoped M10 command advisory key.
2. Shared candidate head, where the operation consumes a candidate.
3. M10 preview row, selection only.
4. Canonical master authority rows, sorted by artifact key; include the final
   and all source heads consumed by currentness, through the host lock helper.
5. Effective profile head, active run head and disposition head, in that order.
6. Packaging-slot head and export-job row, where required.

Create absent M10 head rows under a shared transaction advisory identity and
savepoint/unique constraint; locking a missing row is not a lock. Revalidate
every referenced immutable body under the final transaction and current DB time.
All competing M10 writers use this order. Existing master writers do not acquire
M10 locks; M10 never calls a master writer while holding its own heads. Exact
lock-helper reuse must be proved against all source-head writers before freeze.

Run sealing, disposition issuance, selection and export-ready commit each verify
their inputs under these guards. A master/profile/run/disposition writer racing
with selection either commits first and causes refusal, or waits until selection
commits; future readiness then becomes false. Human decisions changing the head
serialize with selection/export. Real PostgreSQL both-order fixtures, barriers
and observed blocking are mandatory; timing sleeps are not race evidence.

The released Alembic head is `918c4a0e0001`. Future migrations form one linear
chain from the revalidated V2 schema, broaden only the reviewed shared constraint
and create owned tables. No migration from paused M9 is imported. Downgrade may
not discard packaging history; a release/restore procedure must preserve data
or deterministically refuse unsafe downgrade. This draft executes no migration.

## 7. Deterministic export and recovery

Bundle layout: `video/output.mp4`, optional `captions/subtitles.srt`, optional
`thumbnails/thumbnail.<approved-extension>`, canonical `metadata/metadata.json`,
and `manifest.json`. The manifest lists every other member's role/path/size/
digest and binds the selected closure. It cannot include its own digest or
the archive digest. The outer receipt hashes the manifest and whole archive.

Proposed archive is ZIP_STORED, sorted ASCII member paths, fixed 1980 timestamp,
explicit Unix regular-file mode, no extra fields/comments, no directory entries
or symlinks. Approved input member bytes are copied unchanged; metadata text
normalization occurs before candidate identity and human review. Same selection
and builder version must produce byte-identical archives in fresh processes
and output roots. Pin serializer/runtime behavior and include a golden vector.

Build from verified private snapshots into an owned staging file; enforce
per-member/total size limits. Fsync, hash and publish a content-addressed object
without overwriting different bytes. Reverify the complete manifest and archive
after publication. Commit READY/receipt only while the exact selected closure
is still current. A private orphan has no downloadable authorization.

Job states: PREPARED → BUILDING → READY, or FAILED; lease/fencing generation
guards builder ownership. No network outcome-unknown state is needed. Recovery
reconciles an already published matching object, or rebuilds from the same
verified closure, without changing decision timestamps or content identity.
If authority moved/expired, retain historical job evidence and deny readiness.
An exact successful replay returns the receipt; missing/corrupt object is marked
unavailable and repaired only by a separately authorized, still-current command.

Download authorization checks current scope/selection/decision expiry, profile
and master under the same guards, then serves the verified file descriptor.
Its authorization point is this guarded snapshot; changes after headers are
sent do not retract bytes already authorized. A later request revalidates anew.
Tokens are scoped and short-lived and do not replace server revalidation.

## 8. Host interface and operator workflow

One M10 module owns profile/run/decision/selection/export invariants. Expose
small command methods to append a package, assess it, record the human decision,
preview/select it, request export and inspect current status/history. Persistence
and probe adapters remain internal. Read DTOs separate historical status from
current `exportable` and give typed refusal reasons.

The host composes these methods behind authenticated project routes under
`/projects/{project_name}/quality` and `/projects/{project_name}/packaging`.
Use existing scoped download-token facilities with a distinct purpose. No
probe/body field permits authority issuance. Existing final-video export and
Gate D APIs retain their meanings; their approvals do not authorize an M10
package. Future package-aware publication requires an explicit Gate D/M11
binding amendment.

Operator sequence: choose current approved final → prepare exact package → see
technical findings → complete semantic rubric → explicitly PASS/REWORK/WAIVE →
preview/select → download verified bundle. Any edited member requires a new
revision, assessment and decision. The initial implementation plan must include
integration into the existing project workflow, all supported translation keys,
accessible errors and stale/expired states. Visual choices follow the current
V2 UI rather than adding an independent dashboard.

## 9. Acceptance matrix and release packets

| Gate | Required evidence |
| --- | --- |
| V2 baseline | Exact release ancestry, source seals, current schema head, scoped change allowlist |
| Sequencing | Explicit export-only exception accepted; M9 preserved and no planned M9 call surface |
| Shared schema | Existing golden bodies/digests unchanged; PACKAGING rejected by M7 promotion paths |
| Contracts | Canonical vectors, malformed fields, digest/body tamper, no circular subject binding |
| Probes | Real decoded media, all selected audio, missing/oversized/nonfinite/timeout/cancel fixtures |
| Human decision | Auth/scope/expiry, exact waived codes, no waiver of integrity/incomplete evidence |
| Race/CAS | Both writer orders for master/profile/run/decision, first-head creation, one selection winner |
| Replay | Same-command identity, changed-body conflict, historical receipt vs current readiness |
| Bundle | Exact members and hashes, fresh-process byte identity, path/symlink rejection |
| Crash recovery | Real kill/reap at staging/fsync/publication/READY boundaries, fenced stale builder |
| Host regression | Existing Gate C/D/export and M8 artifact promotion still behave as released |
| Donor comparison | Exact pins, selected function/source hashes, same-fixture comparison and defect cases |
| Product flow | Authenticated operator path, all locales, stale/error/rework/waive states |
| Release | Targeted/full affected-domain checks required by project policy, independent review, restore proof |

Proposed packet order: A contracts/shared schema and baseline; B quality evidence
and bounded probes; C human decisions and packaging selection; D deterministic
export/recovery; E host UI and whole-M10 qualification. One active implementation/
review packet at a time. No acceptance label is issued by this document.

Before implementation: accept the bounded sequence amendment and design,
complete two independent normative reviews required by the architecture
contract, freeze exact contract/evidence hashes and migration boundary, and
produce the implementation plan/execution manifest. A builder check of this
draft establishes neither independence nor milestone acceptance.
