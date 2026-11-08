# Rà soát workflow tự động hiện tại theo từng công đoạn, đối chiếu donor

Ngày 2026-11-08. Worktree `9b89`, nhánh `impl/autonomous-production` tại `ad51ae554` (production đang chạy `r2-v2.2.6`).
Phần donor dựa trên [donor stage mechanisms](2026-11-08-r2-donor-stage-mechanisms.md) (đọc mã tại commit đã pin; ba trích
dẫn quan trọng đã được kiểm lại nguyên văn: DramaClaw `structured_extraction.py:285-300`, `graph_build.py:188`, take
`orchestration.ts:131`), [best-of-N và judge](2026-11-08-r2-best-of-n-and-judge-retry-donors.md),
[provider linh hoạt](2026-11-08-r2-donor-model-provider-flexibility.md) và bảng chọn donor gốc
[`r2-origin/01_RESEARCH_SYNTHESIS.md`](r2-origin/01_RESEARCH_SYNTHESIS.md) §4–6 cùng ma trận
[`R2_02_FROZEN_RESPONSIBILITY_MATRIX.md`](../r2/R2_02_FROZEN_RESPONSIBILITY_MATRIX.md) §4. Ghi nhãn: **Sự thật** (có
nguồn), **Suy luận**, **Chưa biết**.

## 1. Kết luận

- **Sự thật:** chuỗi 14 công đoạn chạy được từ ý tưởng đến file xuất mà không cần người (run `6de90785`, 4 giờ 33 phút),
  với kiểm soát quyền, ghi bằng chứng và khôi phục sau sự cố mạnh hơn mọi donor (không donor nào có cổng kiểm định model,
  ghi trước từng lần thử hay đóng gói có lineage).
- **Sự thật:** chất lượng và hiệu quả còn kém ở ba chỗ, xếp theo tác động:
  1. **Thiếu bước chuyển thể/biên kịch giữa truyện và phim.** Truyện là sản phẩm thương mại độc lập (quyết định sponsor
     2026-11-08: không rút ngắn truyện cho vừa phim; STORY 4 giờ 10 phút là chi phí sản phẩm, không phải lãng phí). Nhưng ở
     chế độ narration, lời đọc của phim là **nguyên văn** truyện: prompt kịch bản yêu cầu voiceover "不改写、不润色、不删减、
     不补写" (`lib/prompt_builders_script.py:216`), chỉ lớp hình được chuyển thể. Một tập là một lát cắt nguồn trong sổ tập
     (`source_range`, `lib/episode_ledger.py`), nên nhịp phim là nhịp văn xuôi: không có hook mở đầu, không nén, không
     dựng lại cho màn hình. Mỗi run mặc định chỉ làm 1 tập (`max_target_episodes` = 1, tối đa 12, `settings.py:70`).
  2. **Độ dài phim trượt mục tiêu:** launch profile đặt 45 giây (`fiction_narration_vi_v1.json`), phim ra 26,1 giây; không
     công đoạn nào canh độ dài lời đọc theo mục tiêu.
  3. **Hình gần như tĩnh:** clip là ảnh tĩnh chuyển động Ken Burns (`still-clip-local`); không donor sản xuất phim nào dừng
     ở đó; reviewer gemma3 chấm story 3/5, kết quả `REWORK` chỉ được ghi nhận vì gate là `record`.
- **Sự thật:** bộ "Director Stack" đã chọn lúc thiết kế R2 (take → Jellyfish → ai-short-film → Butterfly) **không nằm
  trong đường chạy tự động**: `server/production_run`, `server/media_tools` và `lib/media_generator.py` không dùng
  `ShotSpec`, `PromptPlan`, `TakeDirector` hay `VisualIdentityProfile`. Đường chạy dùng kịch bản gốc của ArcReel (đã có
  `shot_type`, `camera_motion`, `video_prompt.action` trong `lib/script_models.py`) và catalog tham chiếu nhân vật.
  **Suy luận:** đây không phải thiếu sót lớn — chính take không truyền ảnh tham chiếu trong code batch (chỉ `prompt`,
  `orchestration.ts:131`), nên lấy cơ chế cụ thể của DramaClaw/ViMax/huohuo đáng giá hơn cả bộ stack.

## 2. Từng công đoạn

Thang đánh giá so với donor tốt nhất ở công đoạn đó: **Tốt hơn**, **Ngang**, **Kém hơn**.

| # | Công đoạn | ArcReel hiện tại (sự thật) | Donor đã chọn (thiết kế R2) | Donor làm tốt nhất (sự thật) | Đánh giá |
|---|---|---|---|---|---|
| 1 | BRIEF | Brief từ ý tưởng + writer route đã đóng băng, Gate A duyệt tự động theo grant (`story_adapter.py`) | Novel Studio / Huohuo | ViMax: một lời gọi cho truyện ngắn | Ngang (có digest, grant; donor không có) |
| 2 | STORY (sản phẩm độc lập) | Đồ thị node (seed, bible, outline, chapter plan, scene draft, review, packaging), chỉ làm lại node bẩn; cơ chế Shenbi (review từng chiều, giữ bản tốt nhất, chuẩn hoá độ dài), Huohuo (vá liên tục, khử lặp), prompt Novel Studio (`server/story_authoring/`) | Novel Studio + Huohuo + Shenbi + StoryBox | Huohuo: bộ nhớ theo cuốn (world bible, nhân vật, sổ cốt truyện, chuỗi nhân quả) + change record cuối chương + dải độ dài + dừng khi trì trệ (`novel-writing.ts:546-683,1272-1392`) | Ngang về cơ chế (chất lượng thương mại còn tùy model writer). StoryBox (mô phỏng nhân vật) không dùng |
| 3 | STORY_COMMIT / HANDOFF | Duyệt manifest qua `AutomaticNarrativeAuthority`, không duyệt khi còn finding mở; giao bản thảo vào nguồn một lần | R2 Canon Kernel | Không donor có cổng commit | Tốt hơn |
| 4 | ASSET_ANALYSIS | Một lời gọi theo schema trích nhân vật/cảnh/đạo cụ, bỏ tên đã có, ghi nguyên tử với source revision (`lib/asset_extraction.py`); **không kiểm tên/miêu tả có trong truyện** | Huohuo / DramaClaw | DramaClaw: câu trích phải có nguyên văn trong đoạn, tên phải được truyện viết ra, gộp thận trọng (`structured_extraction.py:285-300,489-512`); ViMax sinh ảnh nghiêng/sau từ ảnh chính diện, lỗi thì dùng ảnh chính diện | Kém hơn ở kiểm chứng nguồn |
| 5 | EPISODE_PLAN | Cửa sổ planner đến khi mọi tập mục tiêu có trong ledger (`text_adapter.py`) | Huohuo (batch planning) | DramaClaw: schema `EpisodePlan` (khoảng chương, xung đột, cliffhanger, sự kiện, 3–6 nhân vật) + kiểm khoảng hở/chồng lấn tất định — reviewer/fixer chưa nối dây trong checkout (`graph_build.py:188`) | Ngang; thiếu kiểm khoảng hở/chồng lấn |
| 5b | **Chuyển thể / biên kịch** (chưa có) | Không có công đoạn: narration đọc nguyên văn truyện; chỉ lớp hình được chuyển thể (`prompt_builders_script.py:183-216`) | Huohuo (Adaptation Authority, `R2_02` "Adaptation planning — Huohuo-derived") | huohuo `drama_script_formatter`, nối dây ở `drama-episode-pipeline.ts:400`: đoạn truyện → kịch bản phân cảnh có tiêu đề cảnh, thoại đẩy xung đột, nén dẫn chuyện, cảnh 30–60 giây, tập 1–3 phút, 3–8 cảnh, không đổi kết; dài hơn nguyên văn 20–30% do định dạng, không do thêm tình tiết | **Thiếu** |
| 6 | SCRIPT_PLAN / SCRIPT | Kế hoạch kịch bản + xác nhận nội dung theo grant, rồi kịch bản cuối; schema có `shot_type`, `camera_motion`, `video_prompt.action`, `image_prompt` | take (shot grammar) + Butterfly (PromptPlan) | huohuo: hợp đồng storyboard `ceil(duration/3)` đoạn prompt 3 giây gắn scene/character id; OpenMontage: kiểm cảnh 5 khía cạnh + biên dịch enum→prompt; DramaClaw: cấm camera tĩnh, tên nhân vật, từ cảm xúc trừu tượng trong prompt keyframe | Ngang về schema; **thiếu ngân sách độ dài lời đọc** (OpenMontage 2,5 từ/giây) |
| 7 | MEDIA – storyboard | ComfyUI FLUX.2 klein 4B; catalog tham chiếu nhân vật/cảnh qua `@[tên]`; kiểm tất định từng ảnh, làm lại ≤2 lần; best-of-N có sẵn nhưng tắt (judge local chưa qua kiểm định) | ai-short-film (identity) + Butterfly (prompt) | ViMax chọn tối đa 8 ảnh tham chiếu ưu tiên cùng góc máy/gần nhất; DramaClaw lời nhắc khoá danh tính + chặn render beat thiếu nhãn danh tính (`render_identity_guard.py:20-37`); huohuo gói tối đa 6 ảnh tham chiếu | Ngang–kém: có tham chiếu và kiểm từng ảnh (donor không có), thiếu chặn beat thiếu danh tính |
| 8 | MEDIA – video | Ảnh tĩnh + Ken Burns cục bộ | DramaClaw (media gateway) | huohuo first+last frame tuần tự; ai-short-film nối khung cuối sang shot sau; ViMax chỉ sinh khung cuối khi biến đổi vừa/lớn; DramaClaw `adjust_video_duration` (cắt, giãn ≤1,5×, đóng băng khung cuối) | **Kém hơn rõ nhất** |
| 9 | MEDIA – âm thanh | VieNeu TTS từng câu, kiểm tất định (độ dài, im lặng, âm lượng), làm lại ≤2 lần; không nhạc nền | VieNeu (youtube-agentic-ai-studio) | DramaClaw SRT từ độ dài audio đo được từng beat; Butterfly tổng hợp từng câu, 3 lần thử, trả danh sách lỗi một phần; OpenMontage thử một câu trước | Ngang (kiểm tất định tốt hơn); thiếu nhạc nền (donor cũng yếu: huohuo chỉ dùng sóng sine) |
| 10 | RENDER | FFmpeg từng đơn vị theo contract rồi nối, giải mã kiểm toàn bộ, hash nguồn trước/sau, staging rồi mới công bố (`lib/presentation_renderer.py`); phụ đề sidecar | Remotion / FFmpeg | Mọi donor đều nối FFmpeg/MoviePy; OpenMontage là donor Remotion duy nhất và cấm hạ cấp renderer âm thầm | Tốt hơn về kiểm chứng; thiếu chuyển cảnh/nhạc |
| 11 | MASTER | Gate C dùng lõi chung, hash lại với render manifest, idempotent theo bước | ArcReel | Không donor có | Tốt hơn |
| 12 | QUALITY | Hai reviewer VLM độc lập đã kiểm định, kiểm phụ đề/khung tất định, finding chỉ đúng segment, REWORK tự làm lại đúng segment khi `enforce` | Shenbi (reviewer độc lập) | DramaClaw reviewer tập (contact sheet); OpenMontage `slideshow_risk` (cổng tất định trước render); Jellyfish `retry_guidance` | Tốt hơn về kiểm định; **thiếu `slideshow_risk`** — phim hiện tại chính là slideshow |
| 13 | PACKAGE | Zip tất định: MP4, phụ đề, manifest render, hai review, lineage | ArcReel | OpenMontage `export_bundle`: metadata, chapters, ý tưởng thumbnail, `publish_log` theo schema | Tốt hơn về lineage; thiếu metadata đăng tải |
| 14 | EXPORT | Kiểm lại hash từng archive và final; không công bố URL | Distribution adapters | Không donor nào upload (grep huohuo, DramaClaw, ViMax, take) | Ngang; chưa có đăng tải |

## 3. Đề xuất theo giá trị trên công sức (suy luận)

1. **Công đoạn chuyển thể (biên kịch) giữa truyện và kịch bản.** Truyện giữ nguyên là sản phẩm; mỗi tập phim được chuyển
   thể từ lát cắt truyện của nó thành kịch bản cho màn hình dọc: hook vài giây đầu, nén dẫn chuyện, thoại/độc thoại đẩy xung
   đột, kết bằng cliffhanger, không đổi tình tiết và kết thúc. Với narration là "kịch bản lời kể" (nén và dựng lại, không
   đọc nguyên văn); với drama là kịch bản phân cảnh có thoại (huohuo `drama_script_formatter`). Bản chuyển thể có bằng chứng
   lineage về đoạn truyện gốc và được reviewer kiểm "trung thành với nguồn". Cùng với đó, kế hoạch tập phủ toàn bộ truyện
   (DramaClaw `EpisodePlan`: xung đột, cliffhanger, sự kiện chính; kiểm hở/chồng lấn). Công sức: vừa–lớn (công đoạn mới,
   cần ADR). Giảm thời gian STORY thì bằng model writer mạnh/nhanh hơn, không bằng rút ngắn truyện.
2. **Ngân sách độ dài lời đọc và khớp thời lượng (SCRIPT + MEDIA).** Kiểm tổng độ dài narration theo mục tiêu (OpenMontage
   2,5 từ/giây; với tiếng Việt cần đo tốc độ VieNeu) trước khi sinh media; khớp clip với độ dài audio như
   `adjust_video_duration` của DramaClaw. Công sức: nhỏ.
3. **Video thật bằng tuyến cloud (MEDIA video).** Đã mở được nhờ "thử tuyến media" (ADR-0113): chọn một model image-to-video,
   dùng first-frame (huohuo) và chỉ thêm last-frame khi biến đổi lớn (ViMax) để giảm chi phí. Cần credential và một lần
   probe.
4. **Cổng `slideshow_risk` tất định (QUALITY trước render).** Rẻ, và chặn đúng lỗi hiện tại khi gate là `enforce`.
5. **Kiểm nguồn khi trích nhân vật (ASSET_ANALYSIS).** Câu trích nguyên văn + tên phải xuất hiện (DramaClaw); chặn render
   beat thiếu danh tính. Công sức: vừa.
6. **Kiểm khoảng hở/chồng lấn của kế hoạch tập (EPISODE_PLAN).** Sao chép phần kiểm tất định của DramaClaw, không dùng
   fixer chưa nối dây. Công sức: nhỏ.
7. **Metadata đăng tải (PACKAGE).** Tiêu đề, mô tả, chương, ý tưởng thumbnail theo `export_bundle` của OpenMontage; sau đó mới
   là adapter đăng tải. Công sức: nhỏ.
8. **Model cloud cho writer/reviewer** (đã sẵn sàng cấu hình sau `r2-v2.2.6`): cần credential; nên làm cùng mục 1 để so
   chất lượng trên truyện ngắn.

## 4. Chưa biết và giới hạn

- **Chưa biết:** thời gian/chi phí thực tế mỗi tập của huohuo, DramaClaw, ViMax, take (chỉ OpenMontage công bố chi phí:
  ≈$1,33 cho 60 giây). Không so được tốc độ end-to-end.
- **Chưa biết:** cách huohuo chia truyện thành tập; các donor chỉ có trên GitHub (Shenbi, ai-short-film, Butterfly,
  Jellyfish) mới được đọc nông.
- Số đo phía ArcReel chỉ từ một run production (`6de90785`) với model local; chưa có run nào dùng model cloud.
- Bảng chọn donor gốc thuộc kiến trúc R2 dài hạn (Canon, Epistemic, Director Stack); run tự động hiện chỉ dùng phần cơ chế
  đã liệt kê ở cột "ArcReel hiện tại".
