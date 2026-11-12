# Rà soát lại workflow tự động theo từng công đoạn (2026-11-13)

- **Ngày:** 2026-11-13. **HEAD:** `ca23abc1031ebe38afe7ddd9f202bd2f0f68abac` (nhánh `impl/r2-film-quality` = tag `r2-v2.5.16` + 6 commit hôm nay; production chạy `r2-v2.5.16`).
- **Phương pháp:** audit chỉ đọc. Đối chiếu từng đề xuất của bản rà soát 11-08 và F1–F14 phía truyện với ADR-0111..0134 và mã nguồn tại HEAD (đọc trực tiếp + grep; graph codebase-memory đang trỏ checkout chính, `check_index_coverage` báo `freshness: missing` cho các file của worktree này, nên mọi trích dẫn mã đều từ đọc nguồn). Bằng chứng run thật lấy từ `docs/r2/evidence/R2_AUTONOMOUS_PRODUCTION_HANDOFF.md` (các mục 2026-11-03..2026-11-12) và `docs/r2/evidence/autonomous-run-2026-11-03/`. Không chạy test, không gọi model.
- **Nguồn:** [rà soát 11-08](2026-11-08-r2-workflow-stage-review.md); [tổng hợp 11-13](2026-11-13-r2-quality-roadmap-synthesis.md) (I1–I7, F1–F7 phía phim); [`R2_FILM_QUALITY_HANDOFF.md`](../r2/evidence/R2_FILM_QUALITY_HANDOFF.md); [stage-by-stage 11-11](2026-11-11-r2-donor-stage-by-stage.md) và [deep dive 11-11](2026-11-11-r2-donor-deep-dive.md) (F1–F14); ADR-0111..0134.
- **Nhãn:** **[F]** = sự thật có trích dẫn; **[I]** = suy luận; **[U]** = chưa biết. Không lặp lại I1–I7 / ADR-0133 / ADR-0134 — chỉ tham chiếu.

## Tóm tắt

- [F] Chuỗi 15 công đoạn đầy đủ về mặt luồng cho **narration**; **drama luôn bị từ chối** (`preflight.py:47-48` `DRAMA_ROUTE_NOT_QUALIFIED`, I2). Từ 11-08 đến nay mọi ADR (0114–0132) trừ 0133/0134 đều làm phía truyện; run phim tự động thật **duy nhất** sau 11-08 vẫn là `6de90785` (11-08, 26,1 s, REWORK ghi nhận).
- [F] Trong 8 đề xuất 11-08: 1 DONE ở mức mã nhưng **mặc định tắt** (chuyển thể), 3 PARTIAL, 4 NOT DONE (video thật, slideshow_risk, kiểm khoảng hở tường minh của plan có phần, cloud writer/reviewer chưa chạy thật). F1–F14 phía truyện: 12 DONE/quyết định xong, 2 đo rồi không xây (F5 weights, F13.4–5 giao cho judge), F10b bị loại có chủ đích.
- [F] Ba lỗ hổng mới tìm thấy làm phim tự động **không thực sự tự động hay đúng mục tiêu**: (a) `RunPolicy.target_duration_seconds=45` không được công đoạn nào đọc; (b) phim do autopilot tạo không bật chuyển thể và cần launch qualification **theo từng project**; (c) mặc định `local_only=True`, trần $5/run, craft judge chỉ Ollama — chặn tuyến cloud dù sponsor định hướng cloud.

## §1. Trạng thái đề xuất 11-08 và F1–F14

### 1a. Tám đề xuất 11-08 (`2026-11-08-r2-workflow-stage-review.md` §3)

| # | Đề xuất | Trạng thái | Bằng chứng |
|---|---|---|---|
| 1 | Công đoạn chuyển thể (biên kịch) + kế hoạch tập có xung đột/cliffhanger | **DONE (mã) / PARTIAL (thực tế)** | [F] ADR-0114; `lib/episode_adaptation.py` (logline, conflict, cliffhanger, cảnh theo nguồn; kiểm thứ tự trích đoạn, mở/kết nguồn, cast, hook ≤6 s `:49,260`, độ dài ±20 % mục tiêu `:50,263-273`, drama 3–8 cảnh, voiceover ≤30 %); RunStage `ADAPTATION`. [F] Mặc định `verbatim` (`episode_adaptation.py:66-71`); `TEMPLATE_FIELDS` của batch phim không có `episode_adaptation` (`autopilot_batch.py:25-40`) ⇒ phim autopilot đọc nguyên văn. [F] Không có reviewer model kiểm "trung thành với nguồn" (chỉ kiểm tất định). |
| 2 | Ngân sách độ dài lời đọc / khớp thời lượng | **PARTIAL** | [F] Adaptation ép độ dài theo mục tiêu; planner/script nhận mục tiêu mềm qua `episode_target_volume` (2,5 âm tiết/s, `lib/speech_rate.py:33`). [F] Handoff 11-09: "video ≥ TTS" đã có. [F] **`RunPolicy.target_duration_seconds` (=45, `r2/contracts/automation.py:129`) chỉ được ghi ở `composition.py:153`, không công đoạn nào đọc**; render chấp nhận 10–600 s (`render_adapter.py:66-76`). [F] Film look đặt 60–90 s (`server/story_authoring/film_looks.py:22-33`) trong khi policy giới hạn 30–60. [U] 2,5 âm tiết/s chưa đo trên VieNeu. Không có kiểm sau TTS (tổng audio đo được so mục tiêu). |
| 3 | Video thật bằng tuyến cloud | **NOT DONE** | [F] Chỉ có `scripts/r2/bakeoff_video_engines.py` (`806ec1d30`); mọi adapter cloud `UNQUALIFIED` (FILM handoff finding 1); launch profile ghim `still-clip-local` (`fiction_narration_vi_v1.json`). Cần keys. |
| 4 | Cổng `slideshow_risk` | **NOT DONE (hoãn có chủ đích)** | [F] Handoff 11-09: hoãn đến khi có tuyến video thật (sẽ đánh trượt mọi phim still-clip). grep 0 hit trong `lib server r2`. |
| 5 | Kiểm nguồn khi trích nhân vật + chặn beat thiếu danh tính | **PARTIAL** | [F] Tên nhân vật phải được nguồn nêu (`lib/asset_extraction.py:93` `named_in`, `ee6adc6b6`). [F] Không có câu trích nguyên văn, không kiểm cảnh/đạo cụ; không có identity-lock preflight (tổng hợp 11-13 F1). |
| 6 | Kiểm hở/chồng lấn kế hoạch tập | **DONE (tương đương)** | [F] Handoff 11-09: "planner anchors contiguous" (neo liên tiếp, `lib/episode_planner.py:466-492`). [I] Không có kiểm tất định riêng kiểu DramaClaw ngoài neo; đủ cho lát cắt liên tục. |
| 7 | Metadata đăng tải | **PARTIAL** | [F] `publish.json` (title, description từ logline/cliffhanger, tags, language, duration) + `thumbnail.jpg` = khung ở giây 1, không model (`lib/publish_metadata.py:43-70`), EXPORT kiểm lại (`packaging_adapter.py:231-285`). [F] Không có chapters, hashtag, series/playlist, thumbnail thiết kế (chữ, mặt, chọn khung), không adapter đăng tải (`packaging_adapter.py:9`). |
| 8 | Model cloud cho writer/reviewer | **PARTIAL (cấu hình sẵn, chưa chạy)** | [F] ADR-0113 (writer cloud theo endpoint, `vision_chat.py`, `gemini_reviewer.py` nối trong `composition.py:45`). [F] Chưa có run nào dùng cloud (FILM handoff "Next"). Cần keys. |

**Các dòng "Kém hơn/Thiếu" của bảng 11-08:**

| Dòng 11-08 | Trạng thái | Bằng chứng |
|---|---|---|
| 4 ASSET_ANALYSIS (kiểm nguồn) | PARTIAL | như #5 |
| 5b Chuyển thể (Thiếu) | DONE mã, tắt mặc định | như #1 |
| 6 Thiếu ngân sách độ dài lời đọc | PARTIAL | như #2 |
| 7 MEDIA storyboard (thiếu chặn beat thiếu danh tính) | PARTIAL | [F] ADR-0134 judge 11 kiểm + `prompt_fix` đã xây nhưng **chưa nối vào MEDIA** (chỉ `tests/…/test_continuity_judge.py` và `scripts/r2/qualify_continuity_judge.py` import nó) |
| 8 MEDIA video (kém nhất) | NOT DONE | như #3 (I1) |
| 9 Âm thanh (không nhạc nền) | PARTIAL | [F] ADR-0133 master −14 LUFS/−1 dBTP; không nhạc/SFX/ducking (I3), không điều khiển giọng (I4) |
| 10 RENDER (thiếu chuyển cảnh/nhạc) | NOT DONE | I3; không chuyển cảnh |
| 12 QUALITY (thiếu slideshow_risk) | NOT DONE | như #4; ADR-0133 thêm finding giao hàng MINOR |
| 13 PACKAGE (metadata) | PARTIAL | như #7 |
| 14 EXPORT (chưa đăng tải) | NOT DONE | `packaging_adapter.py:9` |

### 1b. F1–F14 phía truyện (`2026-11-11-r2-donor-stage-by-stage.md` §3, deep dive §6)

| Mục | Trạng thái | Bằng chứng |
|---|---|---|
| F1 giọng truyện cho writer | DONE | ADR-0128 §1 |
| F2 đoạn tự nhiên | DONE ở export; scene text chưa | ADR-0128 §10, "Deferred" |
| F3 đã xảy ra / digests | DONE (khối "[Cần tránh]" hoãn) | ADR-0128 §3, "Deferred" |
| F4 trường drama + closing hook | DONE; kiểm `CLOSING_HOOK` chỉ stylistic, ngưỡng chưa đo | ADR-0131 §5 |
| F5 nhiệm vụ theo vị trí | DONE; **trọng số cảnh đo rồi không xây** | ADR-0128 §5; ADR-0131 "Measured and not built" |
| F6 giọng + khuyết điểm nhân vật | DONE | ADR-0128 §6 |
| F7 kiểm nền seed | DONE (phần tất định + vẽ lại) | ADR-0128 §7 |
| F8 repair thấy kế hoạch + lịch sử | DONE | ADR-0128 §4 |
| F9 lọc tiêu đề | DONE | ADR-0128 §8 |
| F10a viết lại chương cuối khi kết chưa đóng | DONE | ADR-0128 §9 |
| F10b sàn xuất bản (chặn duyệt tự động) | KHÔNG LÀM (xung đột "tự động hoàn toàn") | ADR-0128 "Deferred" |
| F11 gộp anti-AI vào craft | DONE chỉ trên judge khác họ; writer giữ tách | ADR-0132 |
| F12 bỏ chỉ dẫn tự mâu thuẫn | DONE | ADR-0128 §2 |
| F13.1 POV / F13.2 rò chương sau / F13.3 tuổi | DONE | ADR-0131 §3,6,7 |
| F13.4–5 sống/chết, thứ tự thời gian | Giao cho continuity judge (không mã) | ADR-0131 §8 |
| F14 judge độc lập | DONE cho **local** (`gemma3:12b`); [F] production đang **tắt** gemma3:12b trên provider 1 nên part 2 không có craft judge (handoff 2026-11-12) | ADR-0132; `service.py:452-469` |

## §2. Bảng công đoạn tại HEAD

Cột: **Đủ?** (narration/drama) · **Chất lượng** (chỉ phát hiện mới/khác so với 11-08) · **Hiệu quả** · **Bền** · **Sẵn cloud** · **Giám sát**.

| Công đoạn | Đủ? | Chất lượng | Hiệu quả | Bền | Sẵn cloud | Giám sát |
|---|---|---|---|---|---|---|
| BRIEF | Có (cả hai) | [F] ADR-0125 rút ý tưởng/hồ sơ tự động, chống trùng ≥0,5 với 20 project gần nhất | [F] ~15 s (handoff 11-02) | [F] `RUN_CAPS_BELOW_STORY_BOUND` dừng sớm (ADR-0127 §1) | [F] writer cloud theo endpoint (ADR-0113); [F] craft judge chỉ chọn khi route là `ollama-chat` (`service.py:469`) ⇒ writer cloud = tự chấm craft | [F] "Hệ thống đã chọn" trên trang truyện (ADR-0125) |
| STORY | Có | [F] F1–F14 phần lớn xong (§1b); [I] chất lượng còn bị chặn bởi writer 9B | [F] ~93 s/call local; truyện ngắn 3–4 h (186 call, 11-02; 4 h 10 min run `6de90785`); book part 5 chương ~375 call ≈ 9 h | [F] power-loss tự hồi phục (11-12); ADR-0129/0130 tiếp quản; [F] `BLOCKED_BUDGET` wall clock 32 400 s (11-11, đã sửa bởi ADR-0127); `BLOCKED_QUALITY book_chapters[2]` sau ~5 h (11-10, đã sửa) | [F] trần USD story cloud 1..10 000 minor = ≤ $100 (`routes.py:159`); paid route không bao giờ top-up (ADR-0127); [U] chi phí cloud cho cả part (U5) | [F] reader bản nháp + "Written so far" (r2-v2.4.1), đọc các part trước (r2-v2.5.16); call không stream |
| STORY_COMMIT | Có | [F] commit tự động chấp nhận finding đã ghi (Shenbi accept-and-continue); F10b không làm | tức thời | [F] NARRATIVE_BRANCH cho part sau (`9d3822e78`) | không phụ thuộc model | [F] report liệt kê ngoại lệ đã chấp nhận (`/report`) |
| HANDOFF | Có | — | tức thời | [F] một lần, rename | — | — |
| ASSET_ANALYSIS | Có | [F] chỉ kiểm tên nhân vật (`asset_extraction.py:93`) | 1 call | [F] ghi nguyên tử theo revision | dùng route script | thumbnail giai đoạn (r2-v2.2.4) |
| EPISODE_PLAN | Có | [F] neo liên tiếp; mục tiêu thể tích mềm | vài call | — | — | — |
| ADAPTATION | **Chỉ khi `screen`** | [F] kiểm tất định mạnh (§1a #1); [F] không có review model về độ trung thành | 1 call + làm lại khi hỏng | — | route script | [F] bước trên canvas; [I] người không thấy bản chuyển thể trong run panel (không thấy route riêng) — [U] |
| SCRIPT_PLAN / SCRIPT | Có (narration) | [F] mục tiêu độ dài chỉ là prompt mềm (`project_manager.py:2408` "不做阻断"); `RunPolicy.target_duration_seconds` không ai đọc | [F] 15 s–10 min (11-08) | [F] quarantine + set-aside (11-03 attempt 2) | — | semi checkpoint `SCRIPT_PACKAGE` |
| MEDIA | Narration (still-clip); drama bị chặn | [F] ADR-0134 judge chưa nối; best-of-N tắt (judge local không qualify, 11-08) | [F] 9,5–10 min / 15–19 đơn vị local | [F] làm lại đơn vị ≤2; task local mất do restart được xếp lại 1 lần (ADR-0130 §2); `WORKFLOW_PATCH_EPISODE_SCRIPT` (11-03) | [F] tuyến cloud có trong registry nhưng adapter `UNQUALIFIED` (FILM handoff #1); Veo preview id chết (I7) | [F] thumbnail giai đoạn, "make 3 versions" thủ công |
| RENDER | Có | [F] ADR-0133 mastering | giây | [F] staging + hash | không phụ thuộc | — |
| MASTER | Có | — | giây | idempotent | — | — |
| QUALITY | Có | [F] gate `record` trên profile local ⇒ REWORK vẫn xuất (`fiction_narration_vi_v1.json` `quality_gate`); [F] reviewer local false positive (gemma `FRAME_UPSIDE_DOWN`, 11-03) | ~phút | [F] replay giữ lần ghi đầu (11-03) | [F] Gemini watch reviewer có (`gemini_reviewer.py`), flash qualify được, flash-lite không (tổng hợp F5) | [F] report điểm/finding; REWORK → MEDIA g+1 (r2-v2.2.4) |
| PACKAGE | Có | metadata tối thiểu (§1a #7) | giây | [F] zip tất định, hash | — | tải về có xác thực |
| EXPORT | Có (không đăng) | — | giây | [F] kiểm lại hash, publish.json, thumbnail | — | — |
| Autopilot (ADR-0124/0125) | Story: có; Film: **dừng ở preflight** | [F] film theo story, 1 tập/run (`r2/contracts/autopilot.py:43`) | [I] mỗi run phim chạy lại ASSET_ANALYSIS..EXPORT cho 1 tập | [F] mọi kết cục khác thành công ⇒ halt chờ Showrunner (`autopilot.py:239-247`); [F] `COMMAND_REPLAY_CONFLICT` một lần, chưa điều tra (11-11) | [F] `local_only` mặc định `True` ⇒ `CLOUD_ROUTE_FORBIDDEN` (`composition.py:144`, `preflight.py:87`); `max_cost_minor_units` mặc định 500 (`composition.py:147`) | [F] dòng autopilot + Resume (r2-v2.5.12); [F] không có cảnh báo ra ngoài app khi halt (không grep thấy notifier/webhook trong `server/production_run`) |

Ghi chú quan trọng cho autopilot phim: [F] preflight buộc launch qualification khớp `(user_id, project_name, …)` (`preflight.py:69-84`), handoff 11-10 ghi "batch-created films need per-project launch qualification and a published quality profile" ⇒ [I] "make films for finished stories" tạo project rồi **dừng `LAUNCH_PROFILE_NOT_QUALIFIED`** cho tới khi có người qualify từng project.

## §3. Bằng chứng run thật

| Run / ngày | Công đoạn: thời gian | Dừng / lỗi | Nguồn |
|---|---|---|---|
| Debug 11-02 | BRIEF 15 s; STORY 3 h 13 min (186 call, 1,21 M in / 129 k out) | 33 NARRATIVE_CRITICAL offered | handoff 11-02 |
| Official #1 11-03 | STORY 3 h 49 min | `scene_draft[3,2]: call cap 6` → sửa `ab544c4a7` | `autonomous-run-2026-11-03/official-attempt-1-*.json` |
| Official #2 11-03 | STORY 2 h 59 min | SCRIPT_PLAN quarantine (near-verbatim); MEDIA `WORKFLOW_PATCH_EPISODE_SCRIPT` | `official-attempt-2-*.json` |
| Official #3 11-03/04 | STORY 3 h 9 min, MEDIA 9,5 min, tổng 3 h 34 min | PASS; final 25,15 s | `official-attempt-3-succeeded.json` |
| `6de90785` 11-08 (production) | STORY 4 h 10 min (≈40 min chờ keep-alive), ASSET→SCRIPT_PLAN 10 min, MEDIA 10 min (15 task), QUALITY→EXPORT 2 min; tổng 4 h 33 min | REWORK ghi nhận (gemma3:4b story 3); final **26,1 s / mục tiêu 45 s** | handoff 11-08 15:27 |
| `du-an-01` book 30 ch 11-10 | ~5 h | `BLOCKED_QUALITY book_chapters[2]` (26 hook không trả được) → `book.settle_plan` | handoff 11-10 r2-v2.4.2 |
| Minh `story-7d7ff17…` 11-11 | 4 chương, ~93 s/call | `BLOCKED_BUDGET` wall clock 32 400 s, 349/375 call; truyện trôi khỏi ý tưởng; nam thành nữ (ADR-0126) | handoff 11-11 cast gender |
| Minh `0bc215c9` 11-11 | — | `BLOCKED_UNKNOWN` `AUTOMATION_GOVERNANCE_NOT_ACTIVATED` (worker trước authority) → ADR-0130 §4; scene có JSON trong prose, POV drift → ADR-0131 | handoff 11-11 |
| Minh (discarded) 11-11 | — | `COMMAND_REPLAY_CONFLICT` 1 lần, chưa điều tra | handoff 11-11 craft judge |
| `story-24a97fcd…` 11-12 | mất điện 14:28–17:58; tự tiếp tục 18:10 | không mất công (85→93 call); cần người chạy `v2-release-start.sh` (app không tự khởi động); JWT bị tạo lại | handoff 11-12 |

Tần suất (từ các mục trên, [F] đếm tay): dừng ở STORY 5/9 lần (call cap, budget, quality plan, governance, tiếp nối); SCRIPT_PLAN/MEDIA 2; QUALITY REWORK/false positive 2; hạ tầng (mất điện, app không autostart) 1. [F] Chưa có run phim nào với model cloud, chưa run phim nào từ autopilot. [U] Thời gian từng công đoạn của run book part 2 hiện tại (không ghi trong evidence).

## §4. Bổ sung / điều chỉnh xếp theo giá trị trên công sức

### A. Làm được ngay, không cần cloud key

| # | Gì | Vì sao (bằng chứng) | Donor / tham chiếu | Công sức | Key? |
|---|---|---|---|---|---|
| A1 | **Nối mục tiêu thời lượng end-to-end:** run phim ghi `episode_target_duration` của project từ một nguồn duy nhất (bỏ hoặc dùng thật `RunPolicy.target_duration_seconds`; thống nhất dải 30–60 với film look 60–90); thêm kiểm sau MEDIA: tổng TTS đo được ngoài ±20 % mục tiêu ⇒ REWORK về ADAPTATION/SCRIPT_PLAN; đo tốc độ VieNeu thay hằng 2,5 | §1a #2: field không ai đọc; 26,1/45 s | OpenMontage 2,5 w/s; DramaClaw `adjust_video_duration` | S | không |
| A2 | **Bật chuyển thể mặc định cho phim tự động** (`episode_adaptation=screen` trong template/batch và project phim mới) | §1a #1: autopilot phim đọc nguyên văn, không hook/nén | huohuo `drama_script_formatter` (đã hấp thụ ở ADR-0114) | S | không |
| A3 | **Launch qualification kế thừa** cho project phim do autopilot/batch tạo (qualify theo launch profile + routes ở cấp workspace/template thay vì từng project), cần ADR | §2 ghi chú: phim autopilot dừng `LAUNCH_PROFILE_NOT_QUALIFIED` | ADR-0123 (workspace grant) làm mẫu | M | không |
| A4 | **Nối ADR-0134 bước 3 vào MEDIA** (judge chạy sau unit checks, drift ⇒ tái sinh 1 lần với `prompt_fix` ghi provenance, `continuity.json`), sau cờ policy | judge đã xây, chưa có caller | AIVPE, ViMax `fd4b72e` | M | mã: không; bật: cần judge qualify (key) |
| A5 | **Hồ sơ cloud sẵn sàng:** mặc định `local_only` theo routes thực tế, trần `max_cost_minor_units` theo launch profile (dải $4–8/tập, tổng hợp N2), craft judge chấp nhận route cloud khác họ (`service.py:469` chỉ Ollama), thêm launch profile `*_cloud_v1` với `quality_gate: enforce` | §2: `CLOUD_ROUTE_FORBIDDEN`, $5/run, craft judge local-only, profile ghim local | — | S–M | mã: không; qualify: có |
| A6 | Backport Gemini Omni + gỡ id Veo preview chết | FILM handoff #2, I7 | upstream `4221a0cdc`, `b59f93382` | S–M | verify: có |
| A7 | **Cảnh báo ngoài app khi autopilot halt / run BLOCKED** (mail/Telegram/webhook) + tóm tắt thời gian & chi phí theo công đoạn trong report | halt cần Showrunner (`autopilot.py:239-247`), không có notifier; mất điện 11-12 phát hiện bằng tay | — | S | không |
| A8 | App tự khởi động sau reboot (systemd, Human sudo) | handoff 11-12 "not yet decided" | — | S | không |
| A9 | Điều tra `COMMAND_REPLAY_CONFLICT` | 1 lần, chưa điều tra (11-11) | — | S | không |
| A10 | Identity-lock preflight: chặn render beat có nhân vật không có tham chiếu; trích nhân vật kèm câu nguyên văn | §1a #5 | DramaClaw `render_identity_guard.py:20-37`, `structured_extraction.py:285-300` | S–M | không |
| A11 | Metadata đăng tải đầy đủ hơn: series/part/tập, hashtag, chọn khung thumbnail theo điểm judge thay vì giây 1, chữ trên thumbnail | §1a #7 | OpenMontage `export_bundle` | S (tất định) / M (model) | phần model: có |
| A12 | Bật lại `gemma3:12b` trên provider 1 (thao tác UI của operator) | part 2 chạy không craft judge | ADR-0132 | S | không |

### B. Cần cloud key / tài khoản

| # | Gì | Vì sao | Tham chiếu | Công sức |
|---|---|---|---|---|
| B1 | Bake-off video + TTS A/B → profile cloud qualified (OFFLINE_VERIFIED đã được sponsor duyệt) | I1; FILM handoff "Next" 1,3 | tổng hợp §4.1 | M |
| B2 | Qualify continuity judge cloud (ADR-0134) rồi bật A4 + best-of-N storyboard | I5 | ADR-0134 | M |
| B3 | Chuyển động thật + cổng `slideshow_risk`/no-silent-downgrade (sau B1) | §1a #4 | OpenMontage | M |
| B4 | Writer cloud cho truyện + đo chi phí một part (U5); cân trần $100 story cloud (`routes.py:159`) với book part ~375 call | §2 STORY | ADR-0113 | S cấu hình, M đo |
| B5 | Reviewer cloud + chuyển `quality_gate` sang `enforce` | QUALITY đang `record` | `gemini_reviewer.py`, F5 tổng hợp | S |
| B6 | Review model "trung thành nguồn" cho ADAPTATION (judge khác họ writer) | §1a #1 | — | S–M |
| B7 | Nhạc nền + ducking; TTS có cảm xúc (I3/I4) | — | openfilm | M |
| B8 | Drama: Kling elements + lip-sync route để gỡ `DRAMA_ROUTE_NOT_QUALIFIED` | I2 | tổng hợp §4.3 | L |
| B9 | Song song hoá các lời gọi độc lập của STORY khi route là cloud (audit các chiều của một chương, digest) | [I] trên local GPU chỉ có một model nạp được (ADR-0132 §1: swap 18–19 s) nên tuần tự là đúng; trên cloud thì không | — | M; [U] driver hiện có gọi song song hay không chưa kiểm |

Thứ tự đề xuất: A1 → A2 → A3 → A7/A8 → A5 → A4 → (keys) B1 → B2 → B3 → B5 → B4 → B7 → B8.

## §5. Sự thật / suy luận / chưa biết

- **Sự thật:** mọi dòng có trích dẫn file:line hoặc mục handoff ở trên; đặc biệt: `target_duration_seconds` không có reader; chuyển thể mặc định `verbatim` và không có trong template batch; continuity judge không có caller ngoài test/script; launch qualification gắn `project_name`; `local_only` mặc định `True`, trần $5/run; craft judge chỉ `ollama-chat`; run phim thật duy nhất sau 11-08 là `6de90785` (26,1 s).
- **Suy luận:** phim autopilot sẽ dừng ở preflight khi chưa qualify từng project; độ dài lệch mục tiêu chủ yếu do mục tiêu không được truyền/ép (không do TTS); song song hoá có ích chỉ trên cloud; thứ tự ưu tiên §4 và mức công sức.
- **Chưa biết:** tốc độ đọc thật của VieNeu tiếng Việt; chi phí cloud cho một part truyện; engine video nào thắng (U1); driver STORY có gọi song song không; phim autopilot có từng chạy trong production chưa (không có evidence); người có xem được bản chuyển thể trong run panel không; nguyên nhân `COMMAND_REPLAY_CONFLICT`.

## Ghi chú kiểm lại của main agent (2026-11-13)

- Đã kiểm lại nguyên văn: (a) `target_duration_seconds` chỉ được ghi vào policy (`server/production_run/composition.py:153`), không có chỗ nào đọc `policy.target_duration_seconds`; (b) `TEMPLATE_FIELDS` (`server/production_run/autopilot_batch.py:25-40`) không có `episode_adaptation` (`lib/episode_adaptation.py:41`); (c) preflight so `qualification.project_name` với project của run (`server/production_run/preflight.py:72-84`).
- Hiệu chỉnh A8: unit systemd `arcreel-v2-app` đã được bật ngày 2026-11-13 (ghi nhận sau mục handoff 11-12 mà audit dùng); việc còn lại chỉ là xác nhận ở lần khởi động lại kế tiếp.
- Hiệu chỉnh A12: `gemma3:12b` đã được bật trên provider 1 qua UI ngày 2026-11-13 (craft judge áp dụng từ book part 3); cần xác nhận trên production thay vì bật lại.
