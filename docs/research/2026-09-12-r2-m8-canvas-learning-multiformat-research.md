# R2 M8 — Canvas, Learning và Multi-format: nghiên cứu donor có giới hạn

**Ngày chụp bằng chứng:** 2026-09-12  
**Trạng thái:** `PARTIAL / RESEARCH INPUT ONLY` — chưa phải ADR, spec, integration pin hay phê duyệt triển khai.  
**R2 checkout được đối chiếu:** `5d81d8339042c18c0284d50945b3b8b1914709df`, nhánh `design/r2-m5b-narrative-context`.  
**Graph R2 do phiên cha xác nhận:** project `home-anhtuan-content-production-os`, generation `2026-09-12T15:26:05Z`, full; Tier 2, coverage trên các path được chuyển giao là `no_recorded_issue`/`metadata_match`, best-effort. Donor không được lập graph trong vòng nghiên cứu này; kết luận donor dưới đây đến từ source/tree GitHub tại SHA bất biến và probe cục bộ có giới hạn.

## 1. Kết luận điều hành

1. **Không đưa DramaClaw canvas vào production authority nguyên dạng.** Bề mặt đáng học là graph workbench, history/restore, grouping, viewport bookmarks, service seams, impact preview và thao tác promote có tên rõ. Nhưng wrapper `promoteToAsset()` chỉ validate một số trường rồi gọi thẳng `/freezone/push`; nó không chứng minh preview bắt buộc, approval custody, audit receipt, optimistic concurrency hay rollback. R2 phải giữ chuỗi riêng: `CanvasCandidate -> impact preview -> explicit audited PROMOTE -> R2 production artifact`.
2. **Director World là probe spatial có giá trị, chưa phải production contract.** Source tạo topology JSON từ MASTER/REVERSE, tách điều nhìn thấy khỏi vùng suy diễn, khóa seam/front/back và chống nhân đôi anchor. Tuy vậy phần phân tích gọi model qua OpenRouter; `temperature=0` không biến output model thành deterministic. Nó còn ghi file trực tiếp và dùng schema donor riêng, nên chỉ phù hợp làm candidate/projection trước R2 validation và promotion.
3. **OpenMontage có ba seam dùng được:** `research_brief` có URL/credibility; `decision_log` có lựa chọn bị loại, score, confidence và cờ human visibility/approval; `video_compose` + Remotion/FFmpeg có runtime lock, normalize format và pre/post checks. Đây **không phải** một Learning Engine hoàn chỉnh: trong bề mặt đã đọc chưa có contract ingest performance theo lineage, holdout evaluation, recommendation scope, accept/reject lifecycle hay authority-safe application.
4. **Multi-format nên là projection từ một lineage nguồn đã duyệt, không phải generate lại nội dung độc lập theo từng tỷ lệ.** OpenMontage chứng minh được seam kỹ thuật về target width/height, `pad`/`cover`, fps/pixel-format normalization và composition 16:9/9:16. Nó chưa chứng minh semantic reframing, safe zones, caption collision, shot replacement, hay quality parity giữa format.
5. **Khuyến nghị hướng tích hợp:** clean-room contract + adapter mỏng, không wholesale vendor. DramaClaw CE là Elastic License 2.0/source-available; OpenMontage tại pin nghiên cứu là AGPL-3.0. Mọi reuse code phải qua rà soát license và bốn gate R2-DEC-031; pattern-reference clean-room phải được phân loại tường minh.

## 2. Nguồn và độ bao phủ

### 2.1 Pins đã đọc

| Nguồn | Exact commit SHA | Path chính | Tình trạng |
|---|---|---|---|
| DramaClaw | `b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83` | [`frontend/src/features/canvas/application/canvasServices.ts`](https://github.com/dramaclaw/dramaclaw/blob/b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83/frontend/src/features/canvas/application/canvasServices.ts), [`frontend/src/stores/canvasStore.ts`](https://github.com/dramaclaw/dramaclaw/blob/b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83/frontend/src/stores/canvasStore.ts), [`frontend/src/features/freezone/commit/promoteToAsset.ts`](https://github.com/dramaclaw/dramaclaw/blob/b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83/frontend/src/features/freezone/commit/promoteToAsset.ts), [`src/novelvideo/director_world/scene_spatial_contract.py`](https://github.com/dramaclaw/dramaclaw/blob/b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83/src/novelvideo/director_world/scene_spatial_contract.py) | Đã đọc source thật; SHA-256 khớp manifest R2 cả 4 file. Tree GitHub `truncated=false`. Chưa chạy donor tests/runtime. |
| OpenMontage upstream | `08e2151fa02de28a5d6a312b3d575692bf147ad7` | [`skills/pipelines/explainer/research-director.md`](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/skills/pipelines/explainer/research-director.md), [`schemas/artifacts/research_brief.schema.json`](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/schemas/artifacts/research_brief.schema.json), [`schemas/artifacts/decision_log.schema.json`](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/schemas/artifacts/decision_log.schema.json), [`tools/video/video_compose.py`](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/tools/video/video_compose.py), [`tools/analysis/composition_validator.py`](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/tools/analysis/composition_validator.py), [`tools/analysis/visual_qa.py`](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/tools/analysis/visual_qa.py), [`remotion-composer/src/Root.tsx`](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/remotion-composer/src/Root.tsx) | Đã đọc source/schema thật; tree GitHub `truncated=false`. Pin này chưa có entry trong `source-manifest.json`. Log lịch sử trong repo ghi 56 contract tests pass, nhưng vòng này không chạy lại. |
| Huohuo drama donor | `f104b853b3563e124d9cde25f9331d323fb483b9` | [`workbench-server/src/services/novel/novel-outline-drama-fields.ts`](https://github.com/appolloqin/huohuo-drama/blob/f104b853b3563e124d9cde25f9331d323fb483b9/workbench-server/src/services/novel/novel-outline-drama-fields.ts) | Đã đọc source thật để kiểm chứng field `爽`; không suy rộng thành quy luật mọi short drama. |

Manifest nội bộ khóa các file DramaClaw và hash tại [`docs/r2/evidence/reuse-map-2026-09-07/source-manifest.json`](../r2/evidence/reuse-map-2026-09-07/source-manifest.json). Probe hash vòng này cho bốn file lần lượt là `f3a301…`, `649c49…`, `d04d3f…`, `975e63…`, khớp manifest. Probe OpenMontage lịch sử là [`56 passed in 6.31s`](../r2/evidence/reuse-map-2026-09-07/openmontage-probe.log), nhưng **không được trình bày như fresh validation tại HEAD hiện tại**.

### 2.2 Giới hạn bắt buộc khi đọc kết luận

- Không clone/vendor donor vào repo. Source được tải read-only vào `/tmp` từ immutable raw URLs.
- Không chạy UI, Node/Remotion render, OpenRouter request, FFmpeg benchmark hay test donor trong vòng này.
- Inventory test DramaClaw dựa trên complete GitHub tree: 112 file test dưới `features/canvas`, 24 dưới `features/freezone`; tìm theo basename không thấy test mang tên `promoteToAsset` hoặc `scene_spatial_contract`. Đây là **khoảng trống đặt tên/coverage cần kiểm tra**, không chứng minh hành vi hoàn toàn không được cover gián tiếp.
- Nghiên cứu nguồn chính thức về genre bị dừng sớm; phần genre là acceptance-profile có nguồn, không phải định nghĩa thẩm mỹ phổ quát.

## 3. R2 invariants áp dụng trước mọi donor behavior

Các ràng buộc này là đầu vào, không phải vấn đề để donor tự quyết:

- Frozen architecture quy định `Canvas State != Production Truth`, candidate không được tự thành Canon/ApprovedMaster ([R2.1 §5](../r2/R2_01_FROZEN_ARCHITECTURE.md#5-frozen-hard-invariants)).
- Canvas chỉ là exploration plane; được generate/branch/compare/restore/group/spatial nhưng không mutate production trực tiếp; bridge bắt buộc là `CanvasCandidate -> preview impact -> PROMOTE -> artifact`, promotion explicit và auditable ([R2.1 §19](../r2/R2_01_FROZEN_ARCHITECTURE.md#19-creative-canvas)).
- Authority mapping đặt `GenerationCandidate`, `ApprovedMaster`, `EditTimelineArtifact` trong Production Authority; cấm `CanvasNode == production artifact` ([R2.3 §31–32](../r2/R2_03_FROZEN_DOMAIN_STATE_CONTRACTS.md#31-authority-ownership-mapping)).
- Learning chỉ tạo recommendation/experiment/routing/hypothesis, không tự sửa Canon, NarrativePlan, CreativePolicy, claim truth hay governance ([R2.1 §25](../r2/R2_01_FROZEN_ARCHITECTURE.md#25-learning-engine-boundary); [R2-DEC-029](../r2/R2_04_CONSOLIDATED_DECISION_LOG.md#r2-dec-029--learning-produces-recommendations-not-authority-mutation)).
- Remotion là deterministic composition path cho mixed composition; ArcReel/FFmpeg giữ media mechanics và drama assembly ([R2-DEC-028](../r2/R2_04_CONSOLIDATED_DECISION_LOG.md#r2-dec-028--openmontageremotion-is-primary-deterministic-composition-path)).
- Không thêm parallel queue/artifact registry; một host/một operator vẫn là mặc định. Việc đưa Node runtime thứ hai hoặc đổi mô hình vận hành cần phê duyệt lại. `R2-HOST-001` vẫn là production-launch blocker liên quan execution identity khi reconfigure provider ([R2.1 §27](../r2/R2_01_FROZEN_ARCHITECTURE.md#27-known-host-hardening-requirement)).
- Nếu lấy code donor, bốn gate Baseline/Coverage/Parity/Completion là bắt buộc và mọi critical behavior chưa kiểm chứng giữ `BLOCKED`; pattern-reference clean-room được phân loại riêng ([PROJECT_DECISIONS QĐ-8/QĐ-9](../r2/evidence/PROJECT_DECISIONS_2026-09-09.md#qđ-8--mọi-reusemerge-donor-phải-đạt-chất-lượng-và-chức-năng--bản-gốc)).

## 4. DramaClaw canvas — inventory và khoảng cách tới R2

### 4.1 `canvasServices.ts`: composition root nhỏ nhưng hard-wired

File 18 dòng dựng các singleton: in-memory event bus, node factory + catalog + UUID generator, graph image/content resolvers, tool processor, AI gateway và image-split gateway ([source lines 3–18](https://github.com/dramaclaw/dramaclaw/blob/b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83/frontend/src/features/canvas/application/canvasServices.ts#L3-L18)).

**Có thể học:** tên seam/factory rõ, tách node/tool/content/image/AI.  
**Không thể mang thẳng:** concrete singleton và gateway donor không truyền project authority, actor, expected version, lineage hay audit context. R2 adapter phải dependency-inject các ports và mọi write phải đi qua service authority của host.

### 4.2 `canvasStore.ts`: behavior inventory

Source là Zustand store lớn (4.020 dòng), dựa trên React Flow. Bề mặt đã nhận diện:

- graph nodes/edges; normalize/dedupe; reject invalid upstream connections và giới hạn reference envelope;
- add/update/delete, manual connect/disconnect, derived nodes, multi-generation siblings;
- group/ungroup, storyboard group/grid/reorder, panorama capture group;
- selection/box-selection, node resize và aspect-ratio sizing;
- history `past/future` giới hạn 50, undo/redo, drag/resize được gom thành một history step ([lines 96–106](https://github.com/dramaclaw/dramaclaw/blob/b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83/frontend/src/stores/canvasStore.ts#L96-L106), [1283–1382](https://github.com/dramaclaw/dramaclaw/blob/b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83/frontend/src/stores/canvasStore.ts#L1283-L1382));
- hydrate/switch reset transient bookkeeping, dangerous-empty/manual-clear intent, draft history restore ([117–153](https://github.com/dramaclaw/dramaclaw/blob/b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83/frontend/src/stores/canvasStore.ts#L117-L153), [1478–1540](https://github.com/dramaclaw/dramaclaw/blob/b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83/frontend/src/stores/canvasStore.ts#L1478-L1540));
- viewport state, 10 bookmarks nằm ngoài undo history ([173–177](https://github.com/dramaclaw/dramaclaw/blob/b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83/frontend/src/stores/canvasStore.ts#L173-L177));
- explicit manual clear giữ snapshot, đặt `pendingClearIntent`, rồi acknowledge sau save ([3970–3996](https://github.com/dramaclaw/dramaclaw/blob/b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83/frontend/src/stores/canvasStore.ts#L3970-L3996)).

**R2 mapping:** node/edge/history/bookmark là `CanvasCandidate`/UI projection, không phải Production Artifact. Undo canvas không được undo authority transaction. Hydrate phải bind đúng `project_id`, candidate revision và approved-source lineage; autosave chỉ được ghi workspace candidate.

### 4.3 `promoteToAsset.ts`: tên đúng, custody chưa đủ

Donor tách `previewAssetImpact()` khỏi `promoteToAsset()`, validate beat/identity/portrait/scene target và gọi `fetchPushImpact`/`pushToPipeline` ([lines 15–36](https://github.com/dramaclaw/dramaclaw/blob/b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83/frontend/src/features/freezone/commit/promoteToAsset.ts#L15-L36), [38–79](https://github.com/dramaclaw/dramaclaw/blob/b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83/frontend/src/features/freezone/commit/promoteToAsset.ts#L38-L79)). Đây là seam UX tốt, nhưng source này **không enforce**:

- preview receipt/hash phải khớp promote;
- human approval id/actor/scope;
- candidate revision và expected current master (TOCTOU);
- idempotency key, transaction outcome, audit event;
- failure không làm mất usable prior master;
- stale/concurrent promotion fail closed.

R2 cần `PromotionImpact{candidate_id, candidate_revision, target_ref, expected_parent/version, lineage_hash, impact, expiry}` và `PromotionAuthorization{actor, decision, scope, approved_impact_hash}`; server xác nhận lại toàn bộ rồi transaction tạo artifact + audit receipt. UI không phải enforcement boundary.

### 4.4 Director World / spatial contract

Contract donor:

- coi MASTER là front và REVERSE là cùng camera yaw 180°; đặt safe seam tại x=0/100, front x=25, right join x=50, back x=75 ([lines 189–205](https://github.com/dramaclaw/dramaclaw/blob/b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83/src/novelvideo/director_world/scene_spatial_contract.py#L189-L205));
- schema ghi coverage gaps, walls/must-preserve, source view/side, count/size, joins, merge-once/do-not-duplicate và direction locks ([208–271](https://github.com/dramaclaw/dramaclaw/blob/b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83/src/novelvideo/director_world/scene_spatial_contract.py#L208-L271));
- yêu cầu conservative: vùng không đủ thấy phải thành gap/inferred fill, không bịa confident wall ([274–289](https://github.com/dramaclaw/dramaclaw/blob/b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83/src/novelvideo/director_world/scene_spatial_contract.py#L274-L289));
- merge overlap anchors một lần, tạo duplicate warnings/locks ([694–812](https://github.com/dramaclaw/dramaclaw/blob/b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83/src/novelvideo/director_world/scene_spatial_contract.py#L694-L812));
- gọi OpenRouter chat completions, `temperature: 0`, timeout 120s, và chỉ ép JSON object cho model tên `openai/*` ([293–344](https://github.com/dramaclaw/dramaclaw/blob/b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83/src/novelvideo/director_world/scene_spatial_contract.py#L293-L344));
- ghi prompt, raw response, contract JSON và sheet xuống output directory.

**Đánh giá:** topology vocabulary và fixture strategy đáng reuse ở mức pattern. Model result phải là `SpatialCandidate` có source refs, model/execution fingerprint, confidence từng assertion và coverage-gap; deterministic normalization chỉ chạy sau schema validation. Chưa được dùng nó làm `ProductionBinding`, chưa được sinh/replace master, và chưa được coi inferred fill là fact.

### 4.5 License/runtime/test gap

- DramaClaw tự mô tả CE là **source available, không phải OSI open source**, theo Elastic License 2.0; cấm cung cấp CE như hosted/managed service cho bên thứ ba ([license lines 4–27](https://github.com/dramaclaw/dramaclaw/blob/b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83/docs/en/license.md#L4-L27)). Đây cần legal review trước copy/port, nhất là sản phẩm hosted.
- Frontend pin dùng pnpm 11.5, React 19, Vite 6, Zustand 5, `@xyflow/react`, PlayCanvas, OGL, photo-sphere viewer, FFmpeg WASM; test bằng Vitest ([package](https://github.com/dramaclaw/dramaclaw/blob/b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83/frontend/package.json)). Spatial Python cần Pillow/httpx/OpenRouter key và network.
- Test tree rộng nhưng vòng này chưa chạy. Critical missing proof: preview/promote ordering và race; server authority; large-canvas memory/latency; corrupt draft migration; undo across group operations; offline/reload; spatial malformed JSON/model drift; seam quality corpus; provider failure/cost/cancellation.

## 5. OpenMontage — research, analytics/learning và multi-format seams

### 5.1 Research module

Research Director đặt research trước creative decision/script/spend và output `research_brief`; nó nói rõ researcher không quyết creative option ([lines 1–17](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/skills/pipelines/explainer/research-director.md#L1-L17)). Mỗi data point ghi exact claim, source URL/name, credibility (`primary_source|secondary_source|anecdotal`), surprise factor và intended use ([124–152](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/skills/pipelines/explainer/research-director.md#L124-L152)); bibliography yêu cầu minimum 5 sources, ít nhất 2 primary, flag source cũ hơn 2 năm ([234–251](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/skills/pipelines/explainer/research-director.md#L234-L251)).

**Reuse tốt:** provenance và credibility vocabulary, negative-space/gap recording, schema validation.  
**Cần harden:** URL không đủ làm evidence identity; R2 nên snapshot/fingerprint source, timestamp retrieval, quote/span locator, claim-to-source edges, scope và contradiction status. Search instruction không được quyền commit Claim truth.

### 5.2 Analytics và Learning: những gì có, những gì chưa chứng minh

Đã thấy các tool phân tích transcription, scene detect, frames, audio, visual QA và composition validation trong complete tree. `composition_validator` kiểm tra cuts, ordering, assets, narration/music duration và trả errors/warnings ([lines 152–243](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/tools/analysis/composition_validator.py#L152-L243)). `visual_qa` dùng ffprobe lấy duration, size, codec, pixel format, fps, audio và so với expected ([lines 203–278](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/tools/analysis/visual_qa.py#L203-L278)).

`decision_log` là seam gần Learning nhất: bắt buộc alternatives, score/reason, selected/rejected reason; có `user_visible`, `user_approved`, `confidence` ([schema lines 1–99](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/schemas/artifacts/decision_log.schema.json#L1-L99)). Nhưng bounded inspection **chưa tìm được dedicated learning contract/module**. Không thấy bằng chứng đủ cho ingest distribution metrics, join metric với exact approved master/format/audience window, offline evaluation, holdout, drift, recommendation scope/expiry, hay accept/reject lifecycle.

R2 phải định nghĩa riêng:

```text
LearningObservation
  metric source + retrieval window + format/channel + approved artifact lineage
  production cost/time + QA/reject/regenerate outcome

LearningRecommendation
  recommendation_id + hypothesis
  evidence_refs[] + confidence + applicability_scope + exclusions
  expected_effect + guardrails + expiry
  status = PROPOSED | ACCEPTED | REJECTED | EXPIRED | SUPERSEDED
  human_decision + actor + timestamp + rationale
```

Accept chỉ tạo experiment/policy proposal theo đúng authority path; không tự mutate Canon/NarrativePlan/CreativePolicy/routing defaults. Reject cũng phải lưu để tránh recommender lặp lại đề xuất đã bác mà không có evidence mới.

### 5.3 Deterministic multi-format / Remotion seams

- `edit_decisions` khóa `renderer_family`, `render_runtime` (`remotion|hyperframes|ffmpeg`) và `composition_mode` tại proposal; thay runtime cần logged decision ([schema lines 196–224](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/schemas/artifacts/edit_decisions.schema.json#L196-L224)).
- `video_compose` tự khai `Determinism.DETERMINISTIC`, phụ thuộc FFmpeg và route runtime từ approved edit decisions ([lines 1–23](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/tools/video/video_compose.py#L1-L23), [58–70](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/tools/video/video_compose.py#L58-L70)). Cần hiểu đây là claim của donor; R2 vẫn phải đo reproducibility.
- FFmpeg branch normalize mọi segment về target width/height, 30 fps, yuv420p, SAR=1; `cover` crop để fill, `pad` letterbox để giữ toàn ảnh ([lines 555–590](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/tools/video/video_compose.py#L555-L590)).
- Renderer family map fail với tên lạ thay vì silently chọn composition ([733–763](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/tools/video/video_compose.py#L733-L763)). Rich/mixed content mặc định Remotion nếu available ([1375–1413](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/tools/video/video_compose.py#L1375-L1413)).
- Root đăng ký 1920x1080/30fps cho Explainer/Cinematic và 1080x1920/30fps cho TalkingHead ([Root lines 123–200](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/remotion-composer/src/Root.tsx#L123-L200)). Đây chỉ chứng minh format surface, không chứng minh cùng composition semantic hoạt động ở cả hai tỷ lệ.

**R2 contract đề xuất:** mọi derivative format tham chiếu cùng `ApprovedMaster`/approved timeline/source lineage và một `FormatProjectionSpec`; chỉ crop/reframe/caption layout/render parameters thay đổi. Nếu cần đổi shot/narrative content thì tạo candidate mới và approval riêng, không giả danh deterministic projection.

### 5.4 License/runtime

OpenMontage pin này có [`LICENSE` AGPL-3.0](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/LICENSE). Composer phụ thuộc Node/npm, React 18 và Remotion `^4.0.484` ([package](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/remotion-composer/package.json)). Runtime còn gọi FFmpeg/ffprobe/npx và có thể cần network/provider credentials. Wholesale integration vừa tăng license obligations vừa tạo tiến trình/runtime thứ hai; không phù hợp mặc định single-host nếu chưa re-approve.

## 6. Drama acceptance profiles, không biến trope thành universal truth

### 6.1 Western generic drama fixture

Không có một “công thức phương Tây” duy nhất. Hai nguồn institution-level chỉ hỗ trợ một profile kiểm thử:

- Sundance Episodic Lab yêu cầu original pilot, series logline, series overview, thematic statement và creative questions; original/adaptation rights cũng phải rõ ([Sundance Episodic Program](https://www.sundance.org/programs/episodic-storytelling)).
- Academy Nicholl rubric hỏi premise/story có beginning-middle-end hợp lý, emotional connection, distinctive voice và vivid characters với voice riêng; chính Academy cũng nói screenplay format chuyên nghiệp có biến thể, không có một absolute standard duy nhất ([Nicholl how to apply/rubric](https://www.oscars.org/nicholl/about), [format resources](https://www.oscars.org/nicholl/screenwriting-resources)).

Vì vậy Golden/holdout “Western generic drama” có thể đo: rights/source lineage; logline/overview/theme; character goal/choice/change; scene causality; distinct voice; emotional coherence; screenplay structure/format. Không hard-code three-act, số beat, loại trope hay page count của một cuộc thi thành luật domain chung.

### 6.2 Chinese short drama / 爽文 fixture

Nguồn pháp quy hiện hành định nghĩa 微短剧 là series có mỗi tập dưới 20 phút, theme/main line rõ, plot liên tục/hoàn chỉnh và nhân vật nổi bật; phân loại/备案 hoặc giấy phép, yêu cầu subtitle/ngôn ngữ và AI-generated label cũng là delivery constraints ([NRTA Order No.16, effective 2026-09-01](https://www.nrta.gov.cn/art/2026/7/31/art_113_73785.html)). Thông báo 2025 yêu cầu classified review/备案 và license/registration marking trước phát hành ([NRTA notice](https://www.nrta.gov.cn/art/2025/2/5/art_113_70148.html)).

Huohuo donor **cụ thể** model hóa mỗi chapter bằng time/place/cast/catalyst/desire/obstacle/stakes shift/choice/conflict layer/emotion craft/ending question/info delta/theme echo; riêng chapter 1–8 yêu cầu `恨/爽/急/盼` và một `爽型` trong closed set ([source lines 24–87](https://github.com/appolloqin/huohuo-drama/blob/f104b853b3563e124d9cde25f9331d323fb483b9/workbench-server/src/services/novel/novel-outline-drama-fields.ts#L24-L87), [248–306](https://github.com/appolloqin/huohuo-drama/blob/f104b853b3563e124d9cde25f9331d323fb483b9/workbench-server/src/services/novel/novel-outline-drama-fields.ts#L248-L306)). Đây là **donor-specific commercial-emotion grammar**, không phải luật NRTA và không phải chân lý của mọi short drama.

R2 nên biểu diễn nó như optional `CreativePolicy.format_constraints`/genre profile có version, cho phép profile khác. Gate chung là continuity, character/causal state, visible conflict/progression, episode-end unresolved event nếu profile yêu cầu, compliance metadata và human quality review; không thưởng “爽” bằng mọi giá hoặc để analytics tự rewrite narrative.

## 7. Ba phương án tích hợp

| Phương án | Mô tả | Ưu điểm | Rủi ro / verdict |
|---|---|---|---|
| A — clean-room contracts + selective pattern reference | R2 tự sở hữu `CanvasCandidate`, Promotion, LearningRecommendation, FormatProjection; học behavior/test corpus donor, gọi renderer qua host adapter | License/runtime blast radius thấp; authority rõ; hợp single-host | Tốn công đạt UX parity. **Khuyến nghị mặc định.** QĐ-9 phải ghi rõ pattern-reference, không copy code. |
| B — port code có chọn lọc | Port canvas algorithms/store helpers hoặc OpenMontage validator/renderer adapter; giữ R2 ports ngoài | Nhanh hơn cho behavior phức tạp | Kích hoạt R2-DEC-031 bốn gate và license review; nguy cơ kéo framework/runtime. Chỉ sau bounded prototype chứng minh lợi ích. |
| C — sidecar/vendor wholesale | Chạy DramaClaw/OpenMontage runtime độc lập rồi bridge | Parity donor ban đầu cao nhất | Parallel authority/store/process, ELv2/AGPL, recovery/observability, resource và one-host conflict. **NO-GO mặc định**, chỉ mở lại qua architecture + ops + license approval explicit. |

## 8. Reuse classification và quality-parity gates

Mỗi surface phải chọn đúng một nhãn: `PATTERN_REFERENCE`, `CLEAN_ROOM_REIMPLEMENTATION`, `PORT`, `COPY/VENDOR`, `PROCESS_ADAPTER`. Với bốn nhãn cuối có donor code, evidence package phải có:

1. **Baseline:** immutable URL/SHA/path/license; language/runtime/dependencies; behavior inventory; donor test inventory và fixture hashes.
2. **Coverage:** chạy donor tests liên quan hoặc port fixture; thêm branches thiếu: stale preview, race, failure/retry, corrupt persistence, malformed spatial JSON, missing assets/audio, format safe-zone.
3. **Parity:** cùng fixture so donor vs R2 về result semantics, determinism, fail-safe/data integrity, audit/observability, p95 latency, peak RSS/CPU/disk, render time và output quality. Khác biệt có chủ ý phải documented và tốt hơn theo R2 invariant.
4. **Completion:** evidence khóa exact integrated HEAD, clean scope, commands/logs/machine-readable results; independent review. Manual impression/code similarity không đủ.

## 9. Bounded probes/benchmarks trước thiết kế hoặc implementation

### P1 — Canvas candidate + promotion race

- Corpus: 1k/5k nodes, nested groups, broken/missing edge, multi-select, 50-step history, reload, clear-to-empty.
- Race: preview rev N; mutate N+1; two concurrent promotes; expired authorization; target master changed; server failure after artifact write/before audit.
- Pass: candidate load/save p95 và peak memory trong budget được chốt; no lost prior master; stale promote fails closed; exactly one committed artifact/receipt; audit contains actor, preview hash, lineage và outcome.

### P2 — Spatial topology

- 12–20 paired MASTER/REVERSE fixtures: symmetric room, repeated doors, mirror, partial coverage, shared seam anchor, contradictory refs.
- So donor pin với R2 normalized candidate; 3 repeated runs/model pin nếu provider cho phép.
- Measure: schema-valid rate, anchor duplicate/miss, front/back inversion, unsupported-inference rate, human correction time, cost/latency. Không đạt nếu inference trở thành hard fact hoặc output thay production state.

### P3 — Learning offline replay

- Train window nội bộ từ QA/reject/regenerate/cost/time; holdout theo project/format/time để tránh leakage.
- Recommendation luôn có evidence refs/confidence/scope/exclusions; operator accept/reject; replay không mutate policy.
- Measure calibration, precision@accepted, regret/cost, repeated-rejected rate, segment sample size. Không deploy auto-routing dựa trên correlation chưa kiểm soát.

### P4 — Multi-format parity

- Cùng approved lineage render 16:9, 9:16 và 1:1; fixtures gồm dialogue, two-shot, text-heavy, captions, title/end card, fast motion.
- Hai lần render cùng toolchain/image/font pin: compare frame count/duration/audio alignment/hash hoặc documented nondeterministic bytes + perceptual metrics.
- Human rubric: subject retained, no caption/text crop/collision, readable safe zones, shot intent preserved. Ghi render time, peak RSS/CPU, output size. Nếu cần đổi shot/content, route thành candidate + approval mới.

## 10. Risk register

| Risk | Mức | Control |
|---|---:|---|
| UI wrapper bị nhầm là authority enforcement | Critical | Server-side authorization + expected lineage/version + transactional audit receipt |
| Canvas autosave/undo làm nhiễm artifact truth | Critical | Separate candidate store; promotion-only bridge; undo không chạm authority |
| Spatial model hallucination/format drift | High | Strict validation, evidence per assertion, gap state, human review, provider/version pin |
| Learning tối ưu metric proxy rồi rewrite creative truth | Critical | Recommendation-only state machine; scope/confidence/evidence; explicit human decision |
| Format outputs rẽ lineage hoặc semantic drift | High | Shared approved source refs; projection spec; new approval khi content changes |
| ELv2/AGPL obligations | High | Legal/license review trước code reuse; ưu tiên clean-room pattern |
| Node/OpenRouter/FFmpeg side runtime phá single-host ops | High | Host-owned adapter/subprocess policy; resource limits; không sidecar nếu chưa re-approve |
| Donor tests rộng nhưng critical path chưa chứng minh | High | Targeted parity corpus + fresh commands at exact pin/integrated HEAD |

## 11. Evidence gaps và next steps

1. Thêm OpenMontage pin/files/hashes vào source manifest qua một task evidence riêng; vòng này không sửa manifest vì ownership bị giới hạn một file.
2. Fresh-run targeted DramaClaw canvas/freezone tests và OpenMontage contract tests ở exact pins; ghi command/env/tool versions, không tái dùng log lịch sử làm PASS.
3. Audit server implementation phía sau DramaClaw `/freezone/push` và tests `commit-dialog-*`, `director-render-commit`, `scene-director-world-commit` trước khi kết luận transaction semantics.
4. Đọc dependency chain và tests của `scene_spatial_contract.py`; hiện mới audit file chính và complete tree names.
5. Xác định OpenMontage modules/telemetry ngoài các path đã đọc; hiện không được claim repo “không có learning”, chỉ “chưa chứng minh trong bounded inspection”.
6. Legal review ELv2 và AGPL-3.0 theo mô hình phân phối/host thực tế.
7. Chốt budgets P1–P4 (dataset, p95/RSS/render-time thresholds, perceptual/human rubric) trong spec tương lai, không trong research note này.
8. Reconfirm single-host/Node subprocess authority trước mọi prototype có Remotion; không start service/migration/provider call nếu chưa có approval.

**Decision recommendation:** cho phép chuyển sang design chỉ với Phương án A và các contract/probe ở trên; giữ `PORT/VENDOR/SIDECAR = BLOCKED` đến khi license, fresh tests, parity corpus và operational approval đóng đủ. Báo cáo này không phê duyệt production, không thay frozen docs và không chứng minh M8 đã hoàn thành.
