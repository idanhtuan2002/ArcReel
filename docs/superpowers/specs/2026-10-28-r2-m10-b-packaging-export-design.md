# M10-B — Packaging, Selection and Deterministic Export (design amendment)

Status: **CANDIDATE**, pending independent review. Base: `0af66db9e` (M10-A accepted with conditions,
`docs/r2/evidence/R2_M10_A_ACCEPTANCE.json`, source `b904bc000`).

Governing: plan Task B (`docs/superpowers/plans/2026-09-16-r2-m10-quality-packaging.md`), design §4.2, §5.2, §6,
§10 (`docs/superpowers/specs/2026-09-16-r2-m10-quality-packaging-design.md`), V2 rebase boundary
(`2026-10-25-r2-m10-v2-rebase.md`), ADR-0080, ADR-0082, ADR-0097 (M8 lock order). License is out of scope.

## 1. Scope

M10-B lets an operator turn an approved V2 final into an exact, Human-selected package and a byte-deterministic
local export bundle. It adds:

1. **F1** — durable failure ResourceEvidence (M10-A acceptance condition 1).
2. **Contracts** — packaging candidate, packaging observation, platform constraint snapshot, selection, export
   manifest/receipt and their digest domains (§5.2 reserved names).
3. **M8 schema evolution** — `PACKAGING` candidate kind in the shared M8 revision kernel.
4. **Packaging observation** — pure, deterministic package checks: asset integrity, required roles, metadata lint
   (ported Kalinga `seo_lint`) and duration window (carried A7 exclusions).
5. **Selection** — preview + Human packaging selection with a custodian lease, owning only the M10 packaging head.
6. **Export** — deterministic ZIP bundle through M7 execution, verification, recovery and download.
7. **Host surface** — authenticated routes and projection-only UI with every supported locale.
8. **Pilots** — Western explainer → vertical factual Short → `zh-shuang`, export-only, with Human decisions.
9. **Donor parity** — OpenMontage `export_bundle` and Kalinga SEO/variant behavior, frozen-before-measure.

Out of scope: upload/publication, provider APIs, network, Publish Approval, Gate D binding, generation of metadata
by models (generated title/description/tag variants are **operator- or agent-authored inputs** recorded with
provenance; no model/provider integration is qualified here).

## 2. Decisions (with rejected alternatives)

**D1 Shared kernel, M10-owned head.** `PackagingCandidate` is a new member of the M8 `CandidatePayload` union
(kind `PACKAGING`) stored in `m8_candidate_revisions` through `ExplorationRepository.append_revision`. Selection is
an M10-owned `m10_packaging_heads` row, not an M8 promotion. *Rejected:* a standalone package revision store
(duplicates M8 CAS/replay, contradicts ADR-0080); targeting M8 promotion with a new `PromotionTargetKind`
(would route through Production Authority, which M10 must never call).

**D2 PACKAGING is refused by every M8 promotion path.** `PromotionTargetKind` is unchanged. `ExplorationPromotion`
and preview staging refuse `kind == PACKAGING` before any lock (`M10_PACKAGING_TARGET_FORBIDDEN`). Differential
tests prove CANVAS/SPATIAL/FORMAT bodies, digests and promotion behavior are unchanged.

**D3 Package quality rides the existing run.** No change to `AssessedSubject` or `QualityRun`. A new
`PackagingObservation` (observation type `PACKAGING`) joins the observation union and binds
`PackagingAssessedSubject` (base subject digest + candidate id/revision/payload digest + constraint snapshot
digest). A profile that governs packaging declares a requirement whose slot accepts `PACKAGING`. Selection
requires the current disposition's run to contain a PASS packaging observation for the **exact** candidate payload
digest. *Rejected:* a second package-scoped run type (doubles A5 closure logic and its migration).

**D4 Platform constraints are a policy amendment.** `QualityPolicyV2` = every V1 field plus
`platform_constraints: PlatformConstraintSnapshot` (`m10.platform-constraints.v1`: duration window, aspect/
dimensions, title/description/tag/hashtag limits, required/optional asset roles and media types, chapter rules,
locales). Profiles publish V2 through the accepted A3 Human publication path; the policy union is discriminated by
`schema_id`, so all V1 vectors and digests are unchanged. A changed constraint is a new profile revision.

**D5 Selection custody mirrors disposition.** `PackagingSelectionCustodianPort.authorize_selection` returns a
`PACKAGING_SELECTION` lease (≤30 s, DB-time admission) from the signed HUMAN_SHOWRUNNER grant, outside the
transaction; reuses the A6 custodian/attestor pattern and `require_actor` JWT binding. The agent cannot obtain it.

**D6 Export is a ZIP_STORED archive.** Sorted ASCII member paths, fixed 1980-01-01 timestamps, mode 0o100644,
no extra fields/comments/directories/symlinks, stdlib `zipfile` pinned by a golden vector. Layout:
`video/output.mp4`, `captions/<locale>.srt`, `thumbnails/thumbnail.<ext>`, `metadata/metadata.json` (canonical
JSON), `metadata/<locale>.json`, `manifest.json`. Content-addressed object under the project's private export
root; visible only after fsync + rename + full re-verification. Status `EXPORTED`, never uploaded/published.
*Rejected:* directory bundles (no single digest, harder atomic visibility).

**D7 Export execution through M7.** Export is a host-local M7 execution family (`m10.export-execution.v1`):
prepare (from current selection) → execute outside the metadata transaction → finalize after recomputing every
byte digest and every current binding. Lease/fencing generation guards the builder; crash at any cut either
reconciles a matching published object or rebuilds from the same verified closure.

**D8 F1 persistence.** New append-only `m10_quality_probe_failures` (execution id, error code, ResourceEvidence
JSON + digest, recorded_at) written in the same transaction that records the M7 FAILED_BEFORE_ACCEPTANCE attempt;
known failures only (ProbeFailed, ReferenceInvalid, OperationalEnvelopeExceeded) — ambiguous outcomes stay
ambiguous. Replay returns the stored evidence on the raised error.

## 3. Contracts and digest domains

Module `r2/contracts/packaging.py` (M10-B only). Shapes follow design §4.2 with these exact choices:

- `PackagingAsset{role, source_ref, content_digest, media_type, byte_size}` — requiredness comes only from the
  constraint snapshot; undeclared or duplicate roles, or missing required roles, fail.
- `PackagingCandidate{kind="PACKAGING", approved_master_id/digest, assessed_subject_digest, quality_profile_id/
  revision/digest, constraint_snapshot_digest, title, description, tags, hashtags, chapters, localization_variants,
  audience_classification, disclosure, assets, provenance}` where `provenance` records author kind
  (`HUMAN`|`AGENT`) and identity per field group; agent-authored text is allowed, never self-approving.
- `PackagingObservation` = `ObservationBase[PACKAGING]` + `packaging_subject`, `constraint_snapshot_digest`,
  `rule_results_digest`.
- `PackagePreview`, `PackageSelection`, `ExportManifest`, `ExportBundleReceipt` per §4.2.
- Domains: `m10.platform-constraints.v1`, `m10.packaging-candidate.v1`, `m10.packaging-subject.v1`,
  `m10.packaging-observation.v1`, `m10.package-preview.v1`, `m10.package-selection-request.v1`,
  `m10.package-selection.v1`, `m10.export-request.v1`, `m10.export-manifest.v1`, `m10.export-execution.v1`,
  `m10.quality-policy.v2`. Golden vectors frozen in B1; M10-A vectors re-verified unchanged.

## 4. Persistence, locks and replay

Tables (append-only unless noted): `m10_quality_probe_failures` (F1), `m10_package_previews`,
`m10_package_selections`, `m10_packaging_heads` (CAS head), `m10_export_jobs` (state + fencing generation),
`m10_export_receipts`; M10 command receipts reused. CHECK on `m8_candidate_revisions.kind` broadened to include
`'PACKAGING'`. One linear migration chain from `bed415be3608`; downgrade refuses when M10-B rows exist
(no silent history loss).

Selection lock order (extends ADR-0097 and the M10-A order): receipt replay → M10 command key → M8 candidate
head (FOR SHARE) → preview (FOR UPDATE) → master rows (sorted) → profile head → run head → disposition head →
packaging head → grant heads (sorted). Export finalize: command key → export job (fenced) → packaging head
(FOR SHARE) → disposition head (FOR SHARE). Absent heads are created under the command advisory key and a
unique constraint. Real PostgreSQL both-order tests with barriers and observed blocking; no sleeps.

Currentness: selection is exportable only while candidate head, master, profile head, run head, disposition
(unexpired, not superseded) and packaging head are exactly as bound; any drift → `M10_SUBJECT_STALE` /
`M10_DISPOSITION_STALE`; history is never rewritten.

## 5. Packaging checks (pure)

Run in the packaging observation, cheap-first: asset digest/size re-hash from verified private snapshots →
required roles/media types → duration window vs master facts → metadata lint (title/description length,
tag/hashtag count and charset, required topic term, banned phrases, chapter ordering/first-at-zero/min length) →
locale coverage. Ported Kalinga `seo_lint` and OpenMontage chapter formatting are reimplemented as pure functions;
the donors are executed only in parity tests from digest-checked pinned sources (A7 pattern).

## 6. Host surface and UI

Routes under `/projects/{project_name}/packaging`: append candidate revision, run packaging observation, preview,
select (Human custodian), request export, export status/history, download (scoped short-lived token, purpose
`m10-export`, server revalidates currentness under the guarded snapshot). Read DTOs separate historical status from
current `exportable` with typed refusal reasons. UI: a packaging panel in the existing V2 project workflow showing
findings, disposition state, selection and export; empty/partial/failed/stale/waived/superseded/invalidated states;
keyboard/focus/reduced-motion; axe-core; all locales in `frontend/src/i18n/`.

## 7. Pilots and utility evidence

Preregistered before running (frozen commit): corpora (one approved final per cohort), reviewer = sponsor as Human
showrunner (single reviewer; independence limit recorded), rubric, smallest useful effect (≥1 real defect caught
or confirmed none against a seeded-defect copy), resource envelope (bundle build ≤ 30 s, RSS ≤ 512 MiB).
Order: Western explainer → vertical factual Short → `zh-shuang`; each needs a published V2 profile, a Human
disposition and a Human selection. The agent prepares everything and stops at each Human gate.

## 8. Acceptance matrix

| Gate | Evidence |
|---|---|
| F1 | failure evidence persisted with the FAILED attempt; replay returns it; ambiguous outcomes carry none |
| Shared schema | M8 golden bodies/digests unchanged; PACKAGING refused by promotion/preview; CHECK migration round trip |
| Contracts | golden vectors, tamper, malformed, undeclared/duplicate/missing roles, no circular subject binding |
| Packaging checks | ported lint + duration window, defect fixtures, deterministic digests |
| Selection | Human-only lease, stale master/profile/run/disposition, preview expiry, head CAS, both lock orders, replay |
| Export | golden archive, two clean roots byte-identical, path/symlink/case-collision refusal, kill at every cut |
| Host regression | Gate C/D/export, M8 promotion, M10-A behavior unchanged |
| Donor parity | frozen baseline, OpenMontage + Kalinga same-fixture, PASS recomputed |
| UI | i18n consistency, states, axe-core |
| Pilots | three dossiers with Human decisions and preregistered metrics |
| Surface | no network/credential/upload; no Production Authority write |

## 9. Packets (one active at a time, each reviewed)

B0 F1 · B1 contracts + M8 evolution + policy V2 · B2 packaging observation · B3 preview/selection ·
B4 export + recovery · B5 routes + UI · B6 donor parity · B7 pilots (Human) · B8 seal M10-B.
M10-C is evidence-only and created only if acceptance cannot bind A and B directly.

## 10. Stop conditions

Any need to modify accepted M8 semantics beyond D1/D2, any network/credential surface, any agent path to a Human
lease, or a parity row that cannot reach PASS under the frozen criteria stops the packet for review.
