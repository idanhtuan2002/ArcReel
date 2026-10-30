# Autonomous production: reuse và authority audit

Status: **RESEARCH FOR PROPOSED DESIGN**, 30/10/2026. Không phải implementation acceptance.

## Căn cứ

Source release đọc trực tiếp: `0cef69a772f1d2946e452b918a8839b0f37fd2d9` (`r2-v2.1.0`), checkout sạch `r2-v2-release-staging`. Root `dbaf93a625bd9e5499f1e50a6838355ff8c0c9e5` có tài liệu dirty ngoài phạm vi. Worktree evidence `r2-m10-c` base `77b42b2d7b254a5e59db8d7b0a57c53177888293` có một deletion media ngoài phạm vi, được giữ nguyên.

User yêu cầu mới: mặc định tự động hoàn toàn, có lựa chọn bán tự động, không cần người can thiệp hoặc chỉ thao tác tối thiểu. Đây là yêu cầu thiết kế thay đổi chính sách gate cũ, không phải lệnh giả danh Human ở endpoint hiện tại. Phạm vi từ ý tưởng đến phim/Quality/export; không suy ra quyền đăng lên nền tảng.

## Host reuse: source đã đọc và khoảng trống

| Owner hiện có | Source/call surface đã kiểm tra | Reuse / gap cụ thể |
|---|---|---|
| Workflow status/planner | `lib/workflow_rules.py`; `server/services/workflow_planner.py:73`; `lib/workflow_plan.py:223` | Reuse rules/next_action/admission; planner là side-effect-free projection, không phải một production run dispatcher |
| Queue và task persistence | `lib/db/repositories/task_repo.py:208,551,683`; `lib/generation_queue.py:413`; `lib/generation_worker.py:526,978` | Reuse task IDs, commands, batch/dependency, claim và executors. Cần durable liên kết transition→owner command/task, thay vì thêm queue provider khác |
| Terminal event hints | `TaskRepository._record_terminal_event:159`; `lib/task_terminal_events.py` | List trong session rồi emit project SSE sau commit; đây là refresh hint, **không phải durable outbox**. Controller phải phục hồi bằng DB reconciliation, không chỉ đợi SSE |
| Execution recovery | `server/services/execution_recovery_scheduler.py:57` | Reuse M7 reconciliation/cancel machinery. Scheduler này xử lý execution attempts; không chứng minh tự điều phối các stage sản xuất |
| Story | `server/story_authoring/{service,driver,executor,commit,authority}.py`; `server/routers/story_runs.py` | Reuse driver/manifest/revision/commit/handoff. Phase của run khác task status. Authority và commit hiện đòi Human Showrunner |
| Kịch bản | `server/tool_runtime.py:539,571,607,1850,1873`; embedded `video-workflow/SKILL.narration.md` | Reuse plan/script services và bounded model calls. Asset extraction và những hành động chỉ có trong skill cần adapter có structured output, receipt và formal write; không giả định toàn bộ tool đã có executor unattended |
| Composition | `server/services/presentation_read_model.py:324`; `server/services/jianying_draft_service.py:231`; embedded `compose-video/SKILL.md`; `r2/m3/composition.py` | Reuse exact materialized selections và audio/subtitle decisions. Compose skill chỉ hỗ trợ scenes, không đọc presentation; GoldenAComposer gắn Golden integration, chưa phải generic narration renderer |
| Promotion | `server/routers/gates.py:329,520`; `r2/production/approval_service.py:22` | Reuse actual SHA/path checks, source-master dependencies, metadata/currentness và transactional master protocol. Automatic actor phải đi qua authority mới, không truyền tên Human vào `selected_by` |
| Quality | `r2/contracts/quality.py:316,333`; `server/services/quality_{runs,dispositions,probes,probe_runtime}.py`; `server/routers/quality.py` | Đã có MODEL assessor class và independence slots; chưa suy ra có đủ qualified model producers. Human-only auth vẫn áp dụng cả service, không chỉ route. Cần automated authority, qualification và evidence producer cụ thể |

## Những ranh giới phải sửa bằng hợp đồng có phiên bản

- ADR-0089 hiện giữ bốn Human gates, bác auto-approve B/C. Yêu cầu mới cần amendment cho production run tự động; các quyết định lịch sử vẫn là Human. Gate D/publication giữ nguyên vì không nằm trong yêu cầu này.
- `r2/contracts/gates.py:20`: `authority_role=HUMAN_OPERATOR`.
- `r2/contracts/narrative_lifecycle.py:300,320` và `r2/contracts/adaptation.py:279`: `HUMAN_SHOWRUNNER`; story authority đọc signed grant và commit tạo Canon/Plan approvals. Không chỉ sửa UI hoặc auth dependency.
- `server/services/quality_runs.py:414,445` và `quality_dispositions.py:86,109`: reauthenticate interactive actor ở service. Bỏ chặn route vẫn không tạo automatic authority hợp lệ.
- ADR-0108 cho phép model reviewers **trong acceptance M8**, ghi rõ không đổi gates A–D hoặc review của milestone khác. Không dùng nó như quyền runtime tổng quát.

## Tài liệu chính thức và suy luận thiết kế

- [PostgreSQL SELECT](https://www.postgresql.org/docs/current/sql-select.html): `SKIP LOCKED` phù hợp tránh tranh chấp giữa các queue consumer, nhưng trả view không nhất quán. **Suy luận:** có thể dùng để claim run đến hạn; không dùng kết quả đó làm bằng chứng prerequisites/authority đầy đủ. Revalidate và fencing vẫn phải thực hiện riêng.
- [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html): có concat, audio mixing/resampling và subtitle filters. **Suy luận:** FFmpeg là backend khả thi cho renderer tiêu thụ presentation. Tài liệu filter không chứng minh renderer host đúng timeline, lineage hoặc audio policy; cần fixture và integration test.

Không chọn dependency workflow engine mới. Có durable intent/owner gap cụ thể, nhưng chưa có bằng chứng cần thay execution substrate hiện tại bằng Temporal hoặc một runtime donor.

## External donor: kiểm tra lại tại pin

Đã đọc audit donor trước đó `docs/research/2026-10-23-r2-m10-research-decision-donor-audit.md`, đặc biệt §5: OpenMontage, Kalinga, narrative donors và host composition. Kết quả lịch sử giữ nhãn supplied/historical, không coi là parity vừa chạy lại.

**Kiểm tra mới, không network/provider:** checkout `/home/anhtuan/Kalinga-Shorts-Factory`, HEAD và Git object pin `e4b5a2173ca03d365aad565a89fcc43159b44f9b`:

- Đọc `pipeline/src/make_video.py:317` bằng `git show <pin>:<path>`: `_safe_validate` trả True khi validator ném exception.
- Đọc `pipeline/src/evaluator.py:300–341`: repair giữ best effort khi hết vòng; file đầu ra không đồng nghĩa review pass.
- Fixture offline: trích đúng AST function `_safe_validate` ở pin, chạy ba callback trên cùng dummy path không đọc file. Kết quả: valid→True, invalid→False, validator_exception→True. Đây là bounded reproduction của lỗi fail-open, không phải full donor acceptance hoặc host parity.
- Có thử tìm `tests/test_make_video.py` ở pin; path không tồn tại. Không suy donor không có test ở đường khác.

**Disposition:** không lấy donor orchestration/authority runtime. Pattern bounded repair và negative fixture có thể dùng; host phải chặn lỗi validator, giữ artifact không đạt ở candidate và không cấp READY. Nếu port một function donor mới, phải thêm pin/fixture/parity tương ứng trước acceptance; audit này không cấp blanket reuse approval.

## Graph và giới hạn

Tier 2, `r2-v2-main`, fast generation `2026-10-15T01:19:44Z`; list/index confirmed. Đã search workflow/planner/scheduler/task repository/approval/assessor, trace planner và đọc snippet `WorkflowPlanner.get_plan`. Trace `TaskRepository.claim_next` bằng tên ngắn bị tool từ chối; dùng direct deployed source cho claim semantics, không coi đó là successful trace.

Coverage checked cho các evidence code paths: planner/rules/task repository/terminal hints/recovery scheduler/production approval/presentation/contracts có best-effort metadata match; Quality/story authority/commit/routes có missing index; gates metadata changed; embedded profile/docs excluded. Đã đọc source trực tiếp cho các claim. `server/services` scope có excluded cache; graph cũ không chứng minh absence toàn repo. Các finding về orchestration gap có phạm vi những đường entry/planner/executor/profile đã truy vết.

Chưa có live generation, E2E/restart, DB migration hoặc qualification run trong audit này. Model evaluator coverage, calibration corpus, GPU sharing và transaction interleavings là implementation acceptance gates, không phải kết quả đã đạt. Không sửa production hoặc donor checkout.
