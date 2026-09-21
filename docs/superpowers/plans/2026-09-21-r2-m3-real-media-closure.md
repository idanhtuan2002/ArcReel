# R2 M3 Real-Media Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close F1 (M3's own unmet product exit gate) by replacing the
solid-color rendering stub with a real Remotion-backed render, and prove it
against both V1 corpus products (ADR-0089 P0 item 4).

**Architecture:** A thin, R2-owned Python module shells out to
`npx remotion render` against the vendored `remotion-composer/` TypeScript
project, exactly mirroring the existing `ffmpeg` subprocess pattern in
`composition.py`. A pure shot-to-cut projection turns a `ShotSpec`/
`ShotSpecV2` plus its method-specific content (a bound source file, a real
`Claim.statement`, or a real `ScreenplayScene.dramatic_text`) into one
`RenderCut`. `GoldenAComposer` (already real) needs no change.

**Tech Stack:** Python/subprocess, Remotion 4.x (Node.js, already vendored
and version-pinned via the donor clone), FFmpeg/ffprobe, pytest.

**Spec:** `docs/superpowers/specs/2026-09-21-r2-m3-real-media-closure-design.md`

## Global Constraints

- Start only from the accepted M7-D head (`content-production-os-m7`,
  `feat/r2-m7-host-production-hardening`, HEAD `05314871`). No M7 code is
  touched by this plan; it only touches `r2/m3/`, a new `r2/render/` (or
  similar) module, and the vendored `remotion-composer/` copy.
- No paid provider call anywhere in this plan (§1 of the spec). Every
  `external_provider_cost` this plan produces is `Decimal("0")`.
- Vendor only `remotion-composer/` (the TypeScript project). Do not import
  `tools/video/video_compose.py` or `tools/base_tool.py`.
- Real render output only: no test may assert against a placeholder/solid
  color as if it were the real acceptance bar. Every render-producing test
  must probe the actual output (`ffprobe` for stream shape/duration, a frame
  extraction + visual/pixel check for on-screen text where the test claims
  text is visible).
- Stop after Task 5's evidence for Codex review, per the M7-A..D precedent
  (self-review with human override, honestly disclosed, if Codex is
  unavailable).

---

### Task 1: Vendor `remotion-composer/` and prove baseline render

**Files:** `vendor/openmontage/remotion-composer/` (new vendored copy),
`docs/r2/evidence/R2_M3_DONOR_BASELINE.json` (new, mirrors M6's
`R2_M6_DONOR_BASELINE.json` shape), a hash-check runner script mirroring
`take_shot_vocabulary_runner.mjs`'s pattern.

**Interfaces:** `verify_remotion_composer_baseline() -> None` (fails closed
if the vendored copy's file hashes drift from the pinned commit's tree).

- [ ] Copy `~/content-os-r1-8/work/OpenMontage/remotion-composer/` into
  `vendor/openmontage/remotion-composer/` verbatim (no edits to vendored
  `.tsx`/`.ts` source --- any R2-side adaptation happens in the calling
  Python module, not by forking the donor's TypeScript).
- [ ] Record `R2_M3_DONOR_BASELINE.json`: donor URL, pinned commit
  `08e2151fa02de28a5d6a312b3d575692bf147ad7`, list of vendored files with
  their SHA-256, mirroring `R2_M6_DONOR_BASELINE.json`'s exact shape.
- [ ] Write a hash-check script/test that fails if any vendored file's
  content drifts from the recorded baseline (same purpose as the Take/Huohuo
  hash-check runners in M6).
- [ ] `npm install` inside the vendored copy (commit `package-lock.json`, not
  `node_modules/`); confirm `npx remotion render` on the vendored copy
  reproduces this session's own zero-key smoke test (empty `cuts` still
  renders 120 real frames at 1920x1080).
- [ ] Run focused tests; expected RED is the vendored directory or baseline
  file not existing yet.
- [ ] Run tests; expected GREEN is the hash check passing and a real render
  succeeding from the vendored (not the donor's original) path.
- [ ] Commit `feat(r2): vendor remotion-composer as the M3 render engine`.

### Task 2: `RenderPlan`/`RenderCut` contracts and the shot-to-cut projection

**Files:** `r2/m3/render_plan.py` (new), `r2/m3/render_projection.py` (new),
unit tests for both.

**Interfaces:** `RenderCut`, `RenderPlan`, `RenderedCutAsset` dataclasses
(spec §4); `project_shot_to_cut(shot, *, method, bound_source, display_text) -> RenderCut`
(spec §5).

- [ ] Write failures for: `REUSE` with no `bound_source` raises; `DETERMINISTIC`
  with no `display_text` raises; every out-of-scope method
  (`STOCK`/`SCREEN_CAPTURE`/`GENERATED_IMAGE`/`GENERATED_VIDEO`) raises
  `NotImplementedError` explicitly (never silently falls through to a
  placeholder); a `REUSE` cut's `source_path` is exactly the resolved
  binding path; a `DETERMINISTIC` cut's `text` is exactly `display_text`.
- [ ] Run focused tests; expected RED is `project_shot_to_cut` not existing.
- [ ] Implement `RenderCut`/`RenderPlan`/`RenderedCutAsset` (spec §4, field-
  for-field) and `project_shot_to_cut` (spec §5).
- [ ] Run tests; expected GREEN.
- [ ] Commit `feat(r2): add RenderPlan contracts and the shot-to-cut projection`.

### Task 3: The real render engine, replacing the color stub

**Files:** `r2/m3/remotion_engine.py` (new: the `npx remotion render`
subprocess wrapper), `r2/m3/local_production.py` (edit: replace the
`ffmpeg -f lavfi color=...` branch with a call into the new engine),
integration tests.

**Interfaces:** `render_cut(cut: RenderCut, *, remotion_project: Path, output_path: Path) -> RenderedCutAsset`.

- [ ] Write failures for: a `video_passthrough` cut whose `source_path` does
  not exist raises before any subprocess call; a `text_card` cut with real
  text produces a file whose extracted frame actually contains that text
  (pixel/OCR-free check: assert the frame is not solid-color, i.e. has more
  than N distinct pixel colors, as a cheap proxy proving real content
  rendered --- mirrors this session's own visual verification, made
  machine-checkable); `wall_time_seconds`/`tool_version` are populated from
  the real subprocess run, not hardcoded; `external_provider_cost` is always
  `Decimal("0")`.
- [ ] Run focused tests; expected RED is `render_cut` not existing and
  `local_production.py` still generating solid color.
- [ ] Implement `render_cut` (builds one single-cut `RenderPlan`, invokes
  `npx remotion render` against the vendored project, `ffprobe`s the result
  exactly as `local_production.py`/`composition.py` already do for
  duration). Replace `GoldenALocalProducer.produce`'s color-generation branch
  with a call to `render_cut`, keeping its existing `LocalProducedAsset`
  return shape (or migrating callers to `RenderedCutAsset` --- implementer's
  call, document the choice).
- [ ] Run tests; expected GREEN. Also re-run the existing Golden A test suite
  (`tests/integration/r2/m3/test_golden_a_*.py`) unchanged --- if any test
  asserted on the *old* solid-color behavior specifically (as opposed to
  just "a valid video exists"), that assertion is now wrong and must be
  fixed to check real content instead, not relaxed to keep the placeholder
  passing.
- [ ] Commit `feat(r2): replace the M3 solid-color render stub with real Remotion output`.

### Task 4: New factual topic and fixture

**Files:** `r2/m3/fixtures/golden_a_<topic>.json` (new), a topic-content
authoring pass (`ResearchPack`/`ClaimLedger`/`ScriptArtifact` matching
`load_golden_a_factual_bundle`'s existing validation contract, unchanged).

**Interfaces:** none new --- reuses `load_golden_a_factual_bundle` as-is.

- [ ] Confirm the topic choice with the user (spec §6.1 proposes "how video
  encoding/compression works"; any equally simple, verifiable,
  non-sensitive topic is an equally valid substitute).
- [ ] Author the fixture bundle: 3-5 sources/evidence records, a
  `ClaimLedger` with 2+ `VERIFIED` claims (real, checkable statements about
  the chosen topic), a `ScriptArtifact` referencing them, matching every
  validation `load_golden_a_factual_bundle` already enforces.
- [ ] Run `load_golden_a_factual_bundle` against the new fixture; expected
  GREEN (structural validation only, no render yet).
- [ ] Commit `feat(r2): add a second Golden A factual topic fixture`.

### Task 5: End-to-end real render for both corpus products + evidence

**Files:** `tests/integration/r2/m3/test_golden_a_real_media_closure.py` (new
factual-product end-to-end test), `tests/integration/r2/m6/test_golden_b_real_render.py`
(new narrative-product end-to-end test, first real render of Golden B ever),
`docs/r2/evidence/R2_M3_REAL_MEDIA_CLOSURE.json` (new).

**Interfaces:** none new --- exercises Tasks 1-4's surfaces end to end.

- [ ] Factual product: run the new fixture (Task 4) through the full chain
  --- `load_golden_a_factual_bundle` → shots/methods (existing
  `GoldenAProductionPreparation`) → `project_shot_to_cut` (Task 2) →
  `render_cut` (Task 3) → `GoldenAComposer.compose` (unchanged) → one final
  `ApprovedMaster`-bound video. Verify via `ffprobe` (valid, expected
  duration within the V1 bar's 60-180s) and frame extraction (each
  `DETERMINISTIC` shot's extracted frame is not solid-color and, ideally,
  contains the exact claim text --- OCR is out of scope; a pixel-diversity
  check plus one manual visual spot-check recorded in the evidence file is
  sufficient).
- [ ] Narrative product: take Golden B's existing admitted-screenplay flow
  (both Western-generic and CN-Shuangwen profile variants,
  `tests/fixtures/r2/m6_dual_profile_corpus.py`, unchanged) through
  `TakeDirectorAdapter.direct()` (unchanged) → `project_shot_to_cut` (Task 2,
  resolving `display_text` from the matching `ScreenplayScene.dramatic_text`)
  → `render_cut` (Task 3) → `GoldenAComposer.compose` (unchanged, proving it
  is genuinely milestone-agnostic). Verify the same way; additionally spot-
  check the CN-Shuangwen variant's Chinese text renders without mojibake
  (this session verified Vietnamese; CJK is untested until this task).
- [ ] Run the full method-diversity check: for at least one product, confirm
  `REUSE`, `DETERMINISTIC`, and `COMPOSITE` each produced visibly distinct
  (non-identical-hash, non-solid-color) output --- the literal "at least
  three production methods" proof.
- [ ] Run the complete gate suite from `CONTRIBUTING.md` at the exact HEAD:
  ruff/format/basedpyright/lint-imports/deptry, full pytest (SQLite and
  postgres-compat selections), `audit_tests.py --check`, frontend/website
  checks only if this plan touched `frontend/`/`website/` (it does not,
  confirm via `git diff --stat`).
- [ ] Write `docs/r2/evidence/R2_M3_REAL_MEDIA_CLOSURE.json`, mirroring the
  M7-A..D evidence shape: `status: "REAL_MEDIA_CLOSED"` or `REJECTED` with
  exact stop codes, the verification-matrix results (spec §9), the
  R2-DEC-031 evidence chain (spec §8), the audio decision (spec §7,
  `audio_decision: "explicit_mute"`), gate results, and coverage_limitations
  (explicitly naming: no real narration audio, no paid-provider methods, no
  new narrative content authored).
- [ ] Commit `docs(r2): record M3 real-media closure` and stop for Codex
  review (or self-review with explicit human-override disclosure, per the
  M7-A..D precedent, if Codex is unavailable) --- no push/merge/tag follows
  without separate explicit human approval.
