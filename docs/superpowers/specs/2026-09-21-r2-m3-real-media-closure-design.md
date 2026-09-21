# R2 M3 Real-Media Closure Design

**Research basis:** `docs/research/2026-09-21-r2-m3-real-media-closure-research.md`

## 1. Goal and boundary

Close F1 (`docs/r2/evidence/PROJECT_STATUS_REVIEW_2026-09-09.md`): M3's own
frozen exit gate --- "one real factual/general-content artifact end-to-end;
at least three production methods; claim lineage visible; cost/provenance
captured" --- has never actually been met. Every shot's video today is a
solid-color FFmpeg test pattern (`r2/m3/local_production.py`), regardless of
its labeled method. This spec replaces that stub with a real rendering
engine and proves it against **both** V1 corpus products (ADR-0089 P0 item
4): a factual/explainer artifact (M3's own Golden A lineage) and a
narrative/drama scene (M6's Golden B, already accepted, never rendered).

**In scope:**
- A real rendering engine wrapping OpenMontage's `remotion-composer`
  (`npx remotion render`), replacing the color-generator in
  `local_production.py`.
- Real `REUSE` (actual source file passthrough), real `DETERMINISTIC`
  (actual script/claim/dramatic-text rendered on screen), unchanged
  `COMPOSITE` (already real).
- A new factual topic distinct from the existing `golden_a_git.json` fixture
  (F1's own stated closing criterion: "chạy thêm một chủ đề chưa dùng làm
  fixture").
- Wiring M6's existing "ledger reveal" Golden B corpus
  (`tests/fixtures/r2/m6_dual_profile_corpus.py`) through `TakeDirectorAdapter`
  into the same rendering engine, for the narrative/drama product.
- R2-DEC-031's evidence chain (baseline/coverage/parity/completion) for the
  vendored `remotion-composer/` surface.

**Explicitly out of scope** (per ADR-0089's bounded V1 and this session's
research):
- Any paid/real AI provider call (`GENERATED_IMAGE`/`GENERATED_VIDEO`
  methods) --- M7-E provider qualification is a separate, later, gated
  milestone requiring separately-approved paid canary work. `REUSE` +
  `DETERMINISTIC` + `COMPOSITE` already satisfy "at least three production
  methods" without a paid provider.
- Vendoring `tools/video/video_compose.py` or `tools/base_tool.py` wholesale
  (research Section 4/7): only the `remotion-composer/` TypeScript project is
  vendored; the rendering orchestration itself is a new, narrow, R2-owned
  Python module mirroring the existing `ffmpeg` subprocess pattern.
- HyperFrames rendering, atelier/bespoke authoring, and OpenMontage's
  automated transcript-vs-script review pipeline --- all unrelated to F1.
- Real narration audio (TTS or recorded) --- V1's own bar
  (`R2_V1_PRODUCTION_RELEASE_STRATEGY.md` §2) accepts "an explicit mute
  decision" as an alternative to intelligible audio; this closure ships
  explicit-mute for both products (see §7), leaving real narration to a
  later, separately-scoped V1.x or V2 item.
- Rewriting M6's screenplay/adaptation authoring pipeline. This closure only
  adds a new *consumer* (the render step) downstream of `TakeDirectorAdapter`,
  which already exists and is unchanged.

## 2. Existing seams and measured gaps

| Seam | Current state | Gap this closes |
|---|---|---|
| `r2/m3/local_production.py::GoldenALocalProducer.produce` | Every method (`REUSE`, `DETERMINISTIC`) renders a solid FFmpeg color pattern; `REUSE`'s bound source file is hashed but never used as visual input | Replace the `ffmpeg -f lavfi -i color=...` branch with a real render call |
| `r2/m3/composition.py::GoldenAComposer.compose` | Real `ffmpeg concat` of per-shot files | No change --- already real, correctness is inherited once its inputs are real |
| `r2/m3/preparation.py::GoldenAProductionPreparation.prepare` | Hardcodes `SH01 → REUSE`, everything else `→ DETERMINISTIC` | No change to the assignment logic itself; the fixture driving it gets a 3rd, genuinely distinct shot exercising each method plus a `STOCK`-style reused clip if the new topic's source material supports it |
| M6 → video pipeline | `TakeDirectorAdapter.direct()` already converts an admitted `ScreenplayArtifactV2` into real `ShotSpecV2`s (`r2/production_intelligence/take_director.py`); nothing downstream ever renders them | New: a render step consuming `TakeDirectionResult.shots` the same way M3's shots are consumed |
| `r2/m3/fixtures/golden_a_git.json` | Existing factual topic (Git's working-tree/index/commit model) already used as a fixture | New fixture, new topic (§6) |
| `tests/fixtures/r2/m6_dual_profile_corpus.py` | Real `dramatic_text`, 2 named characters (Hero/Ally), 6 scenes × 15s = 90s, both Western-English and CN-Shuangwen-Chinese profile variants | Reused as-is (no authoring needed) --- see §6 |

## 3. Canonical vocabulary

- **Cut**: one timed render segment (`remotion-composer`'s own term, kept
  verbatim to avoid a synonym for the same concept). Maps 1:1 from one
  `ShotSpec`/`ShotSpecV2`.
- **RenderPlan**: this spec's new R2-owned contract --- the exact
  `{cuts, overlays, captions, audio}` payload passed to
  `npx remotion render`, plus the identity/provenance fields needed for
  `execution_fingerprint` (mirroring `LocalProducedAsset`'s existing shape).
- **shot-to-cut projection**: the pure function turning one `AnyShotSpec`
  (plus whatever text source the method implies --- a bound `REUSE` source
  file, a `Claim.statement`, or a `ScreenplayScene.dramatic_text`) into one
  `Cut`.

## 4. Fixed contracts

```python
# r2/m3/render_plan.py (new)

@dataclass(frozen=True)
class RenderCut:
    cut_id: str
    in_seconds: float
    out_seconds: float
    kind: Literal["video_passthrough", "text_card", "stat_card"]
    source_path: Path | None          # required iff kind == "video_passthrough"
    text: str | None                  # required iff kind in ("text_card", "stat_card")
    subtitle: str | None = None
    background_color: str | None = None

@dataclass(frozen=True)
class RenderPlan:
    plan_id: str
    cuts: tuple[RenderCut, ...]
    width: int = 1920
    height: int = 1080
    fps: int = 30

@dataclass(frozen=True)
class RenderedCutAsset:
    target_ref: str
    method: ProductionMethod
    path: Path
    sha256: str
    duration_seconds: float
    execution_fingerprint: str
    tool: Literal["remotion"]
    tool_version: str                 # `npx remotion --version` output
    wall_time_seconds: float
    external_provider_cost: Decimal   # always Decimal("0") -- no paid provider in this closure
    source_master_refs: tuple[str, ...]
```

`RenderedCutAsset` is deliberately shaped like the existing
`LocalProducedAsset`/`GoldenACompositeAsset` (same field names/types where
they overlap) so `GoldenAComposer.compose` --- which only reads `path`,
consumes nothing renderer-specific --- needs no change at all.

## 5. Shot-to-cut projection

```python
def project_shot_to_cut(
    shot: AnyShotSpec,
    *,
    method: ProductionMethod,
    bound_source: Path | None,        # resolved REUSE binding, if any
    display_text: str | None,         # Claim.statement or ScreenplayScene.dramatic_text, if any
) -> RenderCut:
    ...
```

- `REUSE`: requires `bound_source` (fail closed if absent --- mirrors
  `local_production.py`'s existing `if not prepared.bindings: raise
  ValueError`). `kind="video_passthrough"`, `source_path=bound_source`. This
  is the one-line-of-intent fix for F1's core defect: the real file is now
  *used*, not just hashed.
- `DETERMINISTIC`: requires `display_text` (fail closed if absent).
  `kind="text_card"` for a factual claim (mirrors `Cut.type: "text"`, proven
  to render correctly including Vietnamese diacritics, research §3);
  `kind="stat_card"` is available for a factual shot whose claim is
  numeric/comparative, at the caller's discretion --- not mandatory for this
  closure.
- Every other currently-defined `ProductionMethod` (`STOCK`,
  `SCREEN_CAPTURE`, `GENERATED_IMAGE`, `GENERATED_VIDEO`) is out of scope for
  this closure (§1) and `project_shot_to_cut` raises `NotImplementedError`
  for them --- explicit, not silent, so a future caller cannot accidentally
  fall through to an unimplemented method the same way the old color-picker
  silently absorbed every method into one code path.

For the factual product, `display_text` is a linked `Claim.statement`
(`r2/contracts/factual.py`) --- the exact mechanism that makes "claim
lineage visible" a real, on-screen fact rather than a data-structure-only
one. For the narrative product, `display_text` is the originating
`ScreenplayScene.dramatic_text`, resolved via the shot's `scene_id` back
through the admitted screenplay `TakeDirectorAdapter` already read
(`r2/production_intelligence/take_director.py`'s `_shot_spec` sets
`scene_id`; the caller re-reads the matching `ScreenplayScene` from the same
`ScreenplayArtifactV2` already in hand rather than adding a new field to
`ShotSpecV2` --- `ShotSpecV2` is a fixed M6 contract and widening it is out
of this closure's scope).

## 6. The two corpus products

### 6.1 Factual/explainer (new topic, new fixture)

A new `r2/m3/fixtures/golden_a_<topic>.json`, structurally identical to the
existing `golden_a_git.json` loader contract
(`load_golden_a_factual_bundle`, unchanged) but with a genuinely different
subject so F1's "fresh topic" bar is met. Candidate topic, subject to the
user's confirmation: **how video encoding/compression works** (H.264
keyframes vs. delta frames, why compression ratio trades off against
quality) --- thematically apt for a video-generation product, has simple,
easily-sourced, verifiable claims, and needs no author-invented factual
content (public, well-documented technical subject, consistent with the
Git-workflow fixture's own "explain a real technical mechanism" shape). Any
other equally simple, verifiable, non-sensitive topic is an equally valid
substitute --- this is a content choice, not an architecture decision.

Duration target: 60-180s per the V1 bar. 3-5 shots is enough to cover
`REUSE` (one shot reusing a real checked-in source asset, exactly as
`SH01` already does) + `DETERMINISTIC` (2-4 shots, each showing one real
`Claim.statement`) + `COMPOSITE` (the final concat, unchanged).

### 6.2 Narrative/drama (reuse Golden B, no new authoring)

Reuse `tests/fixtures/r2/m6_dual_profile_corpus.py`'s existing "ledger
reveal" corpus verbatim: 6 scenes, 2 named characters (Hero, Ally), 15s each
= 90s (inside the V1 bar's 60-120s window). Already exists in two profile
variants --- Western-generic English and CN-short-drama-Shuangwen Chinese
--- both real `dramatic_text`, no author-invented content needed. The
Shuangwen variant additionally exercises real CJK text rendering (this
session tested Vietnamese; CJK has not been tested yet --- see §8 open
item).

Path: `AdmittedScreenplayRef` (already produced by M6's existing admission
flow) → `TakeDirectorAdapter.direct()` (unchanged, already real) →
`TakeDirectionResult.shots` → the new render step (§5) → `GoldenAComposer`
(unchanged, already real, dialect-agnostic to which milestone produced its
inputs).

## 7. Audio: explicit mute, not silent omission

Per the V1 bar's own alternative ("intelligible selected audio or **an
explicit mute decision**"), both products ship muted for this closure:
`RenderPlan` carries no `audio` block, and the acceptance evidence records
`audio_decision: "explicit_mute"` with a one-line rationale (real narration
requires either a TTS pipeline or recorded voice talent, neither built nor
in scope here) --- this is a recorded decision, not a silently missing
feature. Revisit only if the user asks for real audio in this same closure.

## 8. R2-DEC-031 evidence chain for the vendored surface

Only `remotion-composer/` (the TypeScript project, not OpenMontage's Python
tooling) is vendored, matching §1's boundary:

- **Baseline**: donor `github.com/calesthio/OpenMontage`, pinned commit
  `08e2151fa02de28a5d6a312b3d575692bf147ad7` (already the pin recorded in
  `docs/research/2026-09-07-r2-reuse-map-and-completion-gates.md`; no new
  pin needed).
- **Coverage**: this session already ran a real, zero-key render
  (`npx remotion render src/index.tsx Explainer ...`) and a real
  Vietnamese-diacritic text render, both verified via `ffprobe`/visual frame
  inspection (research §3). The implementation plan adds this as a real,
  repeatable integration test (not just an ad hoc session command).
- **Parity**: N/A in the strict "same fixture, two implementations" sense
  --- this closure is the *first* real use of this composition inside R2,
  not a reimplementation of existing R2 behavior, so there is no prior R2
  output to diff against. Parity is instead proven against the donor's own
  behavior: the vendored `Explainer.tsx` is used unmodified (no R2 fork of
  its render logic), so its own upstream contract tests
  (`docs/r2/evidence/reuse-map-2026-09-07/openmontage-probe.log`: 56 passed)
  remain the parity evidence for the composition layer itself.
- **Completion**: evidence bound to the exact integrated HEAD, per the
  M7-A..D precedent format (`docs/r2/evidence/R2_M3_REAL_MEDIA_CLOSURE.json`,
  named to plan).

## 9. Verification matrix

| Requirement (M3's own exit gate) | How this closure proves it |
|---|---|
| one real factual artifact end-to-end | New topic (§6.1) rendered through the full `ResearchPack → ClaimLedger → ScriptArtifact → ShotSpec → RenderCut → ApprovedMaster` chain, real Remotion output, `ffprobe`-verified |
| one real narrative/drama artifact end-to-end | Golden B corpus (§6.2) rendered through `ScreenplayArtifactV2 → TakeDirectorAdapter → ShotSpecV2 → RenderCut → ApprovedMaster`, both profile variants |
| at least three production methods | `REUSE` (real passthrough), `DETERMINISTIC` (real claim/dramatic-text card), `COMPOSITE` (real concat, unchanged) --- each producing visibly distinct, non-solid-color output |
| claim lineage visible | A `Claim.statement`/`ScreenplayScene.dramatic_text` is not just linked in data but literally rendered on screen in the `DETERMINISTIC` shots |
| cost/provenance captured | `RenderedCutAsset.external_provider_cost = Decimal("0")` (accurate: no paid provider used), `execution_fingerprint`/`tool_version` recorded exactly as the existing `LocalProducedAsset` shape already does |
| R2-DEC-031 (donor reuse) | §8 |

## 10. Exit states

- **CLOSED**: both corpus products render real, non-solid-color, distinct-
  by-method output; `ffprobe`-verified playable; claim/dramatic-text visible
  on screen (spot-checked by frame extraction, mirroring this session's own
  Vietnamese-render verification); full gate suite green at the exact HEAD;
  evidence recorded per §8's completion bullet.
- **REJECTED**: any of the above fails, or a method silently falls back to a
  placeholder instead of raising (§5's explicit `NotImplementedError` for
  out-of-scope methods exists precisely to make silent fallback impossible).
