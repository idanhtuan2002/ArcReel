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

## Decisions taken during E2 and E3 research

8. **Renders are bounded M7 attempts** (revised after the E2 review and a research-first comparison).
   - Spec §6 says render work "is represented by M7 execution/candidate evidence", and §10 requires the M7 identity to bind the master, plan, profile, overlay, reframe, runtime settings and adapter.
   - M8-C already extended the M7 route inventory beyond paid video (`host-spatial-v1`), with an evidence table keyed to `execution_attempts`.
   - So a render now runs through `AttemptSubmitter`:
     - route `local-ffmpeg / format-projection / host-format-v1`;
     - capability profile `local-ffmpeg-format-projection@host-format-v1`, `OFFLINE_VERIFIED` against the parity report digest; `QUALIFIED` stays reserved for live verification under the registry policy;
     - a request payload carrying the plan digest, the source digest, the full argv, the FFmpeg build and the deterministic identity.
   - M7 owns the lifecycle: planned, submitting, failed before acceptance, outcome unknown, succeeded.
   - `m8_format_renders` is the evidence row written on success. It carries a foreign key to `execution_attempts`, the command, the plan, the source, the argv and the content-addressed output.
   - One render command is one M7 task. Re-sending it replays; a retry needs a new command.
   - An earlier draft kept a local state machine outside M7. It was withdrawn because it contradicted §6 and §10.
9. **Format slots and genesis.** A projection is promoted into its own M8 artifact slot, `m8-format:<sha256(source artifact key)[:16]>:<profile_ref>`, which is not a manifest key.
   - Options compared:
     - (a) a narrow contract amendment: a format slot's preview may bind "no master" at expected version 0;
     - (b) seeding the slot with a copy of the source master, which is semantically false;
     - (c) a first promotion outside preview and authorization, which violates spec §3.3.
   - (a) keeps every promotion bound to an exact compare-and-set state, since version 0 is the empty slot. The contract already allows null master fields, and every other slot stays replace-only. Chosen: (a).
   - The accepted M8-A preview and promotion only replace an existing master. They now also allow the first promotion into an empty slot, under all of these conditions:
     - the candidate is `FORMAT`;
     - the target is a format slot;
     - `expected_target_version` is 0;
     - the preview's `expected_master_id` and `expected_master_digest` are null (the contract already allows that).
   - Every other kind and slot keeps the replace-only rule.
10. **Format evidence gate.** Before a `FORMAT` preview or promotion, a format evidence port re-verifies:
    - the latest technical report and the latest semantic report for the candidate's plan and artifact both pass, and match the payload's report ids and digests;
    - the render execution succeeded for that plan and produced exactly that artifact digest;
    - the plan's source master is still the current head of its source artifact key.

    Any mismatch blocks with `M8_PROMOTION_BINDING_STALE`.
11. **Blind review.**
    - The reviewer opens a review packet holding the two clips, labelled A and B in an order the server draws and records. The packet shows no plan, profile or reframe detail.
    - The reviewer gives PASS or FAIL for each rubric item, plus a note.
    - Reviews come only from an interactive session. With a single reviewer, the report carries `SINGLE_REVIEWER_DEVIATION`.

## Decisions taken while fixing the fourth Codex review (at `4acbe8dd`)

12. **Reviewers are showrunner grant holders.** The reviewer principal (the JWT `sub`) must hold a current, checkpointed `HUMAN_SHOWRUNNER` grant for the project. Opening a packet, fetching a clip and submitting a review all require it.
    - Precedent: M8-B spatial review sessions gate review on the same grant reader. The grant is the signed, stored authority for the sponsor, issued in M8-C.
    - A self-assigned assignment table would add an authority that nothing signs, so it was rejected.
    - The packet and every review record the grant event digest. `validate_semantic_report` refuses a review without one, so the single-reviewer deviation is bound to that authorized principal.
    - Until grants are activated on a server, review returns 503. A reviewer without a grant gets 403.
13. **Neutral review copies.** At packet open, both clips are stream-copied from verified snapshots into per-packet copies:
    - container metadata and chapters are stripped;
    - each copy gets a random tag and a random name;
    - clips are served from a verified snapshot without ETag, Last-Modified or a file name.

    So no clip matches a recorded digest or name. What blindness cannot hide is that the projection has the target's shape; the evidence states this limit.
14. **Evidence and reviews are serialized per plan.** One PostgreSQL advisory lock per plan covers both report streams.
    - It is taken by report writers, by review submission (before the duplicate check and the aggregation) and by the format evidence gate.
    - The gate also locks the source artifact's authority row.
    - So a promotion commits only with the reports and source head that are current at its commit.
15. **Renders: lease and recovery.**
    - The M7 lease of a render attempt is `RENDER_TIMEOUT_SECONDS + 300`, so the recovery scanner never reclaims an attempt whose bounded FFmpeg run may still be going.
    - An attempt that is `ACCEPTED` without recorded success evidence (the process died in between) is completed when the same command is sent again. Its digest comes from the job id `<execution>:<digest>`, and the content-addressed file must still hold those bytes.
    - A fence lost to another writer is reported as a render failure.
16. **Media I/O stays outside transactions and reads snapshots.**
    - Plan creation, validation, review packets, clip delivery and candidate preparation measure, serve or register private snapshots whose bytes were hashed as they were copied.
    - Database work runs in short transactions that re-read the inputs.
    - A missing media file is `m8_format_media_missing` (409).
17. **Overlay analysis uses pixel geometry.** Collisions are computed on the even-pixel crop and placement that FFmpeg applies, not on the ideal spans.
18. **Parity row F07 (missing source) is measured per dimension.** Each of the eight dimensions has its own measurement, taken over `RUNS` refusals on each side:
    - refusal;
    - no success;
    - stable reasons;
    - no outputs left;
    - an unchanged work directory;
    - a reason that names the missing file;
    - refusal time at most 2 s;
    - zero bytes written.
