# R2-M8E: governed multi-format projection (execution plan)

**Parent plan:** [`2026-09-13-r2-m8e-multiformat-projection.md`](2026-09-13-r2-m8e-multiformat-projection.md).
**Spec:** [`2026-09-13-r2-m8-canvas-learning-multiformat-design.md`](../specs/2026-09-13-r2-m8-canvas-learning-multiformat-design.md), §3 invariant 8, §4, §10, §11 and §12 Gate E.
**Base:** `r2-v2/main` `52183f4b` (M8-D merged; evidence `R2_M8_D_LEARNING.json`).

## Current state (facts)

- **Contracts exist** in `r2/contracts/advanced_creative.py`:
  - `OutputProfile` and `OverlayConstraintSet`;
  - `ReframeDecision` and `FormatProjectionPlan` (source master id and digest, profile, overlay set, reframe decisions, plan digest);
  - `TechnicalValidationReport` and `SemanticParityReport` (rubric version, reviews, material disagreement);
  - `FormatCandidate` (plan digest, artifact ref and digest, both report ids and digests, execution id), which is already part of the M8-A `CandidatePayload` union.
- **There is no persistence, adapter, service, route or UI** for formats.
- **Source masters:** episode and shot masters are `MasterHeadSnapshot`s resolved by `MasterResolver.get_exact(artifact_key)`. For example, M3 promotes `ArtifactKey.episode_video`, and Gate C approves R2 shot masters.
- **The donor is pinned** in the M8 execution contract: OpenMontage `08e2151fa02de28a5d6a312b3d575692bf147ad7`. It is fetched to `~/.cache/r2-donors/openmontage`, and `HEAD` was verified.
  - `tools/video/video_compose.py` reframes with FFmpeg: `fit="pad"` gives `scale … force_original_aspect_ratio=decrease,pad` (letterbox), and `fit="cover"` gives `scale … increase,crop` (centre crop).
  - `tools/analysis/composition_validator.py` checks durations and missing media only.
  - The donor tests that cover these are `tests/qa/test_05_video_compose.py` and `tests/qa/test_08_end_to_end.py`.
- **The M8 execution contract (`packet_inputs.M8-E`)** lists a human decision: *"qualified blind semantic reviewer assignments"*. If it is missing, the outcome is `M8_REQUIRED_EVIDENCE_MISSING`. Only a person can supply this.
- **Migration id:** the parent plan names `8e8c4a0e0001`, which `add_spatial_pair_authority` already uses. M8-E uses `916c4a0e0001`.

## Decisions (agent-chosen under sponsor delegation)

1. **Profiles are versioned records.** `OutputProfile` and `OverlayConstraintSet` rows are immutable and keyed by `profile_ref` / `constraint_ref`, each with its digest.
   - A plan names exact refs. There is never a floating "latest".
   - A malformed profile fails closed: non-positive or odd dimensions, a fractional fps ≤ 0, an unknown codec or container, or a ratio that is not exactly 16:9, 9:16 or 1:1 for the three V1 surfaces.
2. **A projection plan binds one exact master.** It is built from a `MasterHeadSnapshot`: source master id and digest, the profile, the overlay set and the reframe decisions.
   - Its digest is canonical.
   - If the master head moves, the plan becomes stale.
   - Generating a different aspect independently is new candidate lineage, not a projection (parent plan).
3. **Reframe decisions are explicit.**
   - The kinds are `PAD` (letterbox, donor `pad`), `COVER_CENTER` (donor `cover`) and `COVER_FOCAL`. `COVER_FOCAL` is the R2 improvement: a crop window positioned on a declared focal span instead of the centre.
   - Each decision carries the source and target spans, its rationale and its `semantic_risk`.
   - `COVER_*` decisions that crop more than a threshold of the source area are marked `HIGH` risk.
4. **Rendering runs through M7.** The render adapter is a local FFmpeg execution recorded as an M7 `ExecutionAttempt`. The execution identity binds:
   - the source bytes digest;
   - the plan, profile, overlay and reframe digests;
   - the runtime: FFmpeg version, codec, fps, duration, and the adapter version.

   Re-running the same identity replays. The rendered artifact goes to the existing candidate media store with its digest.
5. **Technical validation uses ffprobe facts.** The checks are: dimensions, ratio, codec, fps, duration within tolerance of the source, audio stream presence matching the source, decodability (full decode with error count 0), and overlay collision.
   - Overlay collision tests the profile's UI regions against the declared focal and caption spans after reframing.
   - Every check is a row with an observed value and a verdict. The report is append-only and digest-bound to the plan and artifact.
6. **Semantic parity is a separate plane.**
   - At least two assigned blind reviewers compare the source master and the projection against rubric `format-semantic@1`: focal subject, action, shot intent, on-screen text, captions, timing and audio.
   - Reviewers see the two clips without plan or profile details.
   - `material_disagreement` is true when the reviewers disagree on any material item, and the report then fails.
   - **Reviewer assignments come from the sponsor and are a prerequisite of E3.**
7. **Promotion needs both planes.** A `FormatCandidate` revision is appended only with a passing technical report and a passing semantic report for the same plan and artifact digests.
   - M8-A promotion then applies unchanged: preview, authorization, receipt.
   - A stale master, plan, profile or report blocks promotion.

## Packets

- **E1, persistence (no reviewer needed):**
  - migration `916c4a0e0001`: `m8_format_profiles`, `m8_overlay_constraint_sets`, `m8_format_plans`, `m8_format_technical_reports`, `m8_format_semantic_reports`;
  - pure `r2/advanced_creative/formats.py`: validation, digests and the reframe geometry;
  - repository;
  - tests: malformed ratio, floating profile, changed master, overlay/reframe identity, append-only reports.
- **E2, donor parity and render adapter (no reviewer needed):**
  - a baseline manifest of the donor paths and hashes;
  - the donor tests run unmodified in an isolated environment;
  - same-fixture renders of all three ratios through the donor and through R2;
  - a differential harness (dimensions, ratio, duration, streams, decode errors, crop window);
  - the FFmpeg adapter through M7, with missing media/audio, cancel, codec/fps/duration and idempotency cases.
- **E3, review planes and UI. Needs the reviewer assignments:**
  - technical probes and overlay collision;
  - the blind review flow and the semantic report;
  - promotion blocking;
  - a format page;
  - real local renders, a browser check and `pnpm check`.
- **E4:** seal `R2_M8_E_FORMAT_PARITY.json`.

Each packet runs only its related tests, the static gates and an independent Codex review.

## Sponsor decision: reviewer assignment (2026-10-14)

The sponsor named a single blind semantic reviewer: the sponsor.

The spec asks for at least two independent blind reviews, so this is a recorded **deviation**:
- The semantic report records `reviewer_count = 1` and `deviation = "single_reviewer_by_sponsor_decision_2026-10-14"`.
- `material_disagreement` cannot arise with one review.
- The E4 evidence states the limit.

The service still accepts two or more reviewers whenever they are assigned.
