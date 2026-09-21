# R2 M3 Real-Media Closure Research

**Purpose:** ADR-0089 P0 item 4 requires closing "the M3 real-media product gap
using the two V1 corpus products" before a V1 release candidate can exist.
This document establishes, from primary sources (code, prior research, a real
render executed this session), what the gap actually is, what closing it
requires, and what remains genuinely unknown -- before any spec or plan is
written.

## 1. What the gap actually is (fact, verified in code this session)

M3's own frozen exit gate (`docs/r2/R2_06_FROZEN_IMPLEMENTATION_ROADMAP.md`,
R2-M3 section) is:

```text
Exit:
- one real factual/general-content artifact end-to-end;
- at least three production methods;
- claim lineage visible;
- cost/provenance captured.
```

The frozen roadmap's own intended flow for M3 already names the fix:

```text
ResearchPack → ClaimLedger → ScriptArtifact → OpenMontageDirector
→ SceneSpec / ShotSpec → Production Preparation → ArcReel
→ ApprovedMaster → Remotion/FFmpeg → final output
```

**`OpenMontageDirector` and `Remotion/FFmpeg` were never built.** Instead,
`r2/m3/local_production.py::GoldenALocalProducer.produce` (read in full this
session) does this for every shot, regardless of its labeled
`ProductionMethod`:

- for `REUSE`: reads the real bound source file and computes its SHA-256
  (`local_production.py:66-69`), but **never passes that file to ffmpeg as
  visual input** -- the hash is used only as one input to a seed for picking a
  color from a 5-color palette (`local_production.py:73-78`);
- for every method: generates the shot's entire video via
  `ffmpeg -f lavfi -i color=c={color}:s=1280x720:...` (`local_production.py:108-125`)
  -- a solid-color test pattern, with no real pixel content from any source
  asset, script, or claim.

`r2/m3/composition.py::GoldenAComposer.compose` (the `COMPOSITE` method, final
assembly) is genuinely real: it concatenates the per-shot files produced above
via `ffmpeg -f concat ... -c copy` and probes real duration. It has no defect
of its own -- its output is only as real as the solid-color shots it
concatenates.

`r2/m3/preparation.py::GoldenAProductionPreparation.prepare` hardcodes exactly
two per-shot methods (`shot.id == "SH01"` gets `REUSE`, everything else gets
`DETERMINISTIC`), plus `COMPOSITE` for final assembly. So today's Golden A
fixture demonstrates 3 method *labels*, not 3 methods with distinguishable
real output -- matching the 2026-09-09 status review's own finding verbatim
("3 method mới ở mức nhãn metadata, video là nền màu",
`docs/r2/evidence/PROJECT_STATUS_REVIEW_2026-09-09.md` F1).

**"Claim lineage visible" is currently a data-structure claim, not a visual
one**: `Claim.statement` (`r2/contracts/factual.py`) is real, linked lineage
exists in the DB/objects (`golden_a.py::GoldenARunner._lineage`), but no
claim's text is ever rendered on screen -- a viewer watching the output sees
only a solid color.

## 2. Prior research already done (do not repeat)

`docs/research/2026-09-07-r2-reuse-map-and-completion-gates.md` already
investigated OpenMontage as the donor for this exact gap:

- OpenMontage local pin `08e2151fa02de28a5d6a312b3d575692bf147ad7`, donor
  `github.com/calesthio/OpenMontage`. Ran 3 of its own contract test files:
  56 passed, exit 0 (`docs/r2/evidence/reuse-map-2026-09-07/openmontage-probe.log`).
- Recommendation recorded then: "chuẩn bị acceptance fixture Golden A có nội
  dung thật, tận dụng OpenMontage composition; không nhảy qua milestone để
  đưa renderer mới vào runtime ngay" (prepare a Golden A fixture with real
  content, leveraging OpenMontage composition; do not skip a milestone to put
  a new renderer straight into the runtime).

A separate, earlier evaluation (`R1_02_OPENMONTAGE_REALITY_CHECK.md`, dated
2026-09-06, found under `~/Bản tải về/content_production_os_r1_evidence_2026-09-06/`)
did a deeper capability assessment:

- Explicit conclusion: **OpenMontage should not replace ArcReel as the host
  runtime** (no Python orchestrator by its own architecture) -- it is a donor
  for content intelligence, tooling, and composition, not a runtime.
- "Remotion-first composition" rated `IMPLEMENTED_VERIFIED_SOURCE`, "primary
  deterministic composition candidate", status `PROVISIONAL → STRONGLY SUPPORTED`.
- Its own listed next validation step #3 was **"Run zero-key Remotion
  explainer"** -- explicitly not yet done as of that research
  ("chưa chạy render Remotion lần này").

**R2-DEC-031** (`docs/r2/R2_04_DECISION_REGISTRY.json`, status `LOCKED`) is a
*general* donor-reuse governance decision (any vendored/ported/adapted donor
surface needs a baseline/coverage/parity/completion evidence chain) -- it is
not specific to OpenMontage. The 2026-09-09 status review frames applying
OpenMontage as "the first R2-DEC-031 case," i.e. proposing to apply this
general framework here, not inventing a new architecture direction (the
architecture direction -- `OpenMontageDirector` + `Remotion/FFmpeg` -- was
already fixed in the frozen roadmap before any of this research existed).

**The donor clone already exists on disk**, matching the exact pinned commit:
`~/content-os-r1-8/work/OpenMontage` at `08e2151fa02de28a5d6a312b3d575692bf147ad7`
(verified via `git log -1` this session) -- same reuse pattern as M6's
`~/content-os-r1-8/work/take` / `~/content-os-r1-8/work/huohuo-drama`. No
re-cloning needed.

## 3. New finding this session: the zero-key render feasibility gap is closed

Ran the exact validation step prior research had flagged as not yet done:

```bash
cd ~/content-os-r1-8/work/OpenMontage/remotion-composer
npm install   # 201 packages, 5s, clean (3 audit warnings, none blocking)
npx remotion render src/index.tsx Explainer /tmp/openmontage-smoke-test.mp4 \
  --props='{"cuts":[{"in_seconds":0,"out_seconds":3}],"overlays":[],"captions":[],"audio":{}}'
```

Result: a real render, 120 frames at 30fps/1920x1080, completed in seconds,
producing a genuinely valid file (verified via `ffprobe`: h264/aac,
1920x1080, 4.053s, 303,675 bytes). **No API key, no network call, no paid
provider was used or required.** Node v22.22.1 / npm are already present on
this machine.

This is a real, fact-grounded confirmation -- not an inference -- that the
`Explainer` Remotion composition renders correctly on this machine today,
closing the single biggest open feasibility question from all prior research.

**Vietnamese-text rendering also confirmed this session** (the other concern
`R1_02_OPENMONTAGE_REALITY_CHECK.md` explicitly flagged as untested): a
`Cut` with `type: "text"` and a Vietnamese sentence full of diacritics
("Việt Nam: Đây là một câu tiếng Việt có dấu, kiểm tra font.") rendered
correctly and legibly (verified by extracting and visually inspecting frame
60 of the output) -- Space Grotesk (the font `Explainer.tsx` loads via
`@remotion/google-fonts`) renders Vietnamese diacritics with no mojibake or
missing glyphs, fully offline.

## 4. The `Explainer` composition's real prop model (fact, read from source)

`remotion-composer/src/Explainer.tsx` (923 lines), registered in `Root.tsx`
with `defaultProps={cuts: [], overlays: [], captions: [], audio: {}}`:

- **`Cut`** (`Explainer.tsx:190-271`): one timed segment. Carries
  `in_seconds`/`out_seconds`, an optional `source` (video/image path -- real
  asset playback, not a stub) with `source_in_seconds` for trimming, and a
  `type` discriminator selecting which sub-component renders it: plain video
  passthrough, `text`/`stat`/`callout`/`comparison` cards (real text
  content), bar/line/pie charts, a progress bar, `anime_scene`,
  `terminal_scene`, or `screenshot_scene`. Background can be an image, a
  video, or a flat color.
- **`Overlay`** (`Explainer.tsx:273-285`): `section_title`/`stat_reveal`/
  `hero_title`/`provider_chip`, time-ranged, layered over cuts.
- **`AudioConfig`** (`Explainer.tsx:287-303`): separate narration and music
  layers with fade/offset/loop controls.

This maps cleanly onto R2's existing contracts without inventing new ones:
a `ShotSpec` (`r2/contracts/production.py`) naturally becomes one `Cut`
(`framing`/`camera`/`purpose` inform which `Cut.type` and text to use); a
`REUSE`-method shot's bound source file becomes `Cut.source` (real playback,
finally); a `DETERMINISTIC`-method shot renders the linked `Claim.statement`
(`r2/contracts/factual.py`) as a `Cut.type: "text"` or `"stat"` card, making
claim lineage visible on screen, not just in data.

`tools/video/video_compose.py` (donor's own Python orchestration layer, now
read in full: 2,944 lines) routes `edit_decisions.render_runtime` to
`npx remotion render` for the `remotion` runtime, `ffmpeg` for simple
concat/trim (comparable to today's `GoldenAComposer`), and a `hyperframes`
runtime not relevant here -- plus atelier/bespoke rendering, subtitle
burning, overlay, encoding, and an automated final-review pass that compares
a rendered transcript back to the source script. Its only imports beyond the
stdlib are its own sibling `tools.base_tool` (480 lines, itself stdlib-only,
no donor persistence/config/provider-selector entanglement) -- so dependency
risk is low, but the *file itself* is large and mostly out of scope for M3's
actual need (HyperFrames, atelier bespoke authoring, and the review/QA
sub-pipeline are all unrelated to closing F1). Vendoring the whole file would
mean carrying and R2-DEC-031-justifying ~2,500 lines of code this milestone
does not use. This tips the Section 7 options toward the thinner wrapper
(Option 1): mirror `composition.py`/`local_production.py`'s existing
subprocess pattern and call `npx remotion render` directly, rather than
importing `video_compose.py` wholesale.

## 5. What "two V1 corpus products" need (fact, from the V1 strategy doc)

`docs/r2/R2_V1_PRODUCTION_RELEASE_STRATEGY.md` section 2:

1. one 60-180 second factual/explainer with operator-reviewed source/script;
2. one 60-120 second narrative/drama scene with at least two named characters
   or explicitly selected narrative assets.

Both "must retain selected source/script/master identities, visible media or
graphics, intelligible selected audio or an explicit mute decision, duration,
successful playback, export digest and post-restart reopen/preview evidence."
The factual product maps directly onto M3/Golden A's existing pipeline shape.

**Checked this session**: M6's own acceptance test
(`tests/integration/r2/test_m6_dual_profile_acceptance.py`) does not render
any real video at all. Its `test_mutation_a_failed_candidate_is_refused_and_
never_becomes_master` test (and the rest of the suite around it) uses purely
symbolic strings for `GenerationCandidate.provider_execution_ref`
(`"local:ffmpeg:good"` / `"local:ffmpeg:failed"`) and
`output_asset_ref` (`"asset:good"`) -- these are never resolved to a real
ffmpeg invocation or a real file; they exist only to exercise
`ProductionApprovalService.promote`'s candidate-lifecycle/approval boundary
(M4's authority layer). M6's own roadmap goal was TakeDirector→ShotSpec
mapping and the adaptation authority/decision layer, not rendering -- so this
is not a regression or a hidden defect, just scope that was never built.

**This reframes the whole gap**: there is one missing capability (a real
rendering engine, replacing the F1 solid-color stub), not two separate gaps.
Both V1 corpus products need the *same* new rendering engine; they differ
only in which content feeds it -- M3's `ClaimLedger`-derived `ShotSpec`s for
the factual product, M6's adaptation-derived `ShotSpecV2`s for the
narrative/drama product. A spec/plan for closing F1 should design the
rendering engine once and prove it against both corpora, not build two
independent renderers.

## 6. Facts vs. inference vs. unknowns

**Facts** (verified this session, in code or by direct execution):
- The exact mechanism and location of the solid-color placeholder (Section 1).
- The OpenMontage donor is pinned, cloned, and its contract tests passed
  previously (Section 2).
- A real, zero-key, local Remotion render succeeds on this machine today,
  including a real Vietnamese-diacritic text render, visually verified
  (Section 3).
- The `Explainer` prop model and its mapping onto existing R2 contracts
  (Section 4).
- The V1 corpus product requirements, and that M6's Golden B has no real
  rendering to compare against -- both products need the same new engine
  (Section 5).
- `tools/video/video_compose.py`'s and `tools/base_tool.py`'s exact import
  lists (both stdlib-only; the 2,944-line file is large but not
  dependency-risky, just mostly out of scope for F1) (Section 4).

**Inference** (reasonable but not yet verified):
- That `ShotSpec`/`Claim` map onto `Cut`/`Overlay` as cleanly as Section 4
  suggests once real fixture data is pushed through -- not yet tried.
- That audio narration (TTS or otherwise) is in scope for "intelligible
  selected audio or an explicit mute decision" -- the V1 bar allows an
  explicit mute decision as an alternative, so real audio may not be
  required for a first closure, but this has not been decided.

**Unknowns** (require further investigation before a plan can be written):
- Whether R2-DEC-031's coverage/parity gates expect literally reusing
  OpenMontage's Python orchestration layer, or only its Remotion/TypeScript
  composition layer with R2's own Python wrapper -- both are defensible
  readings of "donor reuse," and the review's own wording ("tận dụng
  OpenMontage composition") is closer to the latter, reinforced by Section 4's
  finding that `video_compose.py` is mostly out-of-scope surface, but this is
  still a judgment call for the spec to make explicitly, not an already-locked
  decision.
- Exact TTS/audio sourcing for real narration, if audio is judged in scope.
- What counts as "a fresh topic not already used as a fixture" for the
  factual product (per F1's own stated closing criterion) -- no candidate
  topic has been chosen yet.
- Exact mapping from M6's `ShotSpecV2`/adaptation output into `Cut`/`Overlay`
  -- Section 4 only worked through M3's (v1) `ShotSpec`; M6's screenplay/
  adaptation output shape has not been read this session.

## 7. Options for the integration boundary

1. **Thin R2-owned Python wrapper** that shells out to
   `npx remotion render` directly (mirroring the existing `ffmpeg`
   subprocess pattern in `composition.py`/`local_production.py`), building
   the `{cuts, overlays, captions, audio}` JSON props from R2's own
   `ShotSpec`/`ClaimLedger`/`SceneSpec` data. Vendors only the
   `remotion-composer/` TypeScript project (already MIT-scoped by the
   sponsor's license-out-of-scope decision), none of OpenMontage's Python
   tooling.
2. **Reuse `tools/video/video_compose.py` more directly**, either by vendoring
   it plus its `tools.base_tool` dependency, or by porting its
   routing/validation logic into an R2-owned module. Higher fidelity to the
   donor's own tested behavior (closer to R2-DEC-031's "parity" bar), and
   Section 4 confirms the dependency risk is low (stdlib-only) -- but the
   file itself is 2,944 lines, and the large majority (HyperFrames rendering,
   atelier/bespoke authoring, automated transcript-vs-script review) is
   unrelated to closing F1. Vendoring it wholesale means carrying and
   R2-DEC-031-justifying code this milestone never exercises.

**Recommendation: Option 1.** It mirrors this project's own established
pattern of vendoring only the exact needed surface (Take's enum vocabulary in
M6, not its whole runtime; Huohuo's Shuangwen scoring logic, not its
book-management layer), and Section 4's full read of `video_compose.py`
removes the main reason Option 2 looked attractive (avoiding a large,
unknown dependency tree) without removing its main cost (vendoring ~2,500
lines of unrelated surface). This is a recommendation for the spec to state
and justify explicitly, not a decision already made by this research.

## 8. Recommended next step

Per the user's explicit choice to do proper research/spec/plan before any
code, this research's open items are now narrowed to: pick a concrete new
factual topic and a concrete narrative scene from Golden B's existing corpus,
decide the audio scope (mute-by-default vs. real narration for V1), and read
M6's adaptation/screenplay output shape closely enough to map it onto
`Cut`/`Overlay`. Then write
`docs/superpowers/specs/2026-09-21-r2-m3-real-media-closure-design.md` and a
matching implementation plan, following this project's established
research → spec → plan → execution sequence (mirrors M6/M7's own history).
