# R2 M10 V2 reuse inventory: quality evidence and packaging

## Scope and evidence boundary

- Release worktree: `/home/anhtuan/content-production-os/.worktrees/r2-m10-v2`.
- Exact base: `4bd70525dc2a4e5a0e05c57381a90a35301ec169` (`r2-v2.0.5`).
- This is a factual inventory of implementation seams and test fixtures, not an
  architecture decision, acceptance result, or implementation plan.
- The release worktree is not indexed. The available codebase-memory project
  `r2-v2-main` is an older index (`2026-10-15T01:19:44Z`) and was used only for
  provisional symbol discovery. All material claims below were checked against
  the pinned release source with numbered reads.
- Graph coverage for source modules had no recorded gap in the older index, but
  `server/services/format_candidate.py` was metadata-changed. Integration tests,
  fixtures, and `docs/` were excluded from that index; their claims therefore
  come from direct release checkout reads. No provider, network, credential, or
  test execution was performed for this inventory.

## Implemented reusable seams

### 1. Typed quality-result and approved-master contracts

`r2/contracts/results.py:11-34` implements `GenerationCandidate`, including
`quality_report_ref`, lifecycle/selection constraints, and a validator that
rejects `FAILED + SELECTED` and any selected non-`GENERATED` candidate.
`r2/contracts/results.py:37-68` implements `ApprovedMaster`, `QualityFinding`,
and `QualityReport`. A report carries `target_ref`, named `checks`, bounded
`score`, separate blocking/advisory findings, `reviewer_type`, and
`created_at`; the validator enforces the two finding planes. These are data
contracts only: they do not run probes, choose an approved master, issue a
quality disposition, or package an export.

`r2/production/artifact_metadata.py:21-48` provides the reusable metadata
shape: `ApprovedMasterMetadata` and `R2ArtifactMetadata` bind selected
candidate/version/approval data, content basis, direct dependency snapshots,
and a content fingerprint. `normalize_dependencies()` rejects conflicting
duplicate refs and emits deterministic ref ordering. This is integrity/lineage
metadata, not an M10 quality authority.

### 2. Candidate-object publication and media-probe verification

`lib/candidate_store.py:153-280` exposes the precise call seam
`prepare_candidate(identity, source_file, final_path, media_root, media_probe,
quarantine_root=None) -> VerifiedCandidateObject`. It copies and fsyncs bytes,
checks the expected SHA-256, checks same-filesystem publication, calls the
caller-supplied `media_probe` on the temporary bytes, then publishes by hard
link under an anchored directory. Digest/probe failures are quarantined; path
and symlink escape, cross-mount, duplicate unequal bytes, and parent replacement
are rejected. A pre-existing same-digest object is an idempotent replay via
`_read_existing_candidate()` (`:105-141`).

`lib/candidate_store.py:288-308` exposes
`verify_candidate(object_ref, expected, media_probe) -> bool`, rechecking file
existence, byte size, SHA-256, and the probe digest. It deliberately returns
`False` for ordinary mismatch/probe exceptions so a caller retains authority to
quarantine or refuse promotion. The store does not define what a probe digest
means or whether a result is quality PASS.

Exact fixtures in `tests/unit/lib/test_candidate_store.py`:

- `test_prepare_candidate_verifies_and_publishes_into_place` (`:55-75`) proves
  expected bytes, size, content digest, object ref, probe digest, and no temp
  residue.
- `test_prepare_candidate_rejects_digest_mismatch_and_quarantines` (`:78-99`)
  and `test_prepare_candidate_rejects_media_probe_failure_and_quarantines`
  (`:101-115`) prove failure quarantine.
- `test_prepare_candidate_preserves_destination_created_after_precheck`
  (`:214-235`) and `test_prepare_candidate_is_idempotent_after_kill_following_publication`
  (`:336-362`) cover competing-writer preservation and crash-after-publication
  replay.
- `test_verify_candidate_detects_on_disk_corruption` (`:364-380`) covers
  post-publication corruption detection.

### 3. Deterministic FFmpeg/ffprobe render and technical validation

`server/services/format_render.py:103-120` implements `verified_snapshot()`: it
copies and hashes a file before any later read and raises on missing or changed
bytes. `:134-146` provides the bounded `run_process()` subprocess seam with
cancellation kill behavior. `:149-170` provides `probe_source()` (video
dimensions/audio) and `ffmpeg_version()`. `FormatRenderService.render()`
(`:225-343`) binds a render to a plan and source-master digest, probes a private
source snapshot, builds the FFmpeg request, records M7 execution evidence, and
stores output content-addressed. Reusing this seam preserves the existing
authority boundary: render execution records evidence; it does not issue a
quality disposition or approve a package.

Exact render fixtures in `tests/integration/server/services/test_format_render.py`:

- `test_a_render_is_a_succeeded_m7_attempt_with_evidence_and_replays`
  (`:71-106`) proves output dimensions, SUCCEEDED attempt, stored execution
  evidence, and same-command replay.
- `test_only_the_bound_master_bytes_render` (`:109-118`) rejects a source whose
  bytes do not match the plan's master digest before an attempt is created.
- `test_a_failed_render_is_an_m7_failure_and_a_new_command_retries`
  (`:121-145`), `test_a_lost_output_needs_a_new_command_which_repairs_the_store`
  (`:147-167`), and `test_a_crash_after_acceptance_is_completed_by_resending_the_command`
  (`:207-220`) cover failure, missing output, and accepted-but-unrecorded
  recovery paths.

`server/services/format_validation.py:29-65` provides typed `MediaFacts`,
`media_facts()`, and `decode_errors()`. `FormatValidationService.validate()`
(`:77-144`) measures verified artifact/source snapshots with ffprobe and a full
FFmpeg decode, then checks dimensions, ratio, codec, FPS, duration tolerance,
audio codec, decode errors, and overlay collisions. It appends a deterministic
`TechnicalValidationReport` through `FormatRepository`; it is a technical
observation/reporting seam, not human semantic adjudication.

Exact validation fixtures in `tests/integration/server/services/test_format_validation.py`:

- `test_a_clean_render_passes_every_measured_check` (`:70-89`) asserts clean
  dimensions/ratio/FPS/audio/decode and report/artifact binding.
- `test_a_ui_region_over_the_subject_fails_the_overlay_check` (`:91-104`)
  proves a localized overlay failure while dimensions still pass.
- `test_a_changed_artifact_or_another_source_is_refused` (`:106-127`) covers
  source mismatch, missing source, and artifact tampering.
- `test_checks_measure_the_verified_snapshot_even_if_the_file_is_replaced_meanwhile`
  (`:129-145`) proves measurements use the verified snapshot despite a later
  replacement.

### 4. Evidence-bound candidate preparation and packaging-adjacent export

`server/services/format_evidence.py:28-81` implements `HostFormatEvidence.verify()`.
It checks render/artifact digest, plan digest and validity, target slot, locks
the source authority and report stream, requires latest passing technical and
semantic reports with matching report IDs/digests, and rechecks the current
source master. This is the closest existing evidence-to-candidate boundary.

`server/services/format_candidate.py:83-103` (`_verified_evidence`) and
`:106-159` (`prepare_format_candidate`) reuse that verification, then call
`prepare_candidate()` with a `CandidateIdentity` whose expected digest is the
render artifact digest. The final transaction re-reads evidence under locks
before appending the immutable candidate revision (the continuation at
`:160-220` performs repository append/lineage work). This can supply M10's
candidate-object mechanics, but its current target is an M8 FORMAT slot and
its evidence model is technical + semantic reports, not M10's planned typed
multi-assessor `QualityRun`/`QualityDisposition`.

Exact projection fixtures in `tests/integration/server/services/test_format_projection_flow.py`:

- `test_a_reviewed_projection_becomes_the_first_master_of_its_format_slot`
  (`:204-224`) proves reviewed evidence can become a first format-slot master.
- `test_a_moved_source_master_blocks_the_projection` (`:227-240`) and
  `test_without_passing_reports_there_is_no_candidate` (`:242-255`) prove
  stale-source and incomplete-report refusal.
- `test_a_report_appended_after_the_preview_supersedes_the_evidence`
  (`:257-270`), `test_a_promotion_waits_for_a_concurrent_report_writer_and_sees_its_report`
  (`:272-293`), and `test_two_projections_racing_for_a_new_format_slot_promote_exactly_one`
  (`:296-320`) cover evidence supersession, PostgreSQL report-lock ordering,
  and CAS-style single-winner promotion.

`r2/m3/deliverables.py:62-90` (`ApprovedMasterResolver`) resolves a current
`master:<shot_ref>` only when the approved metadata, current file, selected
candidate/version, and file SHA-256 all agree. `:121-171` provides
`audio_peak_db()`/`audio_decision_holds()` via ffprobe/ffmpeg `volumedetect`.
`write_export_copy()` (`:185-214`) verifies approved bytes, atomically copies
to `output/`, fsyncs, and rehashes. `Deliverable.exportable` (`:217-235`)
requires current currency and equal approved/current/export digests. These are
strong reuse seams for export integrity, but they package a current approved
final rather than an M10 `PackagingCandidate` revision.

Exact export fixtures in `tests/unit/r2/m3/test_deliverables.py` include
`test_replacing_both_final_and_export_cannot_authorize_new_bytes` (`:61-71`),
`test_token_listing_only_includes_exportable_deliverables` (`:73-80`),
`test_export_copy_rejects_a_changed_promoted_final` (`:95-100`), and
`test_download_uses_the_bytes_verified_before_path_replacement` (`:134-145`).

## Media fixture reuse and concrete gaps

`tests/fixtures/r2/m3_media_assertions.py:15-41` provides the reusable
`frame_pixel_stddev(video_path, tmp_path, frame_index=30)` helper: FFmpeg
extracts a frame, Pillow decodes it, and NumPy computes grayscale pixel
standard deviation. It is a content-bearing-vs-solid-color assertion, not a
general quality score. `tests/integration/r2/m3/test_golden_a_real_media_closure.py:86-137`
uses it on each shot, alongside ffprobe video-stream and duration/hash checks,
with fixture `r2/m3/fixtures/golden_a_h264.json` and reused asset
`r2/m3/fixtures/assets/reused_terminal_frame.svg` (`:26-29`).

In the bounded inspected source and an exact-name search over `r2/`, `lib/`
and `server/` at this release SHA, the M10 names called out by ADR-0080 were
not found: no versioned `QualityProfile`, typed multi-assessor
`QualityRun`, `QualityDispositionAuthority`, immutable `PackagingCandidate`,
or deterministic M10 package-bundle exporter. The exact-name search found `QualityReport` in the
generic contract above, and the existing format path is M8-specific. No M10
quality/packaging spec or plan is present in the release tree; ADR-0080 is a
design boundary, not implementation. Therefore the concrete reuse gap is an
M10-owned layer that composes existing verified bytes/probes/reports and
candidate/export primitives while introducing M10-owned versioned quality
evidence, human disposition, package revision identity, and package-scope
binding. This inventory does not choose that design or claim acceptance.

## Authority boundaries to preserve

ADR-0080 states that M10 owns versioned quality evidence, authority-issued
disposition, immutable packaging revisions, and deterministic export bundles
(`docs/adr/0080-post-m8-north-star-closed-loop.md:42-47`). It separately defines
the Quality Probe seam as typed evidence that does not decide Final Cut
(`:80-86`), keeps Human `QualityDispositionAuthority` separate from probe/model
adapters (`:101-110`), and allows FFmpeg/ffprobe as deterministic probe
adapters while VMAF remains observation-only (`:181-196`). Existing seams above
are compatible with those boundaries only when their reports/probes remain
observations and approval/disposition/package selection remains an explicit
authority operation.

## Main-agent validation after inventory

The main agent ran the existing export and candidate-store suites at the pinned
release: 12 and 16 tests passed respectively, with no skips/failures/errors.
These are existing-seam baseline results, not M10 qualification. See the
[start research](2026-10-23-r2-m10-v2-start.md) for exact evidence and limits.
