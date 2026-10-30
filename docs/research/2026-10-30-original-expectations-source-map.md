# Bản đồ nguồn: kỳ vọng ban đầu của ArcReel / Content Production OS R2

**Phạm vi.** Đây là trích xuất lịch sử, phục vụ đối chiếu với đánh giá trạng thái
hiện tại ở nơi khác; không phải kết luận nghiệm thu hay tuyên bố runtime. Căn cứ
đọc là cây đã commit tại `dbaf93a625bd9e5499f1e50a6838355ff8c0c9e5` (root HEAD
được chỉ định). Bộ `r2-origin` tự xác định là “tầng lý do”, không có thẩm quyền;
khi mâu thuẫn, tài liệu `FROZEN_V1` thắng
([`README.md`](r2-origin/README.md):1-4, 24-37). Vì vậy, các dòng dưới đây là
kỳ vọng gốc được nối tới freeze/ADR khi có thể, không thay thế hợp đồng frozen.

## Kỳ vọng gốc có thể kiểm tra

| # | Kỳ vọng / kết quả mong muốn | Người dùng hoặc workflow hàm ý | Nguồn lịch sử đã commit |
|---|---|---|---|
| 1 | Xây một **AI-native Creative Production OS**, biến cơ hội/ý tưởng thành IP/câu chuyện được quản bằng Canon, rồi thành nhiều media hoàn chỉnh, đưa ra thị trường và học cho vòng sau. | Creative director/operator bắt đầu từ một ý tưởng nhỏ, thay vì ghép các app rời. | `docs/research/r2-origin/00_PRODUCT_VISION.md`:8-16 |
| 2 | Sản phẩm không phải chỉ là app tạo video, YouTube automation, AI viết truyện hay content farm; video là một output và mục tiêu là originality hơn số lượng. | Người dùng cần quản lý trạng thái tự sự, sản xuất, chất lượng, phiên bản, chi phí và quyền con người. | `00_PRODUCT_VISION.md`:18-27, 112-116 |
| 3 | Luồng đích đi gần toàn bộ: discover/research/idea/story/canon → screenplay/storyboard/shot/assets → video/voice/music/edit/QA/metadata → publish/analytics/learning. | Từ series YouTube/TikTok, truyện nhiều tập hoặc IP mới tới vòng lặp kế tiếp. | `00_PRODUCT_VISION.md`:29-44, 46-70 |
| 4 | Human Creative Director giữ quyền quyết định sáng tạo và phát hành; bốn gate đầu là Greenlight, Narrative lock, Final cut và Publish. | Agent/máy có thể chuẩn bị và thực thi, nhưng không phải điểm quyết định cuối. | `00_PRODUCT_VISION.md`:72-93; `02_SYSTEM_REQUIREMENTS.md`:102-105 |
| 5 | Một Canon/IP phải tái dùng được cho nhiều production profile (novel, audiobook, YouTube, TikTok, podcast, drama/film), trong đó mỗi profile có biểu đạt riêng; Shorts không chỉ crop. | Operator phát triển một thế giới/câu chuyện rồi xuất nhiều định dạng có chủ đích. | `00_PRODUCT_VISION.md`:95-111 |
| 6 | Factual truth và fiction truth là authority tách biệt; Canon là structured/versioned state có KnowledgeState; draft không tự thành Canon và transaction lỗi không làm hỏng Canon. | Biên kịch, showrunner và reviewer làm việc qua proposal/QA/approval thay vì coi prose/LLM output là truth. | `02_SYSTEM_REQUIREMENTS.md`:19-24, 26-36 |
| 7 | Chỉ đạo và sản xuất phải là asset-first/hybrid: Shot khác generation; chọn method trước provider; tái dùng asset trước khi generate; deterministic material không giao lại cho AI. | Director tạo ShotSpec/PromptPlan, tạo/chọn candidate có provenance thay vì text-to-video một phát. | `02_SYSTEM_REQUIREMENTS.md`:38-46, 48-57; `01_RESEARCH_SYNTHESIS.md`:40-57 |
| 8 | Hệ thống phải model-agnostic/provider-neutral và chịu được provider churn; Capability Registry/route chọn theo quality, cost, latency, consistency và khả năng tham chiếu. | Operator có thể dùng local/deterministic/cheap/premium theo shot, không bị khóa vào một video model. | `02_SYSTEM_REQUIREMENTS.md`:50-56; `01_RESEARCH_SYNTHESIS.md`:9-21, 43-45 |
| 9 | Chất lượng là cổng chặn: factual, narrative, continuity, visual, audio, production; reviewer độc lập chấm và fail không đi tiếp. | Final-cut evidence không do chính agent tạo output tự xác nhận. | `02_SYSTEM_REQUIREMENTS.md`:58-68 |
| 10 | Mọi collaboration là artifact-first, có dependency graph/invalidation hạt mịn; regeneration không overwrite bản usable, phải version/recovery/atomic promotion; chi phí có budget authority trước paid side effect. | Operator có thể khôi phục, so sánh và sửa đúng shot mà không phá master đã được duyệt. | `02_SYSTEM_REQUIREMENTS.md`:84-116 |
| 11 | Discover không được trend-chasing: Opportunity scoring tách market demand, channel identity, originality, knowledge advantage, feasibility; Research Pack giữ provenance từng fact. | Idea/Research workflow phải tạo căn cứ kiểm chứng trước narrative factual. | `02_SYSTEM_REQUIREMENTS.md`:12-24 |
| 12 | Learn phải evidence-gated: quan sát không tự thành rule; analytics map về scene/script/visual; fiction learning thành recommendation cho Showrunner, không tự sửa Canon/policy. | Channel/portfolio học từ kết quả thật nhưng vẫn giữ authority boundary. | `02_SYSTEM_REQUIREMENTS.md`:76-82; `01_RESEARCH_SYNTHESIS.md`:52-57 |
| 13 | Lộ trình frozen ban đầu tách M0–M8 tuần tự: Host foundation → contracts → artifact bridge → Golden A → production intelligence → Canon/narrative → adaptation/Golden B → hardening → advanced canvas/learning/multi-format. | Đây là decomposition của năng lực, không phải bằng chứng từng capability đã hoàn thành. | `docs/r2/R2_06_ROADMAP_REGISTRY.json`:2-69 |
| 14 | Sau M8, North Star được đóng qua bốn milestone tuần tự: M9 opportunity/research, M10 quality/packaging, M11 governed distribution, M12 portfolio learning; vẫn là deep modules trong ArcReel host/PostgreSQL, không tạo app/orchestrator/DB/truth store thứ hai. | Một closed loop có thể mở rộng mà không phá authority/execution kernel hiện hữu. | `docs/adr/0080-post-m8-north-star-closed-loop.md`:5-14, 24-76 |

## Ranh giới và phần chủ ý để sau

- Không bắt đầu zero-human; gợi ý cũ về auto Gate B/C chỉ là điều kiện tương lai
  trong tài liệu nguồn, không phải quyền tự trị ban đầu
  (`00_PRODUCT_VISION.md`:72-83).
- Feature-film chất lượng cao chưa nên chạy hoàn toàn autonomous; mức tự động hóa
  trong vision là ước lượng kỹ thuật, **không phải benchmark**
  (`00_PRODUCT_VISION.md`:118-132).
- Một IP nhiều profile không có nghĩa mọi profile cùng là kernel: podcast,
  audiobook và novel còn là extension cho tới khi có bằng chứng cần contract kernel
  riêng (`ADR-0080`:217-222).
- M9–M12 không được bắt đầu từ hành vi predecessor mới “planned”; mỗi milestone
  cần evidence và independent review được chấp nhận trước khi milestone sau bắt
  đầu (`ADR-0080`:72-76).
- Export package không đồng nghĩa upload/publish/public. M10 không có external
  publish side effect; M11 tách approval, command, provider identity, delivery
  attempt, reconciliation và receipt (`ADR-0080`:42-53, 204-218).
- Không dùng scraping undocumented để thay thế official capability không có;
  TikTok Research mặc định unavailable nếu không đủ eligibility; Google Trends là
  optional (`ADR-0080`:136-152).
- Adapter/provider/model/donor checkpoint/engagement score/HTTP success không
  được cấp Greenlight, quality disposition, Production Approval hay Publish
  Approval (`ADR-0080`:92-110).

## Diễn biến phạm vi theo tài liệu

1. **Nguồn gốc (03–07/09/2026):** bộ `r2-origin` giải thích chuỗi
   `RESEARCH → PRINCIPLE → REQUIREMENT → ARCHITECTURE → ROADMAP → IMPLEMENTATION`,
   và ghi rõ nó không phải log thực thi (`r2-origin/README.md`:1-13, 39-46).
2. **Đóng băng R2.1–R2.6:** freeze index đánh dấu architecture, responsibility,
   contracts, decision log, hardening và roadmap là `FROZEN v1`; broad donor
   research đóng, chỉ còn targeted gap/implementation/provider qualification
   (`docs/r2/00_R2_FREEZE_INDEX.md`:1-23).
3. **Mở rộng có trình tự sau M8:** ADR-0080 định nghĩa M9–M12 để hoàn thành phần
   DISCOVER/DISTRIBUTE/LEARN còn lại, đồng thời cấm chúng thành parallel host
   authority (`ADR-0080`:5-22, 204-226). Văn bản còn chứa mâu thuẫn lịch sử cần
   được parent xác minh khi đánh giá hiện tại: front matter ghi `accepted`, nhưng
   phần acceptance nói “remains proposed” cho tới independent review
   (`ADR-0080`:1-3, 228-248). Memo này không tự giải quyết mâu thuẫn đó.

## Phân biệt bản commit với bản nháp live

Tại lúc trích xuất, root worktree có sửa đổi chưa commit đối với hai tài liệu
nguồn: `00_PRODUCT_VISION.md` (`+19/-1`) và `02_SYSTEM_REQUIREMENTS.md`
(`+29/-1`) so với `dbaf93a6`. Diff nháp thêm sequencing V1→V2, ràng buộc tất cả
gate phải là human decision, và tham chiếu ADR-0089/R2 V1 strategy. Vì các thay
đổi này chưa nằm ở commit baseline và có tham chiếu tới tài liệu working/untracked,
chúng **không được dùng làm authority hay kỳ vọng đã chấp nhận** trong bảng trên.
Đây là ghi nhận drift, không phải đánh giá nội dung draft.

## Giới hạn sử dụng

- Không kiểm tra code, test, runtime, evidence packet, Git HEAD ngoài baseline,
  hoặc mức độ hoàn thành hiện tại.
- Không suy luận từ roadmap/ADR rằng implementation hoặc production authority đã
  được cấp; chính ADR tách planning khỏi code, credentials, API calls, upload,
  publication, runtime activation và production approval
  (`ADR-0080`:223-248).
- Sponsor yêu cầu bỏ qua toàn bộ nghiên cứu/đánh giá license; memo này không dùng
  license như căn cứ hay blocker.

## Bổ sung khi tích hợp báo cáo hiện tại

Phần trên cố ý chỉ đọc baseline root `dbaf93a6`. Main đã kiểm tra thêm nhánh phát hành `0cef69a77` / evidence `18b74a17b`: ADR-0089 và R2_V1_PRODUCTION_RELEASE_STRATEGY.md **đã có trong lịch sử commit của nhánh phát hành**, dù bản root đang hiển thị chúng là untracked. Vì vậy trạng thái dirty ở root không đồng nghĩa quyết định V1-first chưa được chấp thuận trên nhánh đang chạy. POST_M8_ARCHITECTURE_ACCEPTED tại 016e0946 cũng giải quyết trạng thái chấp thuận của ADR-0080; phần “remains proposed” cũ không được dùng để phủ định acceptance record. Đánh giá hiện tại và các giới hạn nằm trong [báo cáo đối chiếu](2026-10-30-project-expectations-assessment.md).
