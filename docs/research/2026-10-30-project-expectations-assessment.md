# Đối chiếu kỳ vọng ban đầu với trạng thái hiện tại — 30/10/2026

## Kết luận

**Dự án đã có nền tảng sản xuất nội dung chạy thật, có quản trị phiên bản/nguồn gốc, viết truyện, tạo media, xuất gói và bằng chứng khôi phục. Mục tiêu một Creative Production OS khép kín, tạo sản phẩm chất lượng thương mại với ít can thiệp rồi học từ thị trường, vẫn chưa đạt.**

Khoảng cách hiện nay nằm ở chất lượng và trải nghiệm xuyên suốt, nghiên cứu cơ hội, phát hành và dữ liệu khán giả. Không thể lấy số milestone, số test, nhãn `COMMITTED` hoặc một MP4 phát được để suy ra tỷ lệ hoàn thành mục tiêu sản phẩm. Báo cáo không gán phần trăm tổng thể vì các kỳ vọng có trọng số và mức chứng minh khác nhau.

Cần điều chỉnh nhận định “bước viết tự động chưa được kiểm chứng” trong trao đổi trước: **đã có lượt idea→truyện ba chương→nguồn video**, có hồ sơ từ tháng 10 và hiện còn một run COMMITTED trên production. Phần chưa chứng minh là một hành trình mới, ổn định, đạt chất lượng, nối thẳng từ ý tưởng đến phim hoàn chỉnh với stack media local vừa cấu hình.

## Căn cứ và cách đọc

- Bản đang chạy: `r2-v2.1.0`, checkout sạch ở `0cef69a772f1d2946e452b918a8839b0f37fd2d9`, `127.0.0.1:1251`. Evidence/media mới nhất trước lần đánh giá: `18b74a17b` trên `r2-m10-c`.
- Root checkout `dbaf93a6` chứa nhiều bản nháp dirty; không phải ảnh chụp đầy đủ của bản đang chạy. Giữ nguyên chúng. Bản đồ kỳ vọng gốc: [memo nguồn](2026-10-30-original-expectations-source-map.md).
- **LIVE:** đọc trực tiếp trạng thái hiện tại trong lần rà soát này. **HỒ SƠ:** acceptance/log/artefact đã có, được đọc lại nhưng không chạy lại bộ nghiệm thu. **THIẾT KẾ:** hướng đi/contract, chưa được tính là khả năng sử dụng đã chứng minh.
- Vision/origin giải thích mục đích. Frozen architecture và các quyết định/acceptance tiếp theo xác định phạm vi. ADR-0089 chốt V1 có giới hạn; tài liệu 23/10 gọi phần mở rộng còn lại là “V3”. Do đó nhãn release “V2.1” không có nghĩa toàn bộ M9–M12 đã hoàn thành. [S1, S2, S3, S4]
- Dữ liệu LIVE đã lọc bỏ bí mật: [snapshot JSON](2026-10-30-project-expectations-live.json), thời điểm chụp nằm trong `captured_at`. Không gửi generation, không sửa cấu hình/dữ liệu ứng dụng, không duyệt gate hay thực hiện publish trong lần đánh giá này.

## 1. Mục đích ban đầu thực sự là gì?

North Star đặt mục tiêu biến **cơ hội/ý tưởng → câu chuyện/IP được quản lý bằng Canon → nhiều sản phẩm media → thị trường → quan sát thực tế → quyết định sáng tạo tiếp theo**. Chất lượng, tính nguyên bản, provenance, reuse và quyền quyết định của con người là các yêu cầu cốt lõi. Video, viết truyện và tự động hóa kênh là những capability trong hệ thống đó. [S1:8–43]

Những nguyên tắc xuyên suốt cần được giữ khi đánh giá: draft khác Canon; generation candidate khác ApprovedMaster; runtime task khác artifact truth; method phải được chọn trước provider; dữ liệu quan sát chưa tự trở thành rule. [S2:256–291; S5:26–82]

V1 đã chủ động thu hẹp phạm vi về một operator: tạo/mở dự án, đưa ý tưởng/nguồn, duyệt kịch bản, sản xuất, chọn bản cuối, xuất và khôi phục an toàn. Tự động phát hành/analytics/portfolio được để lại cho giai đoạn sau. Đây là sequencing đã quyết định, không phải mọi phần chưa làm đều là một lỗi của V1. [S3:16–71]

## 2. Ma trận kỳ vọng → bằng chứng → khoảng cách

| Kỳ vọng | Đánh giá hiện tại | Đã chứng minh | Phần chưa đạt/chưa đủ bằng chứng |
|---|---|---|---|
| Một workbench thống nhất, quản lý dự án, nguồn, tập/cảnh, task, phiên bản và artefact | **Đạt nền tảng sử dụng** | HỒ SƠ V1 có chu kỳ operator và restore; LIVE hai dự án đọc được; dự án local có một tập hoàn tất 3/3 cảnh. [S6, S7, LIVE] | Chưa chứng minh mọi luồng người dùng hoàn tất thuận tiện từ đầu đến cuối mà không cần người điều khiển kỹ thuật. |
| Một ý tưởng tạo thành truyện hoàn chỉnh | **Đạt một phần đáng kể** | HỒ SƠ `accept-clean` có 3 chương, khoảng 8.263 đơn vị âm tiết, export và handoff khớp digest. LIVE truyện “Đò Cuối Sông” COMMITTED, đã handoff. [S8, S9, LIVE] | Local mất khoảng 4–5 giờ. Lượt production cũ có 16 ngoại lệ narrative-critical được agent chấp nhận; có mâu thuẫn sống/chết, lộ bí mật và diễn biến hụt. Lượt cloud mới đang dừng vì kết quả/usage chưa xác định. Chất lượng thương mại ổn định chưa được chứng minh. |
| Canon, tri thức nhân vật và continuity được quản trị | **Đạt về kernel/hợp đồng; một phần về hiệu quả sáng tạo** | HỒ SƠ M5/M6 và V1 có narrative admission, lifecycle và hai profile từ một Canon. Story pipeline có review/repair; donor parity cho các surface chọn lọc PASS. [S6, S10] | Không có bằng chứng một series dài giữ nhân vật, tri thức, setup/payoff và hình ảnh tốt liên tục. Kernel đúng không bảo đảm văn học hay. |
| Direct/Prepare và sản xuất hybrid, reuse-first | **Đạt một phần** | HỒ SƠ Golden có deterministic composition; LIVE/artefact local đi ảnh→video và có selected versions. [S6, S11] | Chưa chứng minh tự động chọn tối ưu reuse/stock/capture/deterministic/generated cho nội dung mới; bộ local chưa thử reference-guided image, look-lock, lip sync và continuity nhiều cảnh có nhân vật định danh. |
| Có media thật, không chỉ metadata hoặc test | **Đạt trong các phạm vi đã đo** | HỒ SƠ Golden A 75,2 s; Golden B Western/爽文 96,3 s. Bài local mới: 3 ảnh FLUX, 3 audio VieNeu, 3 video Wan, MP4 6,125 s H.264/AAC, phụ đề tiếng Việt; đủ 9 task thành công. [S6, S11] | Golden là corpus/driver kiểm chứng, bản V1 chọn MUTE. Clip AI local mới chỉ 6,125 s, chưa là bằng chứng phim kể chuyện 60–120 s hay factual video mới 60–180 s đạt chất lượng. |
| Model/provider trung lập, kiểm soát chi phí và lựa chọn local | **Đạt khả năng cấu hình/thực thi; tối ưu tự động chưa chứng minh** | LIVE ảnh/video/TTS dùng custom local; default text vẫn Gemini. Các protocol và model identity tách biệt; có bounded cloud canary trong hồ sơ. [S12, LIVE] | Chưa có benchmark end-to-end chọn model theo chất lượng/giá/độ trễ. Local media không đồng nghĩa toàn bộ text/agent hoạt động offline hay tự chủ tốt. |
| Sáu lớp QA, assessor độc lập, fail thì dừng | **Đạt một phần, tiến bộ rõ từ M10** | HỒ SƠ M10-A/B/C accepted có điều kiện; UI Quality thực thi được trên pilot; C4 đã qualify 33 test và bật trên host. [S13, S14, S15] | Catalog `host-v1` ở đây phục vụ container/decode, không đại diện đủ factual/narrative/continuity/visual/audio. Nhiều pilot dùng agent làm reviewer. LIVE hai dự án đang xem đều chưa có QualityProfile; clip local mới chưa đi trọn QualityRun→disposition→package selection. |
| Một IP sinh nhiều format với lineage đúng | **Đạt một phần theo corpus/profile** | HỒ SƠ M6 Western và short-drama Trung Quốc; M8 có Canvas/spatial/format và profile isolation, 9:16/square. [S6, S16] | Corpus M8 dùng synthetic values/pinned responses, không đại diện khán giả thật. Chưa chứng minh một IP thương mại tạo được nhiều phiên bản có giá trị trên nhiều kênh; podcast/audiobook/feature-film vẫn là extension tương lai. |
| Packaging và controlled export | **Đạt cơ chế có điều kiện** | HỒ SƠ M10 có immutable package, selection/disposition/digest và export kiểm tra được. Native editable draft local có 3 video/audio/text segment. [S13, S11] | Bản MP4 local được ghép bằng FFmpeg từ native presentation, không phải nút xuất MP4 narration đã hoàn thiện trong UI. Chưa có bằng chứng title/thumbnail/cut làm tăng hiệu quả thị trường. |
| Tìm cơ hội, nghiên cứu thị trường, ResearchPack với fact có nguồn | **Chưa đạt mục tiêu vận hành** | HỒ SƠ M9-A foundation accepted; M9-B acquisition/manual-recovery offline accepted có điều kiện. [S17] | M9-A/B chưa nằm trong ancestry release hiện tại; production API được công bố không có họ opportunity. Candidate/scoring/factual closure và activation không được suy ra từ acceptance của foundation/acquisition. Người dùng vẫn mang ý tưởng vào. |
| Đưa nội dung lên YouTube/TikTok, schedule và reconcile | **Chưa đạt tự động hóa này** | Có Gate D/receipt và controlled export. Source route publish-approval kiểm tra final rồi ghi decision; không thực hiện upload. [S3, S18] | M11 là thiết kế proposed ở root; chưa thấy bằng chứng vận hành provider delivery trên release này. API catalog hiện tại không công bố họ distribution. Gate D không phải biên nhận nội dung đã xuất bản. |
| Lấy số liệu thật, map retention về cảnh rồi học cho vòng sau | **Chưa đạt closed loop thị trường** | M8 có observation/recommendation/decision lifecycle và thử nghiệm associative trên corpus tổng hợp. [S16] | Không có hồ sơ cho một vòng phát hành→analytics thật→learning→ý tưởng mới đã hoàn tất. Các lift 15–20% trong corpus tổng hợp không phải kết quả tăng view/retention thật. M12 vẫn là phần mở rộng thiết kế. |
| Nhiều pipeline độc lập hoạt động liên tục, ít thao tác người | **Một phần ở task/project; chưa đạt autopilot** | Host có task queue và nhiều project, bảng tiến trình và story runs. [S4, LIVE] | Chưa chứng minh portfolio scheduler/control plane hay vận hành dài ngày không người điều khiển. GPU media hiện được dùng tuần tự; các project phải được khởi động/điều phối trong phạm vi worker. |
| Recovery, provenance và Human authority | **Đạt nền tảng; chưa bao phủ sản phẩm/local stack mới** | HỒ SƠ V1 có DB+media restore, reopen, hash và gate receipts; M10 bám identity hiện hành. [S6, S7, S13] | Restore đó không chứng minh restore toàn bộ cấu hình/model D mới sau thay đổi ngày 30/10. LIVE proof local không có Greenlight/script-lock/publish-approval và không có approved master trong Quality. Tự chạy thành công không thay cho Human creative/release acceptance. |

## 3. Những gì đã đạt cần được ghi nhận đúng

**Chúng ta đã vượt giai đoạn chỉ có tài liệu hoặc giao diện.** Có release chạy thật; chuỗi task thật; dữ liệu có version/digest; khôi phục được DB/media trong các drill; các luồng đã qua nhiều lần review và sửa lỗi. M8, M10 đều có acceptance packet riêng, với giới hạn minh bạch. [S6, S7, S13–S16]

**Không phải dự án mới chỉ làm được 6 giây.** Golden A/B đã chứng minh composition/export/restore ở thời lượng khoảng 75–96 giây. Điểm mới của bài 6 giây là chứng minh các model tạo ảnh/video/giọng đọc local trên RTX 2070 chạy qua hàng đợi dự án và ghép ra bản có tiếng. Hai loại bằng chứng phục vụ hai câu hỏi khác nhau. [S6, S11]

**Đã có tự động viết truyện và đối chiếu donor thật.** `R2_STORY_DONOR_PARITY.json` ghi PASS trên các surface được chọn, 10 mẫu mỗi arm, kèm các thay đổi model/rubric và những phép đo chưa đạt. Đây là bằng chứng tái sử dụng có phạm vi; không chứng nhận toàn bộ hệ thống có chất lượng bằng hay hơn mọi donor trên mọi nội dung. [S10]

## 4. Dữ liệu LIVE và ý nghĩa sản phẩm

Snapshot hiện tại ghi nhận:

- `du-an-01-649c62c1`: 18 tập; **0 tập có kịch bản, 0 hoàn tất sản xuất** trong summary. Có một story COMMITTED đã handoff và một story `BLOCKED_QUALITY`.
- Lý do dừng của lượt cloud mới là **`OUTCOME_UNKNOWN at chapter_review[1]@r0.2.0#3: cloud request outcome or usage is unknown`**. Đây là bất định ở request/usage, không phải bằng chứng rằng nội dung bị reviewer chấm kém. Không thực hiện gửi lại trong lần đánh giá này.
- `local-media-proof-2026-1-f4bd3cf4`: 1 tập scripted/completed, 3/3 cảnh; không có story run. Kịch bản được operator chuẩn bị và nhập qua helper/owner transaction; final MP4 được ghép bằng FFmpeg. Đây chưa phải lượt UI idea→story→film tự động liên tục.
- QualityProfile: 0 trên cả hai dự án. Approved master mà Quality đọc được: 1 ở dự án gốc (Golden final đã có), 0 ở proof local. Không suy số quality run từ GET `/quality/runs` vì route cần tham số; lần đọc không đủ tham số trả 422. Không suy “không có learning” từ GET observations, vì route này trả 405 cho phương thức GET.
- Lịch sử API gates ở proof local: greenlight 0, script_lock 0, publish_approval 0. Đây là proof kỹ thuật chưa có hồ sơ phát hành Human.
- Ba task Wan mất **301,226 / 265,512 / 265,526 giây**. Từ enqueue task đầu đến task cuối khoảng **16,45 phút** để làm 6,125 giây media trong lượt tuần tự này. Đây là một số đo, không ngoại suy thành benchmark video dài. [S11]

Các dữ liệu này giải thích vì sao nhãn “đã triển khai”, “Done”, “COMMITTED”, “production” và “đạt kỳ vọng thương mại” cần được đọc tách biệt.

## 5. Những khoảng cách lớn nhất so với mục đích ban đầu

1. **Chất lượng nội dung và tính nhất quán chưa thành kết quả ổn định.** Có Canon/review/repair và parity, nhưng vẫn có ngoại lệ narrative-critical được chấp nhận trên bản production. Cần một sản phẩm người xem thật thấy tốt, có đánh giá độc lập, thay vì chỉ đóng đủ trạng thái kỹ thuật.
2. **Hành trình người dùng chưa liền mạch.** Một người nhập ý tưởng, duyệt ở các điểm đã quyết định, rồi nhận bản phim hoàn chỉnh có thể xuất bản là mục tiêu cao hơn các demo từng phần. Bài local vẫn cần chuẩn bị dữ liệu và render ngoài UI; dự án truyện thực tế dừng trước script/video.
3. **Phần thị trường của closed loop còn mở.** M9 đang ở foundation/acquisition trên nhánh riêng; M11/M12 và portfolio chưa có bằng chứng production hoàn tất. Chưa chứng minh phát hành, khán giả, retention, học lại hay hiệu quả kinh tế. Không có dữ liệu để kết luận về doanh thu hoặc sức hút thương mại.
4. **Human authority có cơ chế nhưng chưa có đủ acceptance sáng tạo độc lập.** Các ngoại lệ/delegation của sponsor phải được giữ nguyên trong hồ sơ; không biến approval của agent thành một người khác đã đọc và chấp thuận nội dung.
5. **Thông lượng và vận hành dài hạn còn cần chứng minh.** Local giảm phụ thuộc API tính phí nhưng đổi lấy thời gian GPU và tài nguyên. Một proof ngắn và backup cũ chưa chứng minh một hệ thống sản xuất nhiều tập liên tục có thể phục hồi đầy đủ sau sự cố hiện tại.

## 6. Vì sao đọc tài liệu rời rạc dễ cho kết luận sai?

- Root worktree và release worktree có lịch sử khác nhau. ADR-0089 là untracked ở root nhưng đã committed trên nhánh phát hành. Root dirty không đồng nghĩa hệ thống phát hành chưa có quyết định đó.
- Boundary ngày 23/10 còn ghi chưa có image/video provider và chưa có Quality authority. Đến 30/10 đã có M10/C4 và local media. Nó vẫn hữu ích để hiểu sequencing, nhưng các dòng capability đó không còn là ảnh chụp hiện tại. [S4, S12–S15]
- Deployment record V2.1 ban đầu ghi probes disabled. C4 record mới hơn ghi qualified/enabled. Cần đọc theo chuỗi thời gian, không giữ nguyên blocker đã được xử lý. [S14, S15]
- M9-B có candidate JSON còn dấu pending lịch sử; independent-final-review mới hơn đã accepted-with-conditions ở `a59c25eb6` / tested `062f87603`. Tuy nhiên acceptance này **không phải** merge, provider activation hoặc production qualification. [S17]
- M8 Learning đã implemented không đồng nghĩa đã lấy analytics thật; Golden video dài không đồng nghĩa một phim mới bất kỳ đã được model sản xuất tốt; M10 local export không đồng nghĩa đã publish. [S6, S13, S16, S18]

Nên dùng bảng capability có ngày chốt/release/evidence làm bản đọc trạng thái; không dùng nhãn phiên bản hoặc một checklist cũ làm tổng kết toàn dự án.

## 7. Ưu tiên tiếp theo — đề xuất từ khoảng cách đã quan sát

Đây là đề xuất, không đổi roadmap hoặc cấp quyền thực thi mới:

1. **Khép một sản phẩm thực sự từ ý tưởng đến phim trên release hiện tại.** Dùng một câu chuyện Việt ngắn, tiêu chí chất lượng định trước, ít touchpoint đúng quyết định; xử lý lượt cloud `OUTCOME_UNKNOWN` bằng quy trình custody/reconciliation hiện có trước khi cân nhắc retry. Nối manuscript→episode→script→media→approved master→Quality→controlled export. Một người độc lập thực sự đọc/xem/chấp nhận.
2. **Chứng minh lại hai lát cắt sản phẩm thực tế ở chất lượng mong muốn:** factual 60–180 s có nguồn và drama 60–120 s có nhân vật/continuity/audio; dùng sản phẩm mới để bổ sung cho Golden corpus. Đo thời gian, mức can thiệp, tỷ lệ phải làm lại và chi phí/tài nguyên. Thử reopen/restore với DB, media, cấu hình và model-store D hiện tại. [S3]
3. **Tiếp tục các owner packet theo thứ tự đã quyết định:** M9 candidate/scoring/factual closure và activation, rồi M11 delivery, M12 số liệu thật/learning; portfolio sau các owner. Có thể xác thực giá trị bằng xuất và phát hành thủ công có duyệt trong phạm vi hiện có, nhưng lần rà soát này không thực hiện hay chấp thuận xuất bản.

Mục tiêu của bước kế tiếp nên là **một sản phẩm tốt, tái lập được, người dùng tự vận hành được**, cùng bằng chứng đúng cho những phần đã làm. Sau đó mới có cơ sở đo mức tự động hóa hoặc mở rộng công suất.

## Nguồn chính và phạm vi đã đọc

Các nguồn dưới đây được đọc trực tiếp; trạng thái hồ sơ không được trình bày như test vừa chạy lại:

- **S1:** [Product Vision](r2-origin/00_PRODUCT_VISION.md), đặc biệt 8–43, 72–132; baseline gốc `dbaf93a6` và bản released đối chiếu.
- **S2:** [Frozen Architecture](../r2/R2_01_FROZEN_ARCHITECTURE.md), §2, §5; [origin authority guide](r2-origin/README.md).
- **S3:** [V1 release strategy](../r2/R2_V1_PRODUCTION_RELEASE_STRATEGY.md), §2–§8; [ADR-0089](../adr/0089-ship-a-bounded-v1-before-v2-portfolio-automation.md); [V1 readiness research](2026-09-17-r2-v1-production-readiness-v2-deferment.md).
- **S4:** [V2/V3 capability boundary](../r2/R2_V2_CAPABILITY_AND_V3_BOUNDARY.md), 23/10; các phần cũ được đối chiếu lại với release 30/10.
- **S5:** [System Requirements](r2-origin/02_SYSTEM_REQUIREMENTS.md), §A1–A8, §B; [Research Synthesis](r2-origin/01_RESEARCH_SYNTHESIS.md).
- **S6:** [V1 production candidate](../r2/evidence/R2_V1_PRODUCTION_CANDIDATE_2026-09-28.md), product slices và known limits; [Golden restore](../r2/evidence/R2_V1_08_GOLDEN_RESTORE_DRILL_2026-09-28.json); [sponsor exception](../r2/evidence/R2_V1_RELEASE_SPONSOR_DECISION_2026-09-28.json).
- **S7:** [Operator cycle 1](../r2/evidence/R2_V1_OPERATOR_CYCLE_1_RECORD_2026-09-29.md); [V2 start decision](../r2/evidence/R2_V2_START_DECISION_2026-09-29.json).
- **S8:** [Story acceptance run](../r2/evidence/R2_STORY_ACCEPTANCE_RUN.json): 3 chapters, usage/time, export, recorded deviations.
- **S9:** [Production story trial](../r2/evidence/R2_V2_PROD_E2E_TRIAL.json): approval_disclosure, accepted_exceptions_summary, planner limits; [local planner follow-up](../r2/evidence/R2_V2_PLANNER_LOCAL_9B.json) đọc như hồ sơ có bản sửa sau, không giữ nguyên lỗi cũ.
- **S10:** [Story reuse/release research](2026-10-18-r2-v2-story-release-research.md); [Donor parity](../r2/evidence/R2_STORY_DONOR_PARITY.json), sample, result và deviations.
- **S11:** [Three-scene proof](../r2/evidence/media-local-2026-10-30/three-scene-proof/README.md), [task ledger](../r2/evidence/media-local-2026-10-30/three-scene-proof/task-ledger.json), [final verification](../r2/evidence/media-local-2026-10-30/three-scene-proof/final-verification.json). Bản MP4 còn tồn tại và SHA256 khớp trong lần đọc này.
- **S12:** [Media-provider handoff](../r2/evidence/R2_V2_1_MEDIA_PROVIDERS_HANDOFF.md); local runtime defaults trong LIVE snapshot.
- **S13:** [M10 acceptance](../r2/evidence/R2_M10_ACCEPTANCE.json), claims/does_not_claim/conditions; [pilot summary](../r2/evidence/R2_M10_B7_PILOT_SUMMARY.json); [M10-C acceptance](../r2/evidence/R2_M10_C_ACCEPTANCE.json).
- **S14:** [V2.1 deploy](../r2/evidence/R2_V2_1_0_PRODUCTION_DEPLOYMENT.json), rehearsal và limit tại thời điểm deploy.
- **S15:** [C4 activated-host qualification](../r2/evidence/R2_M10_C4_ACTIVATED_HOST_PROBE_QUALIFICATION.json), qualified/enabled, 33 passed và no-production-probe limit.
- **S16:** [M8 implementation acceptance](../r2/evidence/R2_M8_IMPLEMENTATION_ACCEPTANCE.json), scope, coverage_limits; [M8 integrated results](../r2/evidence/R2_M8_F_RESULTS_V2.json), learning/limits (đọc cùng acceptance và các superseding result V3, không tái chấm nghiệm thu).
- **S17:** Nhánh `r2-m9b`: `docs/r2/evidence/R2_M9_A_IMPLEMENTATION_ACCEPTANCE.json`; `.superpowers/sdd/2026-10-20-r2-m9b-manual-recovery-v2/independent-final-review.json`, reviewed `a59c25eb6`, tested `062f87603`, conditions/limits. Git ancestry kiểm tra LIVE: cả accepted candidate M9-A `912abc3be` và M9-B `a59c25eb6` không là ancestor release `0cef69a77`.
- **S18:** `server/routers/gates.py:670–707` trên release `0cef69a77`, graph trace/snippet đối chiếu source trực tiếp; API catalog LIVE. M11/M12 proposed ADRs ở root là thiết kế chưa tính là runtime.
- **S19:** [Post-M8 architecture acceptance](../r2/evidence/R2_POST_M8_ARCHITECTURE_ACCEPTANCE.json); North-Star completion research được đọc từ Git object `016e094689b5e59666ee879c33bdc194caa415a0:docs/research/2026-09-14-r2-north-star-completion-research.md` (§1–3, §8–10); [M10 research/donor audit](2026-10-23-r2-m10-research-decision-donor-audit.md) cung cấp crosswalk nghiên cứu/owner.

### Giới hạn của lần rà soát

Đây là đánh giá kỳ vọng/sản phẩm có kiểm chứng live đọc-only, không phải một cuộc audit đầy đủ từng dòng code hay một lần nghiệm thu mới. Không đọc lại toàn bộ mọi donor hay mọi log test; không chạy lại PostgreSQL/restart/quality probes, không gọi model/provider hoặc publish. Các kết quả nghiệm thu lịch sử giữ nguyên nguồn, head và hạn chế của chúng.

Graph: root project generation 2026-09-27T03:07:32Z, `r2-v2-main` generation 2026-10-15T01:19:44Z và `r2-m9b` generation 2026-10-20T00:39:00Z; coverage best-effort. Docs bị excluded trong graph V2; `gates.py` metadata changed. Đã dùng đọc file/Git và source release trực tiếp cho những kết luận liên quan, không suy absence toàn repo từ tìm kiếm graph. Các nhận định “không có API family” chỉ có phạm vi OpenAPI đang được công bố ở host này; không phải khẳng định không thể có code ở mọi nhánh.

Giữ nguyên các dirty/untracked tài liệu gốc. Khi tích hợp report, worktree evidence có một deletion ngoài phạm vi (`wan-2.2/i2v-proof.mp4`); không khôi phục hoặc stage deletion đó. Hai report mới và snapshot chỉ là tài liệu đánh giá, không trở thành domain authority.
