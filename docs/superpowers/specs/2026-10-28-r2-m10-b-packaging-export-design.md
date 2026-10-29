# M10-B — Packaging, Selection and Deterministic Export (design amendment)

Status: **ACCEPTED WITH CONDITIONS (r3)**. r1 (`1751a23bc`) REWORK
(`docs/r2/evidence/m10-b-reviews/design-b0-review.json`); r2 (`4d76003d5`) ACCEPT_WITH_CONDITIONS, no H
(`design-r2-delta-review.json`); r3 resolves its N1–N7 in place (§11, §12). Same-family review; Codex re-review
recommended when quota returns (C5).
Base: `0af66db9e` (M10-A accepted with conditions, `docs/r2/evidence/R2_M10_A_ACCEPTANCE.json`, source `b904bc000`).

Governing: plan Task B (`docs/superpowers/plans/2026-09-16-r2-m10-quality-packaging.md`), design §4.2, §5.2, §6,
§10 (`docs/superpowers/specs/2026-09-16-r2-m10-quality-packaging-design.md`), V2 rebase boundary
(`2026-10-25-r2-m10-v2-rebase.md`, audit row 6 and "Packaging slot identity/cardinality"), ADR-0080, ADR-0082,
ADR-0097 (M8 lock order). License is out of scope.

## 1. Scope

M10-B lets an operator turn an approved V2 final into an exact, Human-selected package and a byte-deterministic
local export bundle. It adds:

1. **F1** — durable failure ResourceEvidence (M10-A acceptance condition 1). Done in B0 (`d59be1e11`, `1a93a16e5`).
2. **Contracts** — packaging candidate, packaging observation, platform constraint snapshot, preview, selection,
   export manifest/receipt and their digest domains (§5.2 reserved names).
3. **M8 schema evolution** — `PACKAGING` candidate kind in the shared M8 revision kernel (§3.1 inventory).
4. **Packaging check** — pure, deterministic package checks producing a `PackagingObservation`.
5. **Selection** — preview + Human packaging selection into `PACKAGING_SLOT`, owning only the M10 packaging head.
6. **Export** — deterministic ZIP bundle as an M7 host-local execution family, with verification and recovery.
7. **Host surface** — authenticated routes and projection-only UI with every supported locale.
8. **Pilots** — Western explainer → vertical factual Short → `zh-shuang`, export-only, with Human decisions.
9. **Donor parity** — OpenMontage `export_bundle`/chapters and Kalinga SEO/variant behavior, frozen-before-measure.

Out of scope: upload/publication, provider APIs, network, Publish Approval, Gate D binding, model generation of
metadata. Title/description/tag/chapter/thumbnail **variants are required** (§3.3) but are operator- or
agent-authored inputs recorded with server-set provenance; no model/provider integration is qualified here.

## 2. Plan Task B step 1 — M8 schema-evolution verification (recorded)

Facts at `0af66db9e`:

- The candidate union is closed: `CandidatePayload = CanvasCandidate | SpatialCandidate | FormatCandidate`
  discriminated by `kind` (`r2/contracts/advanced_creative.py:474`), `ExplorationKind` has three members (`:31`),
  and SQL `ck_m8_candidate_revisions_kind IN ('CANVAS','SPATIAL','FORMAT')` (`lib/db/models/advanced_creative.py:74`,
  migration `8a8c4a0e0001`). There is no programmatic extension seam.
- The evolution path M8 does expose is the R2_03 §33 rule 1 / ADR-0080 path: an additive union member, an additive
  enum member, a CHECK-broadening migration, and differential predecessor tests proving every existing body,
  digest and behavior is unchanged. **Verdict: the path exists; M10-B uses exactly it and nothing else.**
- Every M8 code site that dispatches on kind, and its required behavior for `PACKAGING`:

| Site | Current behavior | PACKAGING behavior |
|---|---|---|
| `ExplorationService.append_revision` (`r2/advanced_creative/exploration.py:206`) | refuses only SPATIAL | also refuses PACKAGING: `CandidateConflictError("packaging revisions require the M10 packaging service")` |
| generic append route (`server/routers/advanced_creative.py:97`) | accepts CANVAS only | unchanged (already refuses PACKAGING) |
| `promotable_format` (`r2/advanced_creative/exploration.py:180`) | refuses every non-FORMAT kind with `PromotionTargetUnavailableError` | unchanged; PACKAGING is refused by the existing M8 error (no M8 dependency on an M10 code) |
| preview staging / `ExplorationPromotion` (`r2/advanced_creative/promotion.py:116,132`) | ARTIFACT_SLOT + `promotable_format` | unchanged; differential test proves PACKAGING never reaches a lock or Production Authority |
| `production_binding/spatial_set.py:98` | SPATIAL only | unchanged |
| `ExplorationRepository.append_revision` (`lib/db/repositories/advanced_creative.py:232`) | kind-agnostic CAS + M8 `APPEND_REVISION` command receipt | reused as is by the M10 packaging service; receipts are **M8 `APPEND_REVISION` receipts**, not M10 receipts |
| `digest_payload` | kind-agnostic canonical digest | reused; PACKAGING golden vector added, predecessor vectors re-verified |

`get_head` gains no lock mode: selection binds an immutable revision and never locks the M8 candidate head (§4).

## 3. Decisions (with rejected alternatives)

**D1 Shared kernel, M10-owned slot.** `PackagingCandidate` is a new member of `CandidatePayload` (kind
`PACKAGING`) stored in `m8_candidate_revisions` through `ExplorationRepository.append_revision`, called only by the
M10 packaging service. Selection writes the closed M10 target `PACKAGING_SLOT` (an M10 head, §4), never an M8
promotion. *Rejected:* a standalone package revision store (duplicates M8 CAS/replay, contradicts ADR-0080); a new
`PromotionTargetKind` (would route through Production Authority, which M10 must never call).

**D2 PACKAGING never promotes.** `PromotionTargetKind` is unchanged. The existing `promotable_format` refusal covers
PACKAGING after the M8 command key, candidate head and preview locks but before the slot lock and any Production
Authority port. Differential tests prove CANVAS/SPATIAL/FORMAT bodies, digests and promotion behavior
are unchanged and a PACKAGING revision reaches no Production Authority port.

**D3 Package checks are package-scoped observations, not run members.** (Revised from r1.) The M10-A `QualityRun`
seals observations whose `subject_digest` equals the base `AssessedSubject` digest (`r2/quality/runs.py:127`);
putting package observations in the run would force a new run **and a new Human disposition for every metadata
edit** and lets one run carry observations for different candidates. Instead:

- `PackagingObservation` uses the new `ObservationType.PACKAGING` with every common `ObservationBase` field; it is
  **not** added to the run's `QualityObservation` union (it lives in `r2/contracts/packaging.py`);
  its `subject_digest` is the digest of a `PackagingAssessedSubject` (base subject digest + candidate id/revision/
  payload digest + constraint snapshot digest). Run sealing is unchanged and continues to reject any observation
  whose subject is not the base subject, so a packaging observation can never enter a `QualityRun`.
- Packaging observations are stored append-only in `m10_packaging_observations`, one per check command
  (`CHECK_PACKAGE`, `m10.package-check-request.v1`), FK-bound to the exact M8 revision; an exact replay returns the
  stored observation after digest verification, a different request under the same command id conflicts, and the
  preview binds one exact `observation_id`.
- Selection requires (a) a **current** M10-A PASS/WAIVE disposition for the base subject and profile, and (b) a
  packaging observation for the **exact** candidate payload digest and the profile's constraint snapshot whose
  status is PASS, or whose BLOCKING findings are all in the profile's `packaging_waiverable_rule_ids` and are
  listed in the selection request's `waived_finding_ids` with a reason (the Human lease binds them; §3 D5).
  ADVISORY findings never block and are shown.
- Lifecycle: a packaging revision needs a new check (cheap, deterministic) and a new Human selection, but not a new
  run or disposition. A changed master/profile/run/disposition still stales the selection (§4).

*Rejected:* r1's packaging observations inside `QualityRun` (lifecycle cost above, mixed-candidate runs); a second
package-scoped run type (doubles A5 closure logic and its migration).

**D4 Platform constraints are a policy amendment.** `QualityPolicyV2` = every V1 field plus
`platform_constraints: PlatformConstraintSnapshot` and `packaging_waiverable_rule_ids`. The policy field of
draft/revision becomes the union `QualityPolicyV1 | QualityPolicyV2` discriminated by `schema_id`; all V1 vectors,
digests and stored rows are unchanged. V2 does **not** subclass V1 (its `schema_id` literal would be an incompatible
override): both subclass one shared `QualityPolicyFields` base holding every V1 field and the V1 `coherent`
validator, and A code typed against V1 (`r2/quality/runs.py:116`, digests) is retyped to the union. `AssessorKind`
gains no PACKAGING member, so no run slot can require a packaging observation. Profiles publish V2
through the accepted A3 Human publication path.

Rule semantics are server-owned: every `PackagingRule` names one closed `check_id` (`asset.integrity`,
`asset.required`, `closure.content|presentation|subject`, `binding.master|profile`, `duration.window`,
`video.dimensions`, `title.length|terms`, `description.length|terms`, `text.plain`, `tags.bounds`,
`hashtags.bounds`, `phrases.banned`, `chapters.rules`, `locales.coverage`, `variants.bounds`); its `rule_class`
must equal the fixed class of that check, each check is declared at most once, the six safety checks
(`asset.integrity`, three closures, two bindings) must be declared, safety-class rules are always BLOCKING, and
each asset role's `constraint_rule_id` must name the `asset.required` rule (required role) or the
`asset.integrity` rule (optional role). A policy therefore cannot relabel or downgrade a safety rule. The classes
are: `INTEGRITY` (asset digest/size/media type), `REQUIRED_ASSET`,
`CLOSURE` (content/presentation/subject digest), `CURRENTNESS` (master/profile/disposition binding), `DURATION`,
`METADATA_LINT`, `CHAPTER`, `LOCALE`, `VARIANT`. `INTEGRITY`, `REQUIRED_ASSET`, `CLOSURE` and `CURRENTNESS` are
non-waivable (rebase: authority, integrity, closure and currentness are never waived); V2 validation refuses a
`packaging_waiverable_rule_ids` entry naming such a rule (RED test in B1). Packaging requires a V2 profile; a V1 profile refuses with
`M10_PROFILE_STALE`. A changed constraint is a new profile revision.

`PlatformConstraintSnapshot` (`m10.platform-constraints.v1`): `platform_profile_id`, `platform_profile_revision`,
duration window (min/max ms), exact dimensions, title max length, description min/max length, `plain_text_only`,
title and description required terms (matched slug-tolerantly, Kalinga `seo_lint`), banned phrases, `tag_charset`
(closed enum), tag and hashtag min/max count and per-item max length, chapter rules (first at 0, ascending, min
length, max count), required/optional asset roles each with `constraint_rule_id`, accepted media types and byte
ceiling, required locales, variant group bounds (§3.3), and the declared `rules`.

**D5 Selection custody mirrors disposition.** `PackagingSelectionCustodianPort.authorize_selection` returns a
`PackagingSelectionAuthorizationLease` (`action = PACKAGING_SELECTION`, ≤30 s, DB-time admission) from the signed
HUMAN_SHOWRUNNER grant, outside the transaction, reusing the A6 custodian/attestor pattern and `require_actor`
JWT binding. The lease's `evidence_digest` binds the preview digest, which binds the observation digest and the
waived finding ids. The agent cannot obtain it. Lease refusals use the frozen `M10_DISPOSITION_UNAUTHORIZED`
("Human custodian lease is absent/invalid"); no new stop code is added.

**D6 Export is a ZIP_STORED archive.** Every `ZipInfo` field fixed: `compress_type=ZIP_STORED`,
`date_time=(1980,1,1,0,0,0)`, `create_system=3`, `create_version=extract_version=20`, `flag_bits=0` (member paths are
ASCII-only by validation), `external_attr=0o100644 << 16`, empty `extra` and `comment`, archive comment empty,
members sorted by bytewise path, no directories/symlinks. Pinned by a golden archive vector built on Linux; the
writer never reads host defaults. Layout: `video/output.mp4`, `captions/<locale>.srt`, `thumbnails/<variant>.<ext>`,
`metadata/metadata.json` (canonical JSON), `metadata/<locale>.json`, `manifest.json`. Path rules: relative,
normalized, `[a-z0-9._/-]`, no `..`, no case-folded duplicates. *Rejected:* directory bundles (no single digest,
non-atomic visibility).

**D7 Export is an M7 host-local family; M7 owns state.** (Revised from r1.) No `m10_export_jobs` table and no M10
lease/fence. Family `SubmitRouteKey("local-zip", "package-export", HOST_EXPORT_ADAPTER_VERSION)`, capability
`local-zip-package-export@host-export-v1` (`idempotency_mode=NONE`, `not_found_semantics=NON_AUTHORITATIVE`, no
poll/cancel/lookup/webhook, `OFFLINE_VERIFIED`), mirroring `local-ffmpeg-format-projection` and the probe family:

1. **Prepare** (command guard held): resolve and lock the selection closure (§4), stage an append-only
   `m10_export_invocations` row (request digest, execution id, selection receipt id, manifest digest computed in
   advance from the verified closure) and let the M7 submitter commit PLANNED with it.
2. **Execute** (outside any metadata transaction): the M7 `submit` callback runs a fixed stdlib archive-builder
   worker in a **separate export envelope** — a transient unit built by the A4 unit-property code but with its own
   identity and limits, not the probe envelope (which precreates three scratch inodes, caps files at 64 MiB and
   verifies only ffmpeg/ffprobe/vmaf identities): same `SystemCallFilter=~@network-io …` and
   `SystemCallErrorNumber=EPERM`; read-only bind of the verified snapshot directory; one writable private output
   directory; `LimitFSIZE` = closure byte total + 1 MiB; runtime cap 30 s + 1 s per 50 MiB; worker file pinned by
   digest as its tool identity. The worker writes `exports/.partial-<execution_id>.zip`; the host then fsyncs,
   renames to the content-addressed
   `exports/<sha256>.zip`, fsyncs the directory, re-verifies the bytes and returns
   `provider_job_id = "<execution_id>:<archive digest>"`. M7 records ACCEPTED.
3. **Finalize** (one transaction, §4 order): recompute the closure, re-verify the published object against the
   job id digest and the precomputed manifest, then apply M7 `SUCCEEDED` and insert the immutable
   `m10_export_receipts` row together.

Recovery: ACCEPTED-but-not-finalized replays finalize from the job id (format-render `_accepted_digest` pattern).
`SUBMIT_OUTCOME_UNKNOWN` (crash during execute) is never re-run under the same execution; the operator re-requests
with a new command, and because the archive is deterministic the new execution produces the identical digest and
reconciles an already-published identical object. `FAILED_BEFORE_ACCEPTANCE` (a known refusal in the callback)
raises its typed error in that call; a later replay of the failed command reports `M10_EXPORT_INTEGRITY_FAILED`
(export refusals are not quality evidence, so no failure record is kept; a new command re-plans and reports the
typed refusal again). Disk-full and rename failures surface as known failures before acceptance; any partial
file is removed. Status vocabulary is `EXPORTED`; nothing records upload/publish/visibility.

Implementation (B4 review): the worker is `server/services/package_export_worker.py` launched through the A4
`QualityProbeRuntime.launch` (unit prefix `m10-export`, `LimitFSIZE` = exact archive size + 1 MiB, runtime
30 s + 1 s per 50 MiB, the A4 cgroup envelope and seccomp filter). It verifies the envelope with the A4 `confine`
(Landlock: read-only snapshot files, one output inode precreated by the host, no network) before writing. Host
scratch lives in `exports/.work-<uuid>/` held by an exclusive `owner.lock` flock; all host directory work
(snapshots, rename, fsync) goes through descriptors pinned no-follow from the project root. The plan (layout,
documents, manifest and exact archive size including headers and the zipfile no-ZIP64 member margin) is computed
before any byte is copied; paths are claimed case-insensitively and never overwrite (`metadata/metadata.json` is
reserved). Caption assets declare their locale in the role (`captions-<locale>` → `captions/<locale>.<ext>`).
Finalize verifies outside locks that the published object is exactly the stored manifest's archive (member names,
fixed fields, manifest bytes, digest) and that the stored request reproduces the execution identity and M7 task,
then rechecks the pinned file generation under the lock. Worker refusals (`INTEGRITY_FAILED`,
`ENVELOPE_EXCEEDED`) fail the attempt; any other worker result is `SUBMIT_OUTCOME_UNKNOWN` and is never rebuilt
under that command. The sweep removes only work directories whose owner lock it can take and whose
lock is older than the longest worker runtime. Delta (B4 review 2): work directories are created under a
`.creating-` name and renamed only after their owner flock is held; the worker reopens every snapshot, the
manifest and the output with no-follow and requires the exact `(dev, ino)` the host created, so an ancestor swap
can redirect neither a read nor a write; the worker reports its own and the confinement module's digests, the
envelope and the Landlock ABI, all checked by the host; a refusal is known only with exit 1 and a verified unit
cleanup, otherwise the attempt is unknown and its scratch is kept for the sweep; the published-file generation
includes ctime. The project root itself is a trusted host path (`LOCAL_REGULAR_FILE_IO`): only components below it
are walked no-follow.

Envelope: closure total and every member must stay below 2^31 bytes, otherwise `M10_OPERATIONAL_ENVELOPE_EXCEEDED`
before PLANNED, so zipfile never emits ZIP64 extras (`allowZip64=False`). Orphans: a `.partial-<execution_id>.zip`
is removed at the start of its own execute and by a sweep that removes partials whose attempt is terminal or
`SUBMIT_OUTCOME_UNKNOWN`. B4 deliverables include `PACKAGE_EXPORT_SUBMIT_FAMILIES` in
`r2/host_hardening/route_inventory.py`, the `local-zip-package-export@host-export-v1` entry in
`r2/provider_capabilities/registry.json` with its evidence, and the scope-verifier/route-inventory test updates
that admit exactly this family.

**D8 F1 persistence** (implemented in B0). Append-only `m10_quality_probe_failures` flushed in the M7 submit session
so it commits iff the attempt commits `FAILED_BEFORE_ACCEPTANCE`; a staging error turns the outcome into
`SUBMIT_OUTCOME_UNKNOWN` with no row. Known failures raised before the tool callback (catalog/route refusal) are
ordinary request errors and carry no row. Replay returns the stored evidence after digest verification.

## 3.1 Contracts and module placement

Import constraint (resolves an otherwise certain cycle): `r2/contracts/quality.py` imports
`r2/contracts/advanced_creative.py`, so the kernel cannot import M10 models. Therefore:

- `PackagingCandidate` and its nested value types (`PackagingAsset`, `LocalizedPackagingMetadata`,
  `PackagingChapter`, `VariantGroup`, `AudienceClassification`, `DisclosureSet`, `PackagingProvenance`) live in
  `r2/contracts/advanced_creative.py` on `M8ContractModel`, depending only on `r2.contracts.common` and the kernel's
  own `Sha256Digest`/`CanonicalJsonObject`. They are pure data; M10 rules are enforced by the M10 check.
- Every other M10-B shape lives in `r2/contracts/packaging.py` on `M10ContractModel` and imports the kernel.

`PackagingCandidate` fields (ADR-0082 and §4.2 mapping):

- `kind="PACKAGING"`, `approved_master_id`, `approved_master_digest`, `assessed_subject_digest`;
- `quality_profile_id`, `quality_profile_revision`, `quality_profile_digest`; `platform_profile_id`,
  `platform_profile_revision`, `constraint_snapshot_digest` (from the V2 policy);
- **content** group: `title`, `description`, `tags`, `hashtags`, `chapters: tuple[PackagingChapter]`
  (`start_ms`, `title`), `localization_variants`, `audience_classification`, `disclosure`, `variant_groups`;
- **presentation** group: `assets: tuple[PackagingAsset]` (`role`, `variant_id | None`, `source_ref`,
  `content_digest`, `media_type`, `byte_size`, `constraint_rule_id`);
- `content_closure_digest` (`m10.packaging-content.v1` over the content group) and `presentation_closure_digest`
  (`m10.packaging-presentation.v1` over the presentation group), recomputed by the server on append and by the check;
- `provenance: tuple[PackagingProvenance]` per field group: `author_kind` (`HUMAN`|`AGENT`), `actor_id`,
  **set by the server from the authenticated principal**, never accepted from the client.

The kernel does not require a candidate to keep its kind across revisions, so the packaging service refuses to
append to, check, preview or select from a candidate whose current head revision is not PACKAGING
(`M10_STALE_HEAD`); a polluted candidate is abandoned for a new candidate id.

M8 `LineageBinding` for PACKAGING: `content_basis_digest` = the master's content basis, `approved_master_id/digest`
= the bound master (non-null), `creative_profile_id` = quality profile id, `creative_profile_version` =
`str(quality_profile_revision)`, `policy_digest` = the profile's policy digest.

M10 shapes: `PackagingAssessedSubject`, `PackagingObservation` (`ObservationBase[PACKAGING]` + `packaging_subject`,
`constraint_snapshot_digest`, `rule_results_digest`, findings), `PackagePreview`, `PackageSelectionRequest`,
`PackagingSelectionAuthorizationLease`, `PackageSelection` (receipt), `ExportRequest`, `ExportManifest`
(entries: path, media type, byte size, digest; binds selection receipt, disposition, tool/config identities),
`ExportBundleReceipt`.

Domains: `m10.platform-constraints.v1`, `m10.packaging-content.v1`, `m10.packaging-presentation.v1`,
`m10.packaging-candidate.v1`, `m10.packaging-subject.v1`, `m10.packaging-observation.v1`, `m10.package-preview.v1`,
`m10.package-selection-request.v1`, `m10.package-selection.v1`, `m10.export-request.v1`,
`m10.export-manifest.v1`, `m10.export-execution.v1` (`ExportExecutionIdentity`: slot, selection, manifest digest,
builder identity, adapter version), `m10.quality-policy.v2`. Golden vectors for every domain frozen in B1;
M10-A and M8 vectors re-verified unchanged.

## 3.3 Variants

`variant_groups: tuple[VariantGroup]`, each `{group_id, field ∈ {title, description, tags, chapters, thumbnail},
variants: tuple[{variant_id, value | asset role ref, provenance{author_kind, actor_id}}]}` with 1..N variants. Constraint rules bound the
group count and per-group variant count; every variant is checked like the primary value. The selection request
names exactly one `variant_id` per group; the preview and selection bind the chosen set, and export materializes
only the chosen variants (`ExportManifest.chosen_variants`: one `{group_id, variant_id}` per group, canonical
order). This covers Kalinga's title/thumbnail variant
behavior in the parity set.

## 4. Persistence, slot identity, locks and replay

Tables (append-only unless noted): `m10_quality_probe_failures` (B0), `m10_packaging_observations`,
`m10_package_previews`, `m10_package_selections`, `m10_packaging_heads` (CAS head, the only mutable row),
`m10_export_invocations`, `m10_export_receipts`; M10 command receipts for check/preview/select/export. The
`ExplorationKind` enum gains `PACKAGING` and the CHECK on `m8_candidate_revisions.kind` is broadened. One linear
migration chain from `4c1f0e2a9b10`; downgrade refuses while M10-B rows or PACKAGING revisions exist.

**`PACKAGING_SLOT` identity.** One head per `(user_id, project_name, source_artifact_key, cohort_id,
product_surface)` (rebase cardinality). `source_artifact_key` is the master's canonical artifact key. The slot
key encoding is the canonical-JSON array of the five values (no delimiter ambiguity), case-sensitive exact
identities; a unique constraint covers the five columns. The head stores `selection_receipt_id`,
`head_version`, `quality_profile_revision` (bound data, not part of the key). Fixtures: delimiter/case/
cross-cohort/cross-surface/cross-project non-collision, CAS, migration.

**Global order** (one order for every M10 writer; it is the real A5/A6 order — `quality_runs.py` seal and
`quality_dispositions.py` decide both take command guard → `lock_subject_masters` → `lock_profile_head` (FOR SHARE)
→ run head → disposition head → `lock_grant_heads` (sorted, FOR UPDATE) — extended by the M10-B rows):

`receipt replay → command guard → lock_subject_masters (sorted, the existing exclusive no-op UPDATE) →
lock_profile_head (FOR SHARE) → run head (FOR SHARE) → disposition head (FOR SHARE) → preview row (FOR UPDATE) →
packaging-head advisory (m10.packaging-head.v1 over the slot key) → packaging head row (FOR UPDATE for selection,
FOR SHARE for export) → export invocation → lock_grant_heads (sorted, FOR UPDATE, reused helper; validity_in /
load_run_observations re-take the same set, which is idempotent) → M7 attempt row`.

- Masters reuse `lock_subject_masters`; there is no FOR SHARE master helper and M10-B adds none.
- Selection and export prepare/finalize evaluate currentness with the A `validity_in` inside their own transaction
  after the packaging-head row and before the attempt row, so its grant-head locks fall at the grant-heads position.
- **A newer run stales a selection**: the selection binds `quality_run_id`; under the run head lock the head must
  still name that run and `validity_in` must not report `newer_run`/SUPERSEDED, otherwise `M10_DISPOSITION_STALE`.
  Because the run head is FOR SHARE-locked, a concurrent run seal (which locks it exclusively) serializes against
  selection and finalize instead of slipping between read and write.
- Serialization points actually observed (B3 barrier tests identify the blocked backend via `pg_blocking_pids`
  and its statement): for one subject every writer first serializes on the subject's master rows (or, for an
  issuer/sealer, already on the shared Human grant head its lease/grant transaction reads), so the later run,
  disposition and packaging head modes are reached only by the winner; across subjects with disjoint master-row
  sets contention exists only on
  the profile head (publication FOR UPDATE waits behind selection FOR SHARE) and on grant heads, which every writer
  takes as one sorted set. Multi-principal disjoint-master cycles are excluded by construction (one sorted grant
  set per writer), not by a dedicated fixture.
- Absent packaging heads are inserted under the head-keyed advisory lock, so two different commands for the same
  slot serialize on the head, not only on their command keys.
- Disposition writers and run seals never take a preview, packaging or export lock; M7 workers lock only the
  attempt row; M8 writers take only M8 command keys and candidate heads, which no M10-B writer locks. Every writer
  that takes two of these locks takes them in the order above, so no cycle exists across M8, M10-A, M10-B and M7.
- Tentative closure is resolved outside the transaction and recomputed under the guard; if the lock set changed,
  roll back and resolve again; no media/tool I/O while holding locks.
- Real PostgreSQL tests for every writer pair (selection × disposition, selection × run seal, export finalize ×
  run seal, selection × export finalize, export finalize × disposition, selection × selection on one slot with
  different commands, profile publication × selection), with barriers and an observed blocked waiter including a
  queued FOR UPDATE behind FOR SHARE; ordering is driven by events, never by sleeps (bounded polling only
  observes `pg_stat_activity`).

Currentness: a selection is exportable only while master, profile head, the bound run (still the run head), the bound disposition (unexpired, not
superseded, still the current decision for its run) and the packaging head are exactly as bound. The selected
candidate revision is immutable, so a newer candidate revision does not stale an existing selection; it only
becomes selectable after its own check and selection. Drift → `M10_SUBJECT_STALE` / `M10_DISPOSITION_STALE` /
`M10_STALE_HEAD`; history is never rewritten.

## 5. Packaging checks (pure)

Cheap-first inside the packaging check: asset digest/size re-hash from generation-stable no-follow reads → required roles,
media types, byte ceilings → duration window vs master facts → metadata lint (lengths, tag/hashtag count and
charset, required topic terms, banned phrases, chapter ordering/first-at-zero/min length) → locale coverage →
variant group rules. Master facts (duration, video width/height) come from the bound run's verified `CONTAINER_STREAM` probe result
(M10-A replay with digest verification), never re-measured; a run without that probe refuses with
`M10_REQUIRED_EVIDENCE_MISSING`. Asset facts come from the host re-hashing each canonical-spelling `source_ref`
opened component by component from a pinned project-root descriptor (no-follow, non-blocking, regular files only),
reading at most the role byte ceiling plus one byte with full UTF-8 validation for text types, and accepting the
read only when the inode generation (device, inode, size, mtime, ctime) is identical before and after; the whole
measurement has a deadline (`M10_OPERATIONAL_ENVELOPE_EXCEEDED`). The check retains no bytes, so it keeps no
snapshot; B4 export materializes verified private snapshots before building. The `video` role must be the master
inode itself. Every inline variant has its field's canonical value shape, enforced by the kernel contract. Supported storage
(`LOCAL_REGULAR_FILE_IO`): the in-process measurement worker is supported only on host-managed local storage where
regular-file open/read/stat return; the caller's wait is bounded by the event-loop timeout and the worker stops
cooperatively before each asset and each read, but a read blocked inside the kernel (e.g. a hung network mount)
cannot be interrupted in-process. Broader storage needs the confined-unit envelope before activation. The pure check lives in
`r2/quality/packaging_check.py`: every declared rule runs in declaration order and the observation is FAIL iff a
BLOCKING rule failed. Kalinga `seo_lint` and OpenMontage chapter formatting are reimplemented as pure functions;
the donors run only in parity tests from digest-checked pinned sources (A7 pattern).

## 6. Host surface and UI

Routes under `/projects/{project_name}/packaging`: append candidate revision (server-set provenance), run check,
preview, select (Human custodian), request export, export status/history, download (scoped short-lived token,
purpose `m10-export`, server revalidates currentness under the guarded snapshot). Read DTOs separate historical
status from current `exportable` with typed refusal reasons. UI: a packaging panel in the existing V2 project
workflow showing findings, waivers, disposition state, variants, selection and export; empty/partial/failed/stale/
waived/superseded/invalidated states; keyboard/focus/reduced-motion; axe-core; all locales in `frontend/src/i18n/`.

## 7. Pilots and utility evidence (preregistered before running, frozen commit)

- Corpora: one approved final per cohort plus, per cohort, a **seeded-defect copy** with ≥6 known defects drawn from
  the rule set (missing required asset, byte drift, duration out of window, over-long title, banned phrase,
  chapter not at 0, missing locale).
- Reviewer: the sponsor as Human showrunner (single reviewer; independence limit recorded).
- Metrics, each with its preregistered threshold: seeded recall ≥ 5/6 per cohort (false negatives listed);
  false positives on the clean final ≤ 1 per cohort as judged by the reviewer; reviewer disagreement (per finding:
  check verdict vs Human verdict) reported in full; runtime per bundle ≤ 30 s; peak RSS ≤ 512 MiB; bundle storage
  bytes reported against master bytes; determinism = (a) a new export command for the same selection produces the
  byte-identical archive (the §3 recovery property), and (b) every content member (video, thumbnails, captions,
  metadata) is byte-identical across two independent clean roots built from the same frozen logical inputs.
  `manifest.json` binds the selection, disposition and candidate payload of its own root, so whole archives from
  independent roots differ by design and are not compared.
  _Post-run amendment 2026-10-29:_ the frozen wording "byte-identical archives from two clean roots" contradicted the
  manifest's provenance binding; B7 measured it as written (failed in every cohort, only `manifest.json` differed)
  and the definition above replaces it for later runs. Provenance stays in the archive because finalize, recovery
  and offline verification check the archive against the selection that produced it.
- Smallest useful effect: the seeded recall threshold is met **and** at least one of (a real defect caught on a
  clean final, or a confirmed correction made through the panel) is recorded. "Nothing found" on clean finals
  never satisfies the effect on its own.
- Runtime absence of network: the archive builder runs in the D7 export envelope (`SystemCallFilter=~@network-io …`,
  `SystemCallErrorNumber=EPERM`); evidence records the unit properties and a `socket()` attempt from inside the
  unit failing with `EPERM`. The claim covers only the confined builder and the confined probes; host-side check,
  rename and verification code is covered by the static scan, and that limit is recorded.
- Order: Western explainer → vertical factual Short → `zh-shuang`; each needs a published V2 profile, a Human
  disposition and a Human selection. The agent prepares everything and stops at each Human gate.

## 8. Acceptance matrix

| Gate | Evidence |
|---|---|
| F1 | row committed iff FAILED_BEFORE_ACCEPTANCE; staging failure → unknown, no row; replay returns evidence; tamper refused; late-read replay |
| Step 1 | §2 inventory re-verified at the B1 HEAD |
| Shared schema | M8 golden bodies/digests unchanged; PACKAGING refused by generic append, promotion and preview; CHECK migration round trip and refusing downgrade |
| Contracts | golden vectors; RED: mutable payloads, tamper, malformed, undeclared/duplicate/missing roles, duplicate assets, client-supplied provenance, no circular subject binding, closure digest mismatch |
| Packaging checks | ported lint + duration window + variants, seeded-defect fixtures, deterministic digests, packaging observation refused by run sealing |
| Selection | RED: Human-only lease, stale master/profile/disposition, preview expiry, target confusion, head CAS, command conflict, unwaivable finding, waiver outside the lease; every writer-pair order test (§4); replay |
| Export | golden archive; same-selection re-export byte-identical and content members identical across clean roots (§7); RED: unsafe paths, case-colliding names, missing assets, byte drift, disk-full, interruption before/after rename, unknown outcome re-request with a new command; replay |
| Host regression | Gate C/D/export, M8 promotion, M10-A behavior unchanged |
| Donor parity | frozen baseline, OpenMontage + Kalinga same-fixture, PASS recomputed |
| UI | i18n consistency, states, axe-core |
| Pilots | three dossiers with Human decisions and the §7 preregistered metrics |
| Surface | static scan plus §7 runtime network denial; no credential/upload; no Production Authority write |

## 9. Packets (one active at a time, each reviewed)

B0 F1 (done) · B1 contracts + M8 evolution + policy V2 · B2 packaging check · B3 preview/selection ·
B4 export + recovery · B5 routes + UI · B6 donor parity · B7 pilots (Human) · B8 seal M10-B.
M10-C is evidence-only and created only if acceptance cannot bind A and B directly.

## 10. Stop conditions

Any need to modify accepted M8 semantics beyond the §2 table, any network/credential surface, any agent path to a
Human lease, or a parity row that cannot reach PASS under the frozen criteria stops the packet for review.

## 11. r1 review resolution

| Finding | Resolution |
|---|---|
| H1 finalize order inverted | §4 single global order; finalize takes disposition before packaging head and locks masters/profile; writer-pair tests |
| H2 second job truth | D7: no `m10_export_jobs`; append-only invocation bound to an M7 attempt; idempotency NONE; recovery by job id / new command |
| M1 slot undefined, head race | §4 `PACKAGING_SLOT` five-tuple key, canonical encoding, head-keyed advisory |
| M2 step 1 / M8 inventory | §2 table; receipts are M8 `APPEND_REVISION`; no `get_head` lock needed |
| M3 import cycle | §3.1 placement: kernel payload in `advanced_creative.py`, M10 shapes in `packaging.py` |
| M4 D3 gaps | D3 revised: package-scoped observations, run sealing unchanged, waiver rules, lifecycle stated |
| M5 dropped fields | §3.1 content/presentation closure digests, platform profile ids, `constraint_rule_id` |
| M6 variants | §3.3 |
| M7 pilot metrics / runtime network | §7 |
| M8 B0 tests | `1a93a16e5` |
| L1 ZIP fields | D6 every `ZipInfo` field fixed |
| L2 failure digest excludes code | accepted as is: `error_code` is CHECK-bounded and replayed as its typed class; the digest covers the evidence body |
| L3 F1 wording | §8 F1 row, D8 |
| L4 provenance | §3.1 server-set |
| L5 M8 → M10 error | D2 uses the existing M8 refusal |
| L6 RED cases | §8 Contracts/Selection/Export rows |
| L7 earlier A downgrades | unchanged known limit L5 of M10-A; M10-B downgrades refuse |

## 12. r2 delta review resolution

| Finding | Resolution |
|---|---|
| N1 run head / grant heads / master mode / newer run | §4 global order now the real A5/A6 order plus M10-B rows; newer run stales; run-seal pair tests |
| N2 export cannot use the probe envelope | D7 separate export envelope with its own limits and identity; §7 claim scoped; B4 deliverables listed |
| N3 unrestricted waivers | D4 closed `rule_class`, non-waivable classes refused by V2 validation |
| N4 D2 wording, line refs | D2 corrected |
| N5 kind continuity | §3.1 packaging service refuses a non-PACKAGING head |
| N6 ZIP64, orphans, deliverables | D7 envelope paragraph |
| N7 V2 typing, AssessorKind | D4 shared `QualityPolicyFields` base; no PACKAGING assessor kind |
