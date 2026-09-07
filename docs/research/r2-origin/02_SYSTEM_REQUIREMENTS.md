# 02 — System Requirements

**Trạng thái:** Tầng lý do. Không có thẩm quyền — xem [`README.md`](README.md).
Bản có thẩm quyền: `docs/r2/R2_02_FROZEN_RESPONSIBILITY_MATRIX.md`, `docs/r2/R2_03_FROZEN_DOMAIN_STATE_CONTRACTS.md`, `docs/r2/R2_05_FROZEN_HOST_HARDENING_REQUIREMENTS.md`.

Mỗi requirement dưới đây truy vết về một finding trong [`01_RESEARCH_SYNTHESIS.md`](01_RESEARCH_SYNTHESIS.md) §3 (ký hiệu `S#`).

---

## A. Yêu cầu theo capability plane

### A1. DISCOVER — Idea Engine (`S13`)

- **R-A1.1** Opportunity Miner tự đọc: market/trends/search demand/YouTube/channel history/competitors/analytics/news/community; với fiction thêm: themes/genres/audience tastes/cultural signals/story archetypes/unexplored combinations.
- **R-A1.2** Scoring **kết hợp**: `Market Demand × Channel Identity × Originality × Knowledge Advantage × Production Feasibility`. **Cấm** trend-chasing (`hot video → copy format → AI remake`).
- **R-A1.3** Output = Idea Candidate có điểm số + `Commercial Opportunity` **và** `Creative Opportunity` tách biệt.
- **R-A1.4** YouTube Data API tìm theo keyword/date/views/region/language/channel/category → Idea Miner tự động hóa được.

### A2. RESEARCH — Research Pack (`S7`, `S1`)

- **R-A2.1** Idea được duyệt sinh `research/` gồm `sources.json / facts.json / claims.json / competitor_analysis.json / audience_questions.json / benchmarks/ / screenshots/ / research_summary.md`.
- **R-A2.2** **Mỗi fact có provenance**: `{claim, source, confidence, verified}`.
- **R-A2.3** Narrative/script agent **không tự bịa fact** — phải lấy từ Research Pack.
- **R-A2.4** Factual truth (ResearchPack/ClaimLedger/Evidence) và fiction truth (Canon/Epistemic) là **hai authority tách biệt**, chỉ hội tụ ở Script.

### A3. CREATE — Narrative Production OS (`S1`, `S7`, `S8`)

- **R-A3.1** Canon là **structured state**, không phải markdown khổng lồ nhét lại vào context. Entity gồm ≥ `Identity / Appearance / Personality / Goal / Fear / Relationships / Secrets / KnowledgeState / Character Arc`.
- **R-A3.2** Nguyên tử: `Entity / Fact / Event`. `CanonBranch / CanonVersion` có version + nhánh.
- **R-A3.3** **KnowledgeState / Epistemic Engine** first-class: ai biết / nghi ngờ / tin sai / chưa biết một mệnh đề — là authoritative state.
- **R-A3.4** Creative Development Pipeline **không nhảy** `Idea → Story`. Phải: `Idea → Premise → Theme → Genre → Audience → Story Question → World → Characters → Conflict → Story Architecture → Outline → Treatment → Draft`.
- **R-A3.5** `DRAFT ≠ CANON`. Đường ghi: `Draft → Narrative QA → Continuity QA → Logic QA → Human/AI approval → ACCEPT → Update Canon`.
- **R-A3.6** Canon transaction: `PROPOSE → validate → review → COMMIT`. Candidate bị từ chối / transaction lỗi **không** làm hỏng Canon.
- **R-A3.7** `NarrativeChangeSet` (thay đổi suy ra từ prose) **khác** `CanonDelta` (mutation authoritative tường minh).
- **R-A3.8** Novel → Screenplay qua `Adaptation Analysis` (preserve/remove/combine/visualize) → `Screen Treatment → Sequence Outline → Screenplay`, dùng `AdaptationBranch` + `AdaptationMap` giữ source Canon bất biến. Suy nghĩ nội tâm phải thành action/expression/blocking/visual metaphor/dialogue/silence.
- **R-A3.9** `NarrativePlan / SceneContract` tách khỏi Canon (future authorial intent ≠ established world truth).

### A4. DIRECT — Director OS (`S9`, `S10`, `S3`)

- **R-A4.1** Hai giai đoạn: **Creative direction** ("khán giả nên thấy gì?") → **Production direction** ("tạo bằng cách nào?").
- **R-A4.2** 4 trách nhiệm **tuần tự**, không trộn: `take` (creative director → ShotSpec) → `Jellyfish` (shot preparation/readiness → bind entities/dialogue/refs → READY) → `ai-short-film` (visual identity/look-lock) → `Butterfly` (prompt compiler → PromptPlan).
- **R-A4.3** `Shot ≠ Generation`. Shot = creative requirement; generation = candidate implementation. Data model: `Shot → Candidate V1..Vn → APPROVED → Shot Master`, giữ `provider/prompt/references/seed/cost/QA score/rejection reason`.
- **R-A4.4** `shot.status ≠ video-readiness ≠ runtime task status` — ba trạng thái độc lập.
- **R-A4.5** `VisualIdentityProfile` first-class: `face_master / body_master / profile_views / hairstyle_lock / costume_lock / accessories_lock / approved_reference_ids / arc variants / last_frame_anchor`. Variant (`LAN_COSTUME_EP05`, `LAN_INJURED_EP08`) chỉ tạo khi truyện yêu cầu.
- **R-A4.6** Previous-frame chaining là **continuity strategy có điều kiện** — chỉ khi cùng continuity segment ∧ cùng temporal flow ∧ camera transition tương thích ∧ frame trước thực sự hữu ích ∧ provider hỗ trợ chaining. **Không** phải mọi shot nối shot trước.
- **R-A4.7** `PromptPlan` (provider-neutral) tách khỏi `ProviderRequest` (payload cụ thể). Đúng 1 prompt/shot.

### A5. PRODUCE — Production OS (`S3`, `S4`, `S5`, `S6`, `S11`)

- **R-A5.1** **Production Method Router**: chọn `REUSE / STOCK / SCREEN_CAPTURE / DETERMINISTIC / GENERATED_IMAGE / GENERATED_VIDEO / COMPOSITE` **trước** provider/model/tool.
- **R-A5.2** Không "video model chính". Provider abstraction: `video_provider.generate(shot_spec)`; router chọn theo quality/cost/latency/character consistency/reference support/audio/resolution/shot type + lịch sử acceptance.
- **R-A5.3** Một `CapabilityRegistry` chuẩn hóa từ ArcReel + DC-Media + OpenMontage + local/deterministic. Freshness policy (v1): credential/endpoint/process 30s, local VRAM 5s, hard quota 15s, soft latency 300s, non-binding cost estimate 60s. Hard-budget admission dùng **atomic reservation**, không dùng cost estimate cache.
- **R-A5.4** Image/asset generation thường **đi trước** video generation: `text → character ref → location ref → storyboard frame → keyframe → video` đáng tin hơn `text → video`. ComfyUI = Visual Asset Factory (character sheets, expressions, costumes, location plates, props, keyframes, storyboards, control images, masks, depth, pose).
- **R-A5.5** Hybrid production: một sản phẩm = generated video + generated image + stock + real footage + screen capture + motion graphics + text + composite. Method Router chọn technique, không "video model".
- **R-A5.6** Deterministic component (diagram/chart/code) → deterministic render (Remotion/Code2MP4), **không** đưa cho AI làm lại.
- **R-A5.7** Asset **reuse-first**: `Need asset → Retrieve → Reuse → Adapt → Generate only if necessary`. Character `LAN` có `LAN_FACE_MASTER / LAN_BODY_MASTER / ...` trong Approved Asset Registry, reuse xuyên production.

### A6. EVALUATE — QA/Evaluation OS (`S12`, `S16`)

- **R-A6.1** ≥ 6 lớp QA:
  1. **Factual** — claim đúng? source có?
  2. **Narrative** — plot hole? character motivation? setup/payoff?
  3. **Continuity** — character / costume / location / time / props / knowledge
  4. **Visual** — face drift / object mutation / bad hands / flickering / camera errors
  5. **Audio** — dialogue / lip sync / TTS error / volume / music overlap
  6. **Production** — resolution / black frames / codec / subtitle / duration / safe areas
- **R-A6.2** Fail gate = **không đi tiếp**. Scoring do reviewer **độc lập** (không phải chính agent tạo ra output).
- **R-A6.3** Task result tách khỏi artifact currency.

### A7. DISTRIBUTE (`S13`)

- **R-A7.1** Packaging tự sinh: title × 10, thumbnail concept × 5, description, chapters, tags, pinned comment, Shorts cuts, TikTok cuts. Packaging Agent chấm clarity/curiosity/accuracy/brand match/click potential.
- **R-A7.2** Upload qua YouTube Data API `videos.insert` (file + metadata + schedule).
- **R-A7.3** Nếu nội dung realistic được tạo/alter đáng kể bởi AI → **AI disclosure** bắt buộc; lưu distribution record.

### A8. LEARN — Analytics + telemetry (`S14`, `S18`)

- **R-A8.1** YouTube Analytics/Reporting: views / avg view duration / watch time / likes / comments / shares / subscribers / revenue; **100 điểm retention** trên timeline mỗi video; `video_thumbnail_impressions` + `..._ctr`.
- **R-A8.2** Map ngược retention → timestamp → scene → script segment → visual → kết luận (ví dụ "explanation quá trừu tượng + static visual quá dài + không có narrative question").
- **R-A8.3** `Observation ≠ Rule`. Learning chỉ khi có `Repeated Evidence`: rolling statistics / cohorts / A/B tests / confidence / minimum sample size.
- **R-A8.4** **Channel Memory / Channel Brain**: audience / topics / successful+failed hooks / thumbnail patterns / retention patterns / audience questions / comment sentiment / video relationships / subscriber conversion. Sau vài trăm video → moat thật (không phải model).
- **R-A8.5** Fiction có vòng học riêng (character resonance ↑). Learning phát `Creative Recommendation` cho Showrunner. **Analytics không tự sửa Canon/policy.**

## B. Yêu cầu xuyên suốt (cross-cutting)

- **R-B1 Artifact-first** (`S15`) — agents **không giao tiếp bằng chat**; mọi thứ thành artifact. Layout dự án chuẩn:
  ```
  projects/episode_001/
    project.yaml
    research/research_pack.json
    narrative/{canon.json, outline.json, script.md}
    direction/{scenes.json, shots.json}
    assets/{characters/, locations/, props/}
    generations/{images/, video/, audio/}
    timeline/timeline.json
    qa/{narrative_qa.json, visual_qa.json, audio_qa.json}
    output/{master.mp4, youtube.mp4, short_01.mp4}
    distribution/metadata.json
    analytics/performance.json
  ```
- **R-B2 Dependency graph + granular invalidation** (`S16`) — `scene 11 → shots 37–42 → assets → timeline 08:12–08:43`; chỉ invalidate phần đó. Lỗi shot 073 → `regenerate shot_073`, không `recreate entire video`.
- **R-B3 Versioning + recovery** (`S16`) — regeneration không overwrite; failed regeneration **preserves usable prior master**; atomic promotion; restart recovery.
- **R-B4 Cost accounting + budget authority** (`S17`) — usage/cost trên mọi loại; atomic budget reservation trước paid side effect (đã hiện thực = milestone C04).
- **R-B5 Human gates** — A greenlight / B narrative lock / C final cut / D publish (xem `00_PRODUCT_VISION.md` §5).
- **R-B6 Ba database domain** (`S15`) — **không trộn**:
  | DB | Chứa |
  |---|---|
  | Production | projects, jobs, assets, generations, costs, versions |
  | Narrative | characters, locations, timeline, relationships, canon, knowledge states |
  | Intelligence | topics, competitors, performance, experiments, audience, learned_patterns |
  Nhưng **một host / một PostgreSQL** transaction boundary (không microservices quá sớm). Trong DB: prefix `canon_* / epistemic_*` (narrative truth), `project_* / artifact_* / asset_* / generation_*` (production truth), `quality_* / distribution_* / analytics_*`.
- **R-B7 Reuse-first order** (`S5`) — luật toàn hệ thống, hỏi theo thứ tự:
  `artifact đã tồn tại? → asset/library/repo dùng được? → deterministic tool giải được? → local model giải được? → cheap API? → premium generation`.
- **R-B8 Content vs execution fingerprint** — artifact currency dùng semantic/content dependency; provider/model/seed/resolution thuộc execution provenance.
- **R-B9 Exactly one commit authority per authoritative state family** — hệ khác chỉ read/propose.
- **R-B10 Five authority planes** — Factual / Narrative / Authorial Intent / Production / Runtime.

## C. Con trỏ

- Kiến trúc hiện thực các requirement này: [`03_ARCHITECTURE.md`](03_ARCHITECTURE.md)
- Ma trận trách nhiệm chi tiết: `docs/r2/R2_02_FROZEN_RESPONSIBILITY_MATRIX.md`
- Hợp đồng domain/state: `docs/r2/R2_03_FROZEN_DOMAIN_STATE_CONTRACTS.md` + `R2_03_CONTRACT_REGISTRY.json`
- Host hardening H1–H8 (recovery/idempotency/identity): `docs/r2/R2_05_FROZEN_HOST_HARDENING_REQUIREMENTS.md`
