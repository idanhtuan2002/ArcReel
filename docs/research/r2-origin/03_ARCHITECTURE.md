# 03 — Architecture

**Trạng thái:** Tầng lý do. Không có thẩm quyền — xem [`README.md`](README.md).
Bản có thẩm quyền: `docs/r2/R2_01_FROZEN_ARCHITECTURE.md`, `docs/r2/R2_04_DECISION_REGISTRY.json` (`FROZEN_V1`), `docs/r2/R2_06_FROZEN_IMPLEMENTATION_ROADMAP.md`.

Tài liệu này trình bày kiến trúc như nó **được suy ra từ** [`01`](01_RESEARCH_SYNTHESIS.md)/[`02`](02_SYSTEM_REQUIREMENTS.md); §7 là crosswalk sang bản frozen.

---

## 1. Tổng thể — 3 plane quanh một Host

```
                          HUMAN SHOWRUNNER
                                 │  (Gates A/B/C/D)
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│              HOST / CONTROL / PRODUCTION RUNTIME                    │
│                      ArcReel-derived                               │
│  Project │ PostgreSQL │ Tasks │ Queue │ Assets │ Versions │ Cost   │
│  Artifact lifecycle (Current/Stale/Missing/Blocked) │ Review       │
│  Provider backends │ FFmpeg │ Export │ Budget reservation (C04)    │
└──────────────────────────────┬─────────────────────────────────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        ▼                      ▼                      ▼
 INTELLIGENCE PLANE       NARRATIVE PLANE        DIRECTOR PLANE
 OpenMontage-derived      OUR Canon Kernel       take-derived
 research / proposal      Epistemic Engine       Jellyfish readiness
 content profiles         Novel Studio           visual identity (ai-short-film)
 provider scoring         Huohuo / StoryBox      prompt compiler (Butterfly)
                          Shenbi QA
        │                      │                      │
        └──────────────────────┼──────────────────────┘
                               ▼
                       UNIFIED CONTRACTS
        ResearchPack │ ContentBrief │ ScriptArtifact │ SceneSpec │ ShotSpec
        CanonDelta │ GenerationCandidate │ QualityReport │ PerformanceReport
                               │
                               ▼
                   PRODUCTION METHOD ROUTER
   reuse │ stock │ capture │ deterministic │ image │ video │ composite
                               │
                               ▼
┌────────────────────────────────────────────────────────────────────┐
│                        EXECUTION LAYER                             │
│  ComfyUI │ DC-Media gateway │ H3 │ Seedance │ Veo │ Kling │ ...    │
│  VieNeu (VN TTS) │ OBS │ Remotion / HyperFrames │ FFmpeg          │
└──────────────────────────────┬─────────────────────────────────────┘
                               ▼
                        QA / APPROVAL  (6 lớp, reviewer độc lập)
                               ▼
                          DISTRIBUTION  (YouTube / TikTok / ...)
                               ▼
                       ANALYTICS / LEARNING  (OUR subsystem)
                               │
                               └────────────→ INTELLIGENCE PLANE
```

**Nguyên tắc:** không tạo **hai database truth**. Narrative truth (Canon Kernel) và Production truth (ArcReel Artifact Runtime) là hai loại khác nhau nhưng **cùng một host/DB transaction boundary**.

## 2. Bảng sở hữu (owner) — OWNED vs REUSED

| Chức năng | Owner | Nguồn |
|---|---|---|
| Story/scene truth | **R2 owns** | Canon Kernel (tự xây) |
| Epistemic / KnowledgeState | **R2 owns** | tự xây |
| Canon transaction (PROPOSE→validate→review→COMMIT) | **R2 owns** | tự xây |
| Unified cross-media contracts | **R2 owns** | map từ schema ArcReel/OpenMontage/take |
| Cross-media Artifact Dependency Graph | **R2 owns** (mở rộng) | ArcReel Artifact Manifest |
| Production Method Router / Quality Ladder | **R2 owns** | policy từ OpenMontage selector |
| Cross-media continuity | **R2 owns** | tự xây |
| Learning Engine + Governance | **R2 owns** | tự xây |
| Beat/shot grammar | reuse | **take** `packages/core` |
| Shot contract (`ShotSpec`) | R2 owns | (schema riêng) |
| Asset/dialogue confirmation, production readiness | reuse | **Jellyfish**-derived |
| Face/look identity | reuse | **ai-short-film**-derived |
| Prompt compilation (`PromptPlan`) | reuse | **Butterfly**-derived |
| Provider execution, job/recovery, queue, idempotency | reuse | **ArcReel** runtime |
| Artifact/version | reuse + extend | **ArcReel** + R2 |
| Candidate selection | R2 owns | R2 QA/Review |
| Creative canvas (exploration) | reuse | **DramaClaw**-derived |
| Research/proposal/script, content profiles, provider scoring | reuse | **OpenMontage**-derived |
| VN voice | reuse | **VieNeu** |
| Deterministic composition | reuse | **OpenMontage Remotion/HyperFrames** (primary); Code2MP4 (benchmark phụ) |
| Visual execution engine | reuse | **ComfyUI** (external) |

> Tài sản thật của R2 **thu hẹp nhưng mạnh hơn**: Canon Kernel, Epistemic Engine, Canon Transactions, Unified Cross-media Contracts, Artifact Dependency semantics, Method Router/Quality Ladder, Cross-media Continuity, Learning Engine, Governance. Phần còn lại **mổ lấy** từ hệ hiện có.

## 3. Director stack — 4 stage tuần tự

```
ScriptArtifact
     │
     ▼
1. take — CREATIVE DIRECTOR         beat + shot grammar → ShotDraft
     │  normalize + validate
     ▼
   ShotSpec  (provider-neutral)
     │
     ▼
2. Jellyfish-derived — SHOT PREPARATION
     │  bind entities / dialogue / location / prop / wardrobe / references / keyframe
     ▼
3. ai-short-film-derived — VISUAL IDENTITY
     │  face_identity / look_lock / canonical views / last_frame_anchor
     ▼
   READY_FOR_PRODUCTION
     │
     ▼
   PRODUCTION METHOD ROUTER  ──┬── deterministic ──▶ Remotion / Code2MP4
     │                          └── generative ──▶ 4. Butterfly-derived PROMPT COMPILER
     │                                                     │ ShotSpec + VisualIdentityProfile
     │                                                     │ + ProductionBinding + ContinuityAnchor
     │                                                     │ + StyleProfile + ProviderCapabilities
     │                                                     ▼
     │                                                 PromptPlan → Provider Adapter → ProviderRequest
     ▼
   ARCReel RUNTIME  →  GenerationCandidate[]  →  QA / selection  →  ApprovedShotMaster  →  Assembly
```

## 4. Chuỗi visual continuity

```
Canon Character
     │
     ▼
ai-short-film identity  (face_identity, look_lock, canonical views)
     │
     ▼
ArcReel Asset Registry  (approved masters + variants)
     │
     ▼
Jellyfish Shot Binding  (bind vào từng shot)
     │
     ▼
Storyboard / Keyframe
     │
     ▼
Butterfly Prompt Compiler  (consistency_tokens, style_tokens)
     │
     ▼
H3 / Seedance / Veo / ...
```

## 5. Hai luồng chính

### 5a. Fiction / narrative

```
Idea / Research
     ▼
Story Premise
     ▼
Novel Studio  (Story Bible, Style Bible, Arc, Chapter, Scene Beats, Context Pack)
     ▼
OUR Canon / Epistemic
     ├────────────────┐
     ▼                ▼
 StoryBox         Huohuo
 (characters,     (causal planning,
  simulation)      Change Records)
     └───────┬────────┘
             ▼
          Writer  →  Candidate
             ▼
          Shenbi QA  →  Human Review
             ▼
          CanonDelta  →  CANON COMMIT
             ▼
   accepted narrative → Huohuo adaptation → screenplay → take → (Director stack §3)
```

### 5b. General content / YouTube (không qua Narrative OS đầy đủ)

```
OpenMontage research  →  ResearchPack
     ▼
ContentBrief
     ▼
OpenMontage script  →  ScriptArtifact
     ▼
take / lightweight Director  →  ShotSpec
     ▼
Method Router
  ├── OBS (screen capture)
  ├── Stock (Pexels)
  ├── Remotion (deterministic graphics)
  ├── ComfyUI (image)
  └── Video AI (H3 / Seedance / Veo)
     ▼
ArcReel Runtime  →  QA  →  YouTube uploader
```

## 6. Production Method Router (chi tiết)

```
                       SHOT SPEC
                          │
                    Method Router  (method BEFORE provider — R2_04 LOCKED)
                          │
  ┌────────┬──────────┬───┴──────┬──────────────┬──────────┐
  ▼        ▼          ▼          ▼              ▼          ▼
Reuse    Real       Program-   Generated      Generated  Composite
Asset    Capture    matic      Image          Video
  │        │          │          │              │
Library   OBS      Code2MP4/  ComfyUI        ┌────┴────┐
                   Remotion   image models   ▼         ▼
                                          H3 local  Seedance/Veo/Kling
```

Router đọc **một** `CapabilityRegistry` chuẩn hoá; chọn theo task-fit / quality / control / reliability / cost / latency / continuity / reference support / audio / resolution / shot type + lịch sử acceptance. Hard-budget admission → **C04 atomic reservation**.

## 7. Crosswalk quyết định → bản FROZEN

Các ID `R2-D##` / `D-B##` dưới đây xuất hiện trong thảo luận gốc. **Tất cả đã được nâng lên LOCKED** trong `docs/r2/R2_04_DECISION_REGISTRY.json` (`FROZEN_V1`) với tiêu đề sạch hơn. Bảng này chỉ để truy vết nguồn.

| ID gốc | Nội dung gốc | Tiêu đề trong `R2_04` (FROZEN) |
|---|---|---|
| R2-D01 | Human Showrunner final authority | Human Showrunner remains final creative/governance authority — LOCKED |
| R2-D02 | Candidate ≠ Canon | Candidate is never Canon — LOCKED |
| R2-D03 | Shot ≠ GenerationCandidate | (Shot readiness / ApprovedMaster cluster) — LOCKED |
| R2-D04 | Canon và production artifacts là authority tách biệt | Five authority planes; Exactly one commit authority per family — LOCKED |
| R2-D05 | Method before provider/model | Method before provider — LOCKED |
| R2-D06 | Reuse/deterministic/capture/stock trước generation đắt | Method before provider (branch order) — LOCKED |
| R2-D07 / D-B02 | youtube-agentic-ai-studio không còn là baseline | (reopened; ArcReel leads) — LOCKED |
| R2-D08 / D-B01 | ArcReel-derived runtime = primary host | ArcReel-derived Host is primary runtime — LOCKED |
| R2-D09 / D-B03 | OpenMontage = general-content donor | DirectorAdapter is format-sensitive (OpenMontageDirector) — LOCKED |
| R2-D10 / D-B04 | DramaClaw = creative-canvas donor | Creative Canvas is exploration-only until PROMOTE — LOCKED |
| R2-D11 / D-B05 | Novel Studio = long-form planning donor | (narrative authority cluster) — LOCKED |
| R2-D12 | Huohuo = causal Change Record + adaptation | NarrativeChangeSet distinct from CanonDelta; Adaptation uses branch/overlay — LOCKED |
| R2-D13 | Shenbi = narrative QA/gates | (narrative QA cluster) — LOCKED |
| R2-D14 | StoryBox = character simulation | KnowledgeState is first-class — LOCKED |
| R2-D15 / D-B06 | take = creative shot grammar | DirectorAdapter is format-sensitive (TakeDirector) — LOCKED |
| R2-D16 / D-B07 | Jellyfish = shot readiness | Shot readiness distinct from content status and runtime task status — LOCKED |
| R2-D17 / D-B08 | ai-short-film = visual identity/look-lock | VisualIdentityProfile is first-class production state — LOCKED |
| R2-D18 / D-B08 | Butterfly = prompt compiler | PromptPlan is separate from ProviderRequest — LOCKED |
| R2-D19 | OpenMontage Remotion = primary deterministic composition | (execution layer) — LOCKED |
| R2-D20 | Code2MP4 = secondary renderer benchmark | (execution layer) — PROVISIONAL/benchmark |
| R2-D21 | ComfyUI = external Visual Execution Engine | (execution layer) — LOCKED |
| R2-D22 | Một PostgreSQL host trong V1, không truth microservices | Use PostgreSQL from Host fork start; No second general media queue — LOCKED |
| R2-D23 | Temporal hoãn đến khi có bằng chứng gap idempotency | (host hardening) — LOCKED |
| R2-D24 | Giữ Current/Stale/Missing/Blocked | Extend ArcReel Artifact Manifest; no parallel registry — LOCKED |
| R2-D25 | Stale vẫn usable; regeneration explicit | Content currency semantics — LOCKED |
| R2-D26 | Failed regeneration preserves usable prior output | ApprovedMaster requires explicit selection — LOCKED |
| R2-D27 | Golden A **và** Golden B đều bắt buộc | (roadmap M3/M6) — LOCKED |
| R2-D28 | Analytics không tự sửa Canon/policy | (learning governance) — LOCKED |
| R2-D35 | Canvas = exploration, not truth | Creative Canvas is exploration-only until PROMOTE — LOCKED |
| R2-D36 | Canvas → production cần PROMOTE tường minh | " — LOCKED |
| R2-D38 | DC-Media = transport protocol, not domain contract | (execution layer transport) — LOCKED |
| R2-D40 | Director stack có 4 trách nhiệm tuần tự | ProductionBinding is the semantic-to-production bridge — LOCKED |
| R2-D41 | Bỏ take jobs/provider layer khi ArcReel là host | No second general media queue — LOCKED |
| R2-D42 | Shot status ≠ readiness ≠ runtime status | Shot readiness is distinct — LOCKED |
| R2-D43 | Visual identity = first-class domain object | VisualIdentityProfile is first-class — LOCKED |
| R2-D44 | Previous-frame chaining có điều kiện | Previous-frame chaining is conditional — ACTIVE |
| R2-D45 | Butterfly compiles ShotSpec, không sở hữu nó | PromptPlan is separate from ProviderRequest — LOCKED |
| — | Director World (360/3D) | Director World is deferred advanced spatial planning — deferred |

## 8. Golden A & Golden B — hai vertical slice để validate kiến trúc

| | Golden A | Golden B |
|---|---|---|
| Loại | YouTube tech/explainer | Fiction drama |
| Ví dụ | "Claude Code hết quota nhanh vì sao?" | drama 60–120s |
| Test đường | `Idea → Research → Script → mixed media → narration → QA → final` | `Canon → Screenplay → Director → identity → continuity → video → final` |
| Ràng buộc | nguồn hỗ trợ đúng, hình đúng nội dung, caption/audio đồng bộ | 2 nhân vật, 5–10 shots, đổi location, đổi prop/state, secret constraint, ≥1 shot nhiều candidate, continuity pass |

Chỉ pass A mà fail B → quá YouTube-centric. Chỉ pass B mà fail A → quá drama-centric. **Kiến trúc phải pass cả hai.**

## 9. Roadmap — bản gốc đã bị thay

Thảo luận gốc từng đề xuất roadmap `M0 VISION → M1 DOMAIN → M2 CONTRACTS → M3 YOUTUBE SLICE → M4 HYBRID/DIRECTOR → M5 ANALYTICS → M6 NARRATIVE → M7 FICTION SLICE → M8 MULTI-FORMAT`, cùng một `R8 — Advanced Creative Workbench` cho DramaClaw 360/3D.

**Bản có thẩm quyền hiện tại** (`docs/r2/R2_06_FROZEN_IMPLEMENTATION_ROADMAP.md`, `FROZEN v1`):

| | Milestone |
|---|---|
| M0 | Host Fork Foundation (fork/pin ArcReel v0.29.0, PostgreSQL baseline, register H1) |
| M1 | R2 Contract Kernel (ContentBasis, SceneSpec, ShotSpec, ProductionBinding, VisualIdentityProfile, MethodDecision, PromptPlan, fingerprints) |
| M2 | Artifact Bridge (mở rộng Artifact Manifest, Current/Stale/Missing/Blocked, ApprovedMaster) |
| M3 | Golden A — general content (factual fixture) |
| M4 | Production Intelligence (Director routing, Method Router, CapabilityRegistry, PromptPlan/Gate-2, PromptCompiler; C04 budget) |
| M5 | Canon & Narrative Kernel (CanonBranch/Version, Entity/Fact/Event, KnowledgeState, Epistemic Engine, NarrativePlan, transaction services) |
| M6 | Adaptation + Golden B (AdaptationBranch/Map → Screenplay → Director → drama) |
| M7 | Host Production Hardening (H1–H8, execution identity, idempotency, atomic promotion, restart, backup/restore, observability) |
| M8 | Advanced Canvas / Learning / Multi-format (DramaClaw canvas + PROMOTE, Learning Engine, multi-format IP) |

Director World (360/3D) được **gộp vào M8**, không tách thành R8.

## 10. Con trỏ

- Kiến trúc frozen: `docs/r2/R2_01_FROZEN_ARCHITECTURE.md`
- Decision registry (LOCKED): `docs/r2/R2_04_DECISION_REGISTRY.json`, `R2_04_CONSOLIDATED_DECISION_LOG.md`, `R2_04_SUPERSESSION_MAP.json`
- Roadmap: `docs/r2/R2_06_FROZEN_IMPLEMENTATION_ROADMAP.md`
- M4 decisions D01–D12 / C01–C10: `.../conten os/R2_M4_D01-D12_FROZEN_2026-09-07.md`
