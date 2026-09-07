# R2 reuse map và đường hoàn thành M7–M8

Ngày đối chiếu: 2026-09-07. Mục tiêu người dùng đã xác nhận: hoàn thành cả M7–M8, chất lượng cao, reuse-first, một người vận hành. Đây là nghiên cứu triển khai và đề xuất nghiệm thu; không thay thế frozen architecture hoặc tự phê duyệt production.

## Kết luận

Nghiên cứu trước triển khai có tồn tại, đã dẫn đến quyết định chọn ArcReel làm host và phân vai donor. Không cần mở lại cuộc thi chọn host. Khoảng trống hiện nay là chứng minh các phần được chọn hoạt động cùng nhau và tạo ra sản phẩm đạt chất lượng, không chỉ vượt contract tests.

R1.8 khóa ArcReel v0.29.0 tại `6ddedc775e7fe5f398b10081ab741985f7dceda7`. R1.7 phân biệt rõ cross-stack contract fixtures với tích hợp runtime upstream. Vì vậy không cộng các kết quả donor độc lập thành bằng chứng hoàn thành sản phẩm R2. Nguồn lịch sử: `R1_08_FINAL_DECISION.json`, `R1_08_FINAL_HOST_DECISION.md`, `R2_ARCHITECTURE_FREEZE_ENTRY_GATE.md` trong `/home/anhtuan/Bản tải về/conten os/content_production_os_r1_8_final_2026-09-06.zip`; `R1_07_EXECUTABLE_CROSS_STACK_RESULTS.md` trong bundle R1.1–R1.7 cùng thư mục.

Hiện Golden A chứng minh đường kỹ thuật, nhưng video được kiểm tra là các khung màu, không có audio. Chưa thể nghiệm thu nó như một explainer có nội dung. H1 vẫn là blocker vận hành; C04 budget không tự giải quyết H1. Chi tiết và bằng chứng chạy tại [báo cáo trạng thái](../r2/evidence/PROJECT_STATUS_REVIEW_2026-09-07.md).

## Bản đồ tái sử dụng

Các đường dẫn donor bên dưới được định danh bằng URL và SHA trong [source manifest](../r2/evidence/reuse-map-2026-09-07/source-manifest.json). SHA thu thập lần này là revision nghiên cứu, **không tự thay integration pin đã được duyệt**. Khi tích hợp cần kiểm tra license, phụ thuộc và contract của đúng phần lấy vào.

| Nguồn | Phần có bằng chứng để lấy | Cách nối và giới hạn |
|---|---|---|
| ArcReel | `lib/version_manager.py`, queue, usage repository, TTS, export Jianying, deployment/restore docs | Dùng host hiện hữu cho task, artifact, cost, version và recovery; bổ sung R2 contract qua adapter. Không dựng queue hoặc exporter thứ hai. H1–H8 cần kiểm chứng riêng. |
| OpenMontage | `remotion-composer/src/Explainer.tsx`, TerminalScene, ScreenshotScene, CaptionOverlay; `tools/video/video_compose.py` | Ứng viên cho Golden A có hình giải thích thực. Project renderer/asset manifest phải là projection từ approved artifacts của host. Cần benchmark render, font tiếng Việt/offline, audio và phụ thuộc; chưa chạy render Remotion lần này. |
| take | `packages/core/src/schemas.ts`, `validate.ts`, exports trong `index.ts` | Lấy shot grammar và validation. Schema donor có prompt/provider/status riêng, nên không dùng nguyên dạng làm R2 ShotSpec hoặc coi `isRenderable` là human approval. |
| Jellyfish | `shot_preparation_state.py`, `shot_video_readiness.py` | Lấy cách tổng hợp readiness/assets/dialogue. Tách semantic readiness Gate1 khỏi provider/key/task readiness Gate2; service gốc phụ thuộc DB/runtime donor. |
| ai-short-film | `shot_reference_builder.py` | Lấy điều kiện tham chiếu frame trước và visual continuity. Chuyển sang binding/capability R2, không nối previous-frame vô điều kiện. |
| Butterfly Director | prompt director `schema.py`, `validators.py` | Lấy visual profile và kiểm tra đủ/duy nhất shot IDs. Chuẩn hóa thành PromptPlan; không mang prompt history/runtime donor thành authority mới. |
| Novel Studio | `contextPack.ts`, `hardRules.ts`, `memoryService.ts` | Lấy context selection và hard-rule QA. Extraction trở thành proposal; không gọi đường ghi SQLite/accepted chapter làm Canon commit của R2. Các rule chuỗi không thay Epistemic engine. |
| Shenbi | state-settling skill, `gates/g4/state_settling.py` | Lấy audit/extraction workflow. Skill hiện được đọc có yêu cầu human approval trước ghi; không lặp lại nhận định lịch sử rằng luôn tự ghi trước duyệt. Vẫn phải chuyển output truth files thành proposal/commit của R2. |
| Huohuo | `novel-change-record.ts`, causal ChangeRecord service | Lấy parser/cấu trúc nguyên nhân thay đổi, chuẩn hóa vào NarrativeChangeSet. Cần test ngôn ngữ và fallback; không đưa memory store donor thành Canon. |
| StoryBox | `reverie/persona/cognitive/perceive.py` | Lấy mô hình mô phỏng giới hạn. Memory mô phỏng không chứng minh knowledge correctness: đầu vào phải qua epistemic filter, đầu ra chỉ là proposal. |
| DramaClaw | `promoteToAsset.ts`, `canvasServices.ts` | Lấy canvas service seams, impact preview và PROMOTE tường minh. Rebind gateway vào R2 approval/commit; không dùng `/freezone/push` để ghi thẳng vào authority donor. Spatial source đã thu thập nhưng chưa đủ thẩm định sâu để chọn tích hợp. |
| DramaClaw gateway | `dc-media-protocol.en.md` đã thu thập | Chỉ là ứng viên transport tùy chọn; chưa có kiểm thử giao thức hay quyết định cần dùng. Không biến gateway thành task authority. |

Phần R2 cần sở hữu là Canon/Epistemic, transaction/approval, context và delta contracts, routing và learning governance. “Reuse-first” không có nghĩa nhập nguyên runtime của mọi donor.

## Bằng chứng và giới hạn

- Host đang được review ở `1985b815d70dd600519839973b1da20472012d8f`; CI handoff ở `521aad2f83a19bdb03219923b6bd2268a338f617`. Kết quả baseline chi tiết nằm trong báo cáo trạng thái; chưa merge hai nhánh.
- OpenMontage local pin `08e2151fa02de28a5d6a312b3d575692bf147ad7`: chạy mới ba contract files `test_phase0_contracts.py`, `test_remotion_video_transition_contract.py`, `test_theme_text_contrast_contract.py`: **56 passed, exit 0**. [Log](../r2/evidence/reuse-map-2026-09-07/openmontage-probe.log).
- take local pin `47c17216b5ad74ee7dd376e8508266e29aefae2c`: chạy mới `packages/core/test/core.test.ts`: **12 passed, exit 0**. [Log](../r2/evidence/reuse-map-2026-09-07/take-core-probe.log).
- Chưa chạy runtime tests cho chín remote donor, chưa chứng minh cross-stack provider/render E2E. Không dùng tổng test lịch sử làm kết quả hiện tại.
- Host: graph Tier 2, source fallback khi thiếu coverage. Donor không có graph trong danh sách project, nên dùng source/tree tại SHA cụ thể. Manifest ghi file đã thu thập, không có nghĩa mọi dòng đều được audit. Không đưa ra khẳng định đầy đủ/không tồn tại chức năng từ tìm kiếm tên file.
- Canvas store lớn, spatial contract, gateway và learning donor cần thêm kiểm chứng trước implementation. Có đầu mối Shenbi style-learning trong tree; chưa đủ bằng chứng để chọn làm learning engine.

## Tiêu chí đề xuất cho một người vận hành

Các mặc định sau cho phép chuẩn bị test/thiết kế mà không bắt người dùng trả lời lại câu hỏi kiến trúc. Chúng chưa thay đổi frozen acceptance corpus.

| Chặng | Checklist nghiệm thu |
|---|---|
| C04 → M4 | Tiếp tục approved execution package từ CI handoff; budget/reservation theo contract; đạt corpus shot/mutation đã duyệt. Giữ đúng thứ tự milestone. |
| Golden A | Giữ bài mẫu Git để so sánh; thêm một chủ đề chưa thấy. Video có nội dung giải thích được nguồn hỗ trợ, hình đúng nội dung, caption/audio đồng bộ theo tiêu chí sản phẩm được chọn; tiếng Việt là mặc định đề xuất. Master, nguồn, chi phí và approval truy vết được. |
| M5 → M6 | Narrative/knowledge/state/adaptation theo frozen plan. Golden B 60–120 giây, nhiều nhân vật/cảnh, continuity, secret constraint và candidate selection có review thực. |
| M7 hardening | Đóng H1–H8 bằng bằng chứng tương ứng; kill/restart thật, không chỉ tạo lại object. Restore DB + media sang target sạch; kiểm tra master refs. Qualification đường provider thực dùng. Browser workflow tạo → review → export. |
| M7 vận hành | Một deployment có image pin, phiên bản PostgreSQL đã kiểm chứng, private access mặc định, secret config, budget cap, log correlation, hướng dẫn retry/rollback/restore. Compose upstream dùng `latest` không đủ làm release recipe R2. |
| M8 canvas | View/controller trên cùng project authority; load/reload giữ đúng trạng thái, preview impact, PROMOTE cần approval, stale/concurrent/failed promotion không mất master. |
| M8 learning | Bắt đầu từ QA/reject/regenerate/cost/time nội bộ, không phụ thuộc có sẵn social channel. Mỗi đề xuất có evidence, confidence, phạm vi áp dụng và human accept/reject. Không tự thay Canon/policy. Kiểm tra trên trường hợp giữ lại để đánh giá và lưu quyết định. |
| M8 đa định dạng/spatial | Chứng minh đầu ra hữu ích và lineage từ cùng approved assets. Chọn benchmark nhỏ cho spatial nếu kích hoạt; ghi utility, chi phí và quyết định. Không coi thu thập code 3D là đã hoàn thành phần này. |

Không cần hỏi lại mô hình single-operator hoặc chọn host. Các thông tin chỉ người dùng cung cấp khi đến bước thực thi là tài khoản/credentials, ngân sách provider thực và approval phát hành/publish. Chuẩn bị local fixtures, adapter contract và acceptance evidence không bị chặn bởi các thông tin đó.

## Bước tiếp theo

1. Đối chiếu lại C04 approved package và CI handoff để thực thi đúng phạm vi đã duyệt.
2. Chuẩn bị acceptance fixture Golden A có nội dung thật, tận dụng OpenMontage composition; không nhảy qua milestone để đưa renderer mới vào runtime ngay.
3. Trước M8, đóng nghiên cứu learning/spatial còn mở bằng source và benchmark có giới hạn; kết quả phải cập nhật integration decision, không chỉ danh sách repo.

M7–M8 vẫn chưa hoàn thành. Bản đồ này giúp chuyển nghiên cứu cũ thành công việc và điều kiện nghiệm thu kiểm chứng được.
