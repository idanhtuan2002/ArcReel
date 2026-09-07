# 01 — Research Synthesis

**Trạng thái:** Tầng lý do. Không có thẩm quyền — xem [`README.md`](README.md).
Sổ bằng chứng nghiên cứu gốc: `.../content_production_os_foundation_r2/10_RESEARCH_EVIDENCE_REGISTER.md`.
Bản đồ tái sử dụng chi tiết + pin/SHA: `docs/research/2026-09-07-r2-reuse-map-and-completion-gates.md`.

---

## 1. Bối cảnh model & hệ thống (đến ~09/2026)

| Sự kiện | Hệ quả cho kiến trúc |
|---|---|
| OpenAI **ngừng sản phẩm Sora** (26/04/2026) | Provider churn là rủi ro **thật**, không giả định |
| **MiniMax H3** xuất hiện, open-weight/open-source; multimodal context, stereo audio, video ≤15s, ≤2K | Có lựa chọn **local generative video** đáng tin |
| **Veo 3.1**: reference character/object/scene + audio | Reference-driven generation là chuẩn mới |
| **Seedance 2.5**: multimodal reference mạnh | " |
| **Runway**: References cho character/location; vẫn khuyên character/environment plates + storyboard + shot-by-shot assembly cho phim dài | Long-form vẫn cần asset-first, không text-only |
| Nghiên cứu multi-agent filmmaking (**FilmAgent, MovieAgent**): multi-agent > một LLM mạnh đơn lẻ trong quy trình làm phim | "Đoàn phim AI" phân vai (director/screenwriter/storyboard/cinematography) |
| **Google Flow / Veo** tích hợp image gen + video gen trong một workspace, hướng conceptualization → production | Xác nhận hướng "OS" thay vì "prompt → clip" |

**Kết luận:** không hard-code provider ở khắp codebase. Mọi lời gọi phải là `video_provider.generate(shot_spec)` qua một lớp trừu tượng.

## 2. Các mảnh ghép đã tồn tại (2026)

Không cần phát minh lại toàn bộ. Các dự án đã đi rất gần kiến trúc này:

| Dự án | Pipeline |
|---|---|
| **take** | `script.md → beats → shots → storyboard → images → video`; chạy trong Claude Code/Codex; provider router (Seedance, MiniMax H3) |
| **Huohuo Drama** | `Novel → Screenplay → Storyboard → Multimodal Assets → TTS → Video Shots → FFmpeg → Episode`; bộ nhớ continuity nhiều tầng |
| **AI Short Film** | `Screenplay → Episode split → Character assets → Scene assets → Storyboard → Images → Shot video → Merge`; nhấn mạnh character consistency |
| **MovieAgent** | "đoàn phim AI": director / screenwriter / storyboard / location / cinematography agents; screenplay → scene → shot → camera plan |
| **FilmAgent** | `Idea → Outline → Script → Acting → Cinematography → Film` |
| **Google Flow** | asset/character mgmt, scene, camera, reference, image gen, video gen, edit, clip extension, Scenebuilder |

## 3. Bảng tổng hợp: Finding → Implication → Requirement → Component

| # | Research finding | Design implication | Requirement | Component |
|---|---|---|---|---|
| S1 | LLM long-context mất continuity ở truyện dài | LLM **không được sở hữu** story state | Structured Canon Store (không phải markdown khổng lồ) | **Canon Kernel / Narrative State Engine** |
| S2 | Video model kém ở cross-shot identity (CVPR 2026 vẫn coi là bài toán mở) | Cần visual identity memory rõ ràng | Asset Registry + Look Locks | **VisualIdentityProfile** |
| S3 | Workflow thực tế (TQ) dựa reference/keyframe rồi mới video; iterate theo shot | Video generation **không thể** text-only | Reference Asset Pipeline + Storyboard/Keyframe stage + Candidate Selection | **ShotPreparation + Method Router** |
| S4 | Premium video generation đắt | Không generate mọi shot bằng premium model | Production Router + Quality Ladder | **Production Method Router** |
| S5 | Tools hiện có đã giải từng stage | Không rebuild | Adapter architecture + reuse-first policy | **Reuse-first policy toàn hệ thống** |
| S6 | Sora bị ngừng; model thay đổi nhanh | Provider churn | `video_provider.generate(shot_spec)`, không `generate_with_seedance(...)` | **Provider abstraction + CapabilityRegistry** |
| S7 | LLM hallucination → memory → "fact" → toàn truyện sai theo | Draft chưa được cập nhật Canon | `DRAFT → QA → approval → ACCEPT → Update Canon` | **DRAFT ≠ CANON transaction** |
| S8 | Novel và screenplay là hai artifact khác nhau | Không "đổi format" | Adaptation Analysis (preserve/remove/combine/visualize) → Screen Treatment → Screenplay | **AdaptationBranch / AdaptationMap** |
| S9 | Multi-agent > một LLM mạnh cho filmmaking | Phân vai đoàn phim AI | director / screenwriter / storyboard / cinematography agents | **Director OS (4 stage)** |
| S10 | 1 shot ≠ 1 generation trong production thực tế | Generate nhiều, chọn ít | `Shot → Candidate[] → QA/rank → APPROVED → Shot Master` | **GenerationCandidate ≠ ApprovedMaster** |
| S11 | Không phải mọi đoạn đều AI video (hybrid) | Director chọn **production technique**, không "video model" | reuse / stock / capture / deterministic / image / video / composite | **Method Router branches** |
| S12 | Component deterministic (diagram, chart) máy làm chính xác 100% | Không đưa cho AI làm lại | deterministic render trước generative | **Deterministic composition (Remotion/Code2MP4)** |
| S13 | YouTube: nội dung generic/templated/mass-produced có thể không monetize | Tối ưu originality, không số lượng | Idea Engine = Market × Channel identity × Originality × Knowledge advantage × Feasibility | **Idea Engine (không trend-chasing)** |
| S14 | Analytics học mù nguy hiểm (CTR thấp ≠ thumbnail xấu) | Observation ≠ Rule | rolling stats / cohorts / A-B / confidence / min sample | **Learning Engine (evidence-gated)** |
| S15 | Agent giao tiếp bằng chat làm mất trạng thái | Mọi thứ phải thành artifact | project folder + dependency graph + granular invalidation | **Artifact-first + Artifact DAG** |
| S16 | Regeneration lỗi có thể phá bản đã duyệt | Failed retry không được hủy output usable | version history; stale vẫn usable; regenerate explicit | **Artifact currency (Current/Stale/Missing/Blocked)** |
| S17 | Chi phí provider trải nhiều loại (text/image/video/TTS) và estimate ≠ actual | Cost là first-class | usage/cost tracking + budget authority atomic | **Budget reservation (C04)** |
| S18 | Fiction có vòng học riêng (audience thích character B) | Learning không tự sửa Canon | recommendation → Showrunner | **Analytics cannot mutate Canon (D)** |

## 4. Kết quả Reality Check (R1.1 – R1.4)

### R1.1 ArcReel — chọn làm **Host baseline**

ArcReel gần nhất với runtime cần tự xây. Đã có:

- FastAPI application layer (project/asset/task); Agent runtime tách khỏi deterministic tools
- `TextBackend / ImageBackend / VideoBackend / AudioBackend` — provider layer che giấu khác biệt về params/duration/reference count/async state/failure/billing
- **Generation Queue** tách image/video/audio với async execution, RPM, concurrency, persistent state, recovery, failure records, cancel; xử lý **idempotency** rõ ràng (không charge 2 lần, không submit trùng shot, SSE mất kết nối không bị coi là failure, click nhiều lần không tạo duplicate task)
- Project asset model: source/config/characters/scenes/props/references/storyboards/video/audio/outputs/version history/archives; SQLite local + PostgreSQL production; regeneration **không** overwrite; version history để compare/rollback/preserve
- Usage/cost trên text/image/video/TTS × provider × currency × estimate/actual
- Spec hardening đang formalize `CURRENT / STALE / MISSING / BLOCKED`: đổi một shot/reference chỉ stale **direct dependent**; stale vẫn usable/exportable; regenerate explicit; failed regeneration không phá artifact cũ; project-local artifact manifest (deterministic serialization, locking, atomic replacement, hashing)
- Workflow giống studio thật: `Goals → Content Structure → Reference Assets → Sample → Batch → QC → Export`, review gate trước các bước đắt tiền

**ArcReel yếu ở:** idea discovery, research intelligence, long-form writing, deep Canon, epistemic state, character cognition, adaptation, general explainer tooling, analytics/learning → ArcReel là **Host Runtime**, không phải toàn bộ trí tuệ.

### R1.2 OpenMontage — **Content toolkit donor**

>10 production pipeline, 100+ tool, 60+ provider integration (explainer, screen-demo, documentary, talking-head, podcast, cinematic, localization). Pipeline `research → proposal → script → scene_plan → assets → edit → compose → publish` với checkpoint + human approval; schema cho `research_brief / proposal_packet / brief / script / scene_plan`. **Provider Selector** rank theo task-fit/quality/control/reliability/cost/latency/continuity — gần chính là Production Router cần có.

Không lấy: OpenMontage **checkpoint làm authoritative production state** (agent-as-orchestrator, không có central runtime).

### R1.3 DramaClaw — **Creative workbench / media-gateway donor**

Canvas 18 loại node, generation history/revision/restore/locking, 360°/3D Director World, cơ chế "explore on canvas → PROMOTE selected → series/episode". DC-Media gateway normalize `first_frame/last_frame/reference_image/reference_video/reference_audio/files/async task/cancel/capability catalog` với adapter cho ComfyUI, MiniMax/Hailuo, Seedance, Kling, fal.ai, Alibaba, Gemini/OpenAI/Sora, Suno.

Không lấy: DramaClaw **task runtime + filesystem-as-authoritative-state** (in-process task, SQLite/files). ArcReel mạnh hơn ở điểm này. Director World (360/3D) hoãn tới milestone canvas nâng cao.

### R1.4 Director Stack — **tách thành 4 trách nhiệm tuần tự**

Thay vì take / Jellyfish / ai-short-film / Butterfly đều "làm Director":

| Stage | Donor | Trách nhiệm | Lấy gì | KHÔNG lấy |
|---|---|---|---|---|
| 1. Creative Director | **take** | Cảnh này chia thành shot nào, quay thế nào | `packages/core` shot grammar, Zod validation, serialization, skill/MCP | take jobs, provider router, image/video gen, `.take/jobs.json` |
| 2. Shot Preparation | **Jellyfish** | `shot.status ≠ video-readiness ≠ runtime task status`; confirm/bind character/dialogue/location/prop/wardrobe/refs/keyframe | State machine readiness | Jellyfish task runtime, provider execution |
| 3. Visual Identity | **ai-short-film** | `face_identity`, `look_lock`, canonical views (face/full-body/side), review trước video, last-frame chaining | `VisualIdentityProfile` (face/body/profile masters, hairstyle/costume/accessories lock, approved refs, arc variants) | biến chaining thành rule toàn cục |
| 4. Prompt Compiler | **Butterfly** | Mỗi shot: `positive_prompt / negative_prompt / consistency_tokens / style_tokens`, đúng 1 prompt/shot | Prompt Director → `PromptPlan` | storyboard/video/voice/music/editor/job runtime (trùng ArcReel); Branch/Timeline → chuyển sang Narrative Branch Lab |

### Narrative donors (chi tiết ở R1.5, tóm tắt)

| Donor | Lấy gì | Ràng buộc |
|---|---|---|
| **Novel Studio AI** | `Plan → Context Pack → Draft → Continuity → Style revision → Accept → Extract Memory`; Story Bible / Style Bible / Arc / Chapter / Scene Beats / Context Pack builder | Accept chapter **không** cập nhật memory riêng của nó → phát ra `CanonDelta` cho R2 commit |
| **Huohuo** | Digital Writer (`brief → draft → consistency review`), causal **Change Record** (`trigger → process → outcome`), 4-lớp context assembly, novel→screenplay adaptation, episode batch planning | Memory của Huohuo **không** thành truth store |
| **Shenbi** | 8 gate G0–G7 audit/extraction; fail gate = dừng; scoring do reviewer độc lập | Output → proposal/commit của R2, không sở hữu truth |
| **StoryBox** | top-down narrative plan + bottom-up character simulation; character agent chỉ thấy `facts character can know / beliefs / false beliefs / goals / emotions / relationships` | Output chỉ là candidate event; phải qua epistemic filter |

## 5. Phân hạng donor

| Tier | Repo | Vai trò |
|---|---|---|
| **A — foundational** | ArcReel, OpenMontage, DramaClaw, Huohuo, Novel Studio AI, take | Nền của một plane |
| **B — specialized high-value** | Shenbi, StoryBox, Jellyfish, ai-short-film, Butterfly, ComfyUI, VieNeu | Cơ chế chuyên biệt |
| **C — profile/pattern** | Toonflow, Pixelle-Video, NarratoAI, Kalinga, Code2MP4, youtube-autopilot, youtube-agentic-ai-studio, waoowaoo, LumenX, Huobao, VideoClaw | Profile, pattern, regression fixture |

## 6. Kết luận baseline (thay quyết định cũ)

| Quyết định gốc (tạm) | Nội dung | Nay LOCKED tại |
|---|---|---|
| `D-B01` | ArcReel = primary executable Host/Production Runtime baseline | `R2_04` "ArcReel-derived Host is primary runtime" |
| `D-B02` | youtube-agentic-ai-studio **không còn** là baseline → legacy YouTube adapter + regression fixture | `R2_04` (reopened từ M1) |
| `D-B03` | OpenMontage = primary general-content pipeline/tool donor | `R2_04` "DirectorAdapter is format-sensitive" (OpenMontageDirector cho general content) |
| `D-B04` | DramaClaw = primary creative-canvas/advanced drama UX donor | `R2_04` "Creative Canvas is exploration-only until PROMOTE" |
| `D-B05` | Narrative OS = Novel Studio + Huohuo + StoryBox + Shenbi **quanh** Canon/Epistemic của R2 | `R2_04` narrative authority cluster |
| `D-B06` | take = primary Creative Director / shot-language engine | `R2_04` "DirectorAdapter is format-sensitive" (TakeDirector cho fiction) |
| `D-B07` | Jellyfish → Shot Preparation / Readiness semantics | `R2_04` "Shot readiness is distinct from content status and runtime task status" |
| `D-B08` | ai-short-film + Butterfly → visual identity + prompt/consistency | `R2_04` "VisualIdentityProfile is first-class" + "PromptPlan is separate from ProviderRequest" |

**Còn giữ từ youtube-agentic-ai-studio:** VieNeu adapter, YouTube uploader (port), pilot fixtures (regression), Pexels fallback đơn giản. **Bỏ:** researcher/scriptwriter (→ OpenMontage), MoviePy default, Flask review (→ ArcReel review), `pipeline.py` làm orchestrator.

## 7. Con trỏ

- Yêu cầu hệ thống suy ra từ synthesis: [`02_SYSTEM_REQUIREMENTS.md`](02_SYSTEM_REQUIREMENTS.md)
- Kiến trúc + crosswalk quyết định đầy đủ: [`03_ARCHITECTURE.md`](03_ARCHITECTURE.md)
- Reuse map + pin/SHA + probe results: `docs/research/2026-09-07-r2-reuse-map-and-completion-gates.md`
