# M10-B — Packaging, Selection and Deterministic Export (design amendment)

Status: **CANDIDATE r2**, pending delta re-review. r1 (`1751a23bc`) was reviewed REWORK
(`docs/r2/evidence/m10-b-reviews/design-b0-review.json`); §11 maps every finding to its resolution.
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
PACKAGING before any lock. Differential tests prove CANVAS/SPATIAL/FORMAT bodies, digests and promotion behavior
are unchanged and a PACKAGING revision reaches no Production Authority port.

**D3 Package checks are package-scoped observations, not run members.** (Revised from r1.) The M10-A `QualityRun`
seals observations whose `subject_digest` equals the base `AssessedSubject` digest (`r2/quality/runs.py:127`);
putting package observations in the run would force a new run **and a new Human disposition for every metadata
edit** and lets one run carry observations for different candidates. Instead:

- `PackagingObservation` is a new member of the observation union with every common `ObservationBase` field;
  its `subject_digest` is the digest of a `PackagingAssessedSubject` (base subject digest + candidate id/revision/
  payload digest + constraint snapshot digest). Run sealing is unchanged and continues to reject any observation
  whose subject is not the base subject, so a packaging observation can never enter a `QualityRun`.
- Packaging observations are stored append-only in `m10_packaging_observations`, one per
  `(candidate_id, revision, constraint_snapshot_digest, check_config_digest)`; replay recomputes the pure check.
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
digests and stored rows are unchanged and V2 carries every V1 attribute, so A code reads both. Profiles publish V2
through the accepted A3 Human publication path. Packaging requires a V2 profile; a V1 profile refuses with
`M10_PROFILE_STALE`. A changed constraint is a new profile revision.

`PlatformConstraintSnapshot` (`m10.platform-constraints.v1`): `platform_profile_id`, `platform_profile_revision`,
duration window (min/max ms), aspect + exact dimensions, title/description length, tag/hashtag count, charset and
per-item length, required topic terms, banned phrases, chapter rules (first at 0, ascending, min length, max
count), required/optional asset roles each with `constraint_rule_id`, accepted media types and byte ceiling,
required locales, variant group rules (§3.3).

**D5 Selection custody mirrors disposition.** `PackagingSelectionCustodianPort.authorize_selection` returns a
`PackagingSelectionAuthorizationLease` (`action = PACKAGING_SELECTION`, ≤30 s, DB-time admission) from the signed
HUMAN_SHOWRUNNER grant, outside the transaction, reusing the A6 custodian/attestor pattern and `require_actor`
JWT binding. The lease's `evidence_digest` binds the preview digest, which binds the observation digest and the
waived finding ids. The agent cannot obtain it.

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
2. **Execute** (outside any metadata transaction): the M7 `submit` callback runs the stdlib archive builder in the
   A4 confined transient unit (same launcher, read-only verified snapshots, one writable scratch dir), which
   writes `exports/.partial-<uuid>.zip`; the host then fsyncs, renames to the content-addressed
   `exports/<sha256>.zip`, fsyncs the directory, re-verifies the bytes and returns
   `provider_job_id = "<execution_id>:<archive digest>"`. M7 records ACCEPTED.
3. **Finalize** (one transaction, §4 order): recompute the closure, re-verify the published object against the
   job id digest and the precomputed manifest, then apply M7 `SUCCEEDED` and insert the immutable
   `m10_export_receipts` row together.

Recovery: ACCEPTED-but-not-finalized replays finalize from the job id (format-render `_accepted_digest` pattern).
`SUBMIT_OUTCOME_UNKNOWN` (crash during execute) is never re-run under the same execution; the operator re-requests
with a new command, and because the archive is deterministic the new execution produces the identical digest and
reconciles an already-published identical object. `FAILED_BEFORE_ACCEPTANCE` (validation failed in the callback)
replays its typed error. Disk-full and rename failures surface as known failures before acceptance; any partial
file is removed. Status vocabulary is `EXPORTED`; nothing records upload/publish/visibility.

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
`m10.export-manifest.v1`, `m10.export-execution.v1`, `m10.quality-policy.v2`. Golden vectors frozen in B1;
M10-A and M8 vectors re-verified unchanged.

## 3.3 Variants

`variant_groups: tuple[VariantGroup]`, each `{group_id, field ∈ {title, description, tags, chapters, thumbnail},
variants: tuple[{variant_id, value | asset role ref, provenance}]}` with 1..N variants. Constraint rules bound the
group count and per-group variant count; every variant is checked like the primary value. The selection request
names exactly one `variant_id` per group; the preview and selection bind the chosen set, and export materializes
only the chosen variants (the manifest records the chosen ids). This covers Kalinga's title/thumbnail variant
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

**Global order** (one order for every M10 writer, extending the A order "command guard → sorted masters →
profile head → disposition head → grant heads"):

`receipt replay → command guard → sorted master rows → profile head → disposition head → packaging-head advisory
(m10.packaging-head.v1 over the slot key) → packaging head row → export invocation → grant heads (sorted) →
M7 attempt row`.

- Selection: masters, profile head and disposition head **FOR SHARE**; preview row FOR UPDATE (taken after the
  disposition head, before the packaging-head advisory); packaging head advisory + FOR UPDATE; grant heads
  FOR SHARE. Absent heads are inserted under the head-keyed advisory lock, so two different commands for the same
  slot serialize on the head, not only on their command keys.
- Export prepare and finalize: the same prefix with masters/profile/disposition/packaging head **FOR SHARE**, then
  the M7 attempt row (M7's own transition lock). Finalize therefore never takes the packaging head before the
  disposition head.
- Disposition writers (A6) never take a packaging lock; M7 workers lock only the attempt row; M8 writers take only
  M8 command keys and candidate heads, which no M10-B writer locks. Hence no cycle exists across M8, M10-A,
  M10-B and M7 writers.
- Tentative closure is resolved outside the transaction and recomputed under the guard; if the lock set changed,
  roll back and resolve again; no media/tool I/O while holding locks.
- Real PostgreSQL tests for every writer pair (selection × disposition, selection × export finalize, export
  finalize × disposition, selection × selection on one slot with different commands, profile publication ×
  selection), with barriers and an observed blocked waiter including a queued FOR UPDATE behind FOR SHARE;
  no sleeps.

Currentness: a selection is exportable only while master, profile head, the bound disposition (unexpired, not
superseded, still the current decision for its run) and the packaging head are exactly as bound. The selected
candidate revision is immutable, so a newer candidate revision does not stale an existing selection; it only
becomes selectable after its own check and selection. Drift → `M10_SUBJECT_STALE` / `M10_DISPOSITION_STALE` /
`M10_STALE_HEAD`; history is never rewritten.

## 5. Packaging checks (pure)

Cheap-first inside the packaging check: asset digest/size re-hash from verified private snapshots → required roles,
media types, byte ceilings → duration window vs master facts → metadata lint (lengths, tag/hashtag count and
charset, required topic terms, banned phrases, chapter ordering/first-at-zero/min length) → locale coverage →
variant group rules. Kalinga `seo_lint` and OpenMontage chapter formatting are reimplemented as pure functions;
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
  bytes reported against master bytes; determinism = byte-identical archives from two clean roots.
- Smallest useful effect: the seeded recall threshold is met **and** at least one of (a real defect caught on a
  clean final, or a confirmed correction made through the panel) is recorded. "Nothing found" on clean finals
  never satisfies the effect on its own.
- Runtime absence of network: the archive builder runs in the A4 confined transient unit
  (`server/services/quality_probe_runtime.py`: `SystemCallFilter=~@network-io …`, `SystemCallErrorNumber=EPERM`);
  evidence records the unit properties and a `socket()` attempt from inside the unit failing with `EPERM`,
  in addition to the static scan.
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
| Export | golden archive; two clean roots byte-identical; RED: unsafe paths, case-colliding names, missing assets, byte drift, disk-full, interruption before/after rename, unknown outcome re-request with a new command; replay |
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
