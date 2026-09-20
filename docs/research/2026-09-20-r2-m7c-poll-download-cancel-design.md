# R2-M7C: hiện trạng và thiết kế cho "exact-route poll/download/cancel"

Ngày nghiên cứu: 2026-09-20
Phạm vi: Task C3 còn lại của `docs/superpowers/plans/2026-09-12-r2-m7c-restart-event-recovery.md`
(sau khi H5 recovery scanner cho lease hết hạn đã xong, commit `df205ddf`/`b685e604`).
Trạng thái: nghiên cứu + thiết kế để chuẩn bị quyết định phạm vi; **không** sửa
`lib/generation_worker.py`/`server/app.py`/backend thật, không chạy SIGKILL
subprocess thật trong đợt này (theo quyết định của sponsor).

## Kết luận điều hành

Toàn bộ nhánh `poll`/`cancel`/`download` của tầng `ExecutionAttemptService`
(host-hardening, M7) hiện là **scaffolding chưa được nối vào bất kỳ đường chạy
thật nào**. Chỉ có hai việc thật sự chạy trong production hôm nay:

1. `submit` — qua `submit_video_attempt`/`build_attempt_submitter` (M7-A, Task 6).
2. `reconcile_expired` — scanner lease hết hạn vừa xây xong (M7-C Task C3, phần đã commit).

`poll`, `cancel`, và khái niệm "download" hoàn toàn không có call site sản xuất
nào gọi tới `ProviderExecutionAdapter.poll`/`.cancel` (0 kết quả grep trong
`lib/`, `r2/`, `server/` ngoài chính định nghĩa). Đường polling/cancel/download
"hạnh phúc" (happy path) mà người dùng thật đang dùng hôm nay vẫn hoàn toàn là
tầng cũ (`lib/media_generator.py` + `lib/video_backends/base.py` +
`lib/generation_worker.py`), không đọc/ghi `ExecutionAttempt`/`ProviderRouteSnapshot`
cho các bước sau submit.

Vá đúng nghĩa "Poll, download and cancel use only the persisted route snapshot"
(spec §5 mục 8) đòi hỏi hoặc (a) di trú toàn bộ happy path polling sang
`ExecutionAttemptService`, hoặc (b) một đường phục hồi hẹp hơn chỉ kích hoạt sau
khi phát hiện mất tiến trình. **Đã chọn (b)** — không phải quyết định mới, mà
là default kiến trúc đã chốt sẵn trong nghiên cứu gốc M7
(`docs/research/2026-09-12-r2-m7-host-production-hardening-research.md`, xem
§2.5 bên dưới); (a) bị chính nghiên cứu gốc loại vì "biến mọi running task
thành queued". (b) tái dùng gần hết hạ tầng đã có (`candidate_store`,
`usage_repo` execution↔ledger binding, `CommandReceiptRepository`) — chỉ thiếu
một registry route→adapter nhỏ. Vẫn là thay đổi runtime thật, đúng phạm vi
sponsor đã yêu cầu hoãn ở đợt này — tài liệu này chỉ dừng ở thiết kế.

## 1. Bản đồ hiện trạng (bằng chứng cụ thể)

### 1.1 Submit — đã nối (M7-A)

`lib/video_backends/execution_adapter.py:133` (`submit_video_attempt`) dựng
`ProviderRouteSnapshot` đầy đủ (`provider_id`, `provider_account_ref`,
`provider_model_id`, `backend_model_id`, `endpoint_id`, `submitted_base_url`,
`adapter_version`, `capability_profile_ref`) và gọi
`request.attempt_submitter.submit(...)` — đây là đường DUY NHẤT trong `lib/`
gọi vào `ExecutionAttemptServiceImpl.plan_and_submit`. Mỗi video backend
(`lib/video_backends/{gemini,kling,...}.py`) gọi hàm này tại điểm submit.

### 1.2 Poll — chưa nối

`grep -rn "\.poll(" lib r2 server` (loại trừ `tests/`) chỉ khớp chính định nghĩa
Protocol (`r2/host_hardening/ports.py:120`) và cài đặt generic
(`lib/video_backends/execution_adapter.py:196`,
`BackendExecutionAdapter.poll` gọi `self._functions.poll(attempt)`). Không có
nơi nào trong `lib/`/`server/` từng dựng một `BackendExecutionFunctions` với
`poll=` trỏ vào hàm thật của backend nào — `PollFn`/`BackendExecutionFunctions`
tồn tại như kiểu dữ liệu, chưa có instance thật.

Đường polling thật hôm nay nằm trong tầng cũ: mỗi `VideoBackend.generate()`
(Protocol `lib/video_backends/base.py:1315`) tự làm submit+poll+download trong
MỘT coroutine dài (block cho tới khi xong), và `VideoBackend.resume_video(job_id,
request)` (dùng khi worker khởi động lại và thấy task còn `provider_job_id`
nhưng chưa có kết quả) poll+download tiếp mà không submit lại. Cả hai đều dùng
`self._video_backend` — instance backend hiện tại của tiến trình đang chạy —
không đọc `ProviderRouteSnapshot` đã lưu.

`resume_video_async` (`lib/media_generator.py:1114`) — nơi gọi `resume_video`
— chỉ truyền lại đúng MỘT trường định tuyến gốc một cách tường minh:
`submitted_base_url` (comment tại chỗ: "là具名参数而非 version_metadata：nó là
giá trị replay của domain lúc submit, chỉ để backend poll dùng"). Mọi tham số
khác của request (`aspect_ratio`, `resolution`, `duration_seconds`,
`generate_audio`, `service_tier`, `seed`...) được XÂY LẠI từ tham số CALLER
truyền vào lúc resume — tức từ state/config hiện tại của lần gọi resume, không
phải một bản ghi bất biến từ lúc submit gốc. Nếu cấu hình model/account đổi
giữa submit và resume, `resume_video` gọi lại bằng backend/tham số MỚI, không
phải route đã submit — đúng cái khoảng trống mà spec §5 mục 8 muốn đóng.

### 1.3 Cancel — chưa nối, và thiếu hẳn một write authority

`BackendExecutionAdapter.cancel` (`lib/video_backends/execution_adapter.py:199`)
raise `BackendCapabilityUnsupportedError` trừ khi `self._functions.cancel`
được cấp — grep xác nhận **không backend thật nào** (`lib/video_backends/`,
`lib/custom_provider/`) từng dựng `BackendExecutionFunctions(cancel=...)`. Vậy
với mọi backend thật hôm nay, gọi `.cancel()` qua adapter này luôn raise.

Cancel thật hôm nay hoàn toàn ở tầng Task cũ, không đụng `ExecutionAttempt`:
`GenerationQueue.cancel_task` (`lib/generation_queue.py:732`) chỉ đổi trạng thái
Task trong DB task cũ rồi gọi `GenerationWorker.request_cancel`
(`lib/generation_worker.py:1065`), việc này chỉ làm
`asyncio.Task.cancel()` lên coroutine đang chạy trong CHÍNH TIẾN TRÌNH ĐÓ — một
tín hiệu in-process, O(1), không có lệnh gọi HTTP cancel nào tới provider được
tìm thấy trong chuỗi gọi này. Nói cách khác: "cancel" hôm nay là "ngừng chờ cục
bộ", không phải "báo provider hủy job từ xa".

Ở tầng host-hardening, bảng chuyển trạng thái hợp lệ
(`r2/host_hardening/transitions.py:44-58`) cho phép `ACCEPTED`/`RUNNING` ->
`CANCEL_REQUESTED`, nhưng **kho ba write authority** hiện có
(`transition_worker` — cần lease fence của chính worker;
`apply_provider_observation` — chỉ nhận sự kiện provider, không nhận ý định;
`resolve_operator_review` — chỉ nhận từ `NEEDS_OPERATOR`) không có method nào
cho phép một request cancel TỪ BÊN NGOÀI (API/user, không giữ lease của worker
đang chạy) đẩy attempt vào `CANCEL_REQUESTED`. Đây là một write authority thứ
tư còn thiếu hẳn, không phải một bug ở authority có sẵn.

### 1.4 Download — chưa có khái niệm trong contract

`ProviderExecutionAdapter` Protocol (`r2/host_hardening/ports.py:112-122`) chỉ
có bốn method: `submit`, `reconcile`, `poll`, `cancel`. Không có `download`.
"Download" trong spec §5 mục 8 và §7 ("local result-download failure: retry
download for the same remote job, never submit again") mô tả một BƯỚC nằm
trong luồng nghiệp vụ hiện có của `resume_video`/`generate` (tải file kết quả
về sau khi provider báo hoàn tất), không phải một method riêng của
`ProviderExecutionAdapter`. Đóng khoảng trống "exact-route download" tức là:
khi tầng host-hardening polling nhận `ProviderObservationKind.SUCCEEDED`, bước
tải file phải dùng lại đúng `provider_job_id`/route đã ghi, không được re-submit
— hành vi này chưa tồn tại vì poll của host-hardening chưa từng chạy tới bước
có kết quả `SUCCEEDED` trong thực tế.

## 2. Vì sao việc này khác về rủi ro so với M7-C Task C3 (đã xong)

Scanner `reconcile_expired` (đã commit) chỉ ĐỌC bảng `execution_attempts` và
chuyển trạng thái các attempt đã `SUBMITTING`/`CANCEL_REQUESTED` với lease hết
hạn — nó không đụng tới bất kỳ coroutine/backend đang chạy thật, không cần biết
gì về `lib.generation_worker`/`lib.media_generator`. Rủi ro chỉ nằm ở đúng CAS
logic đã test kỹ qua PostgreSQL thật.

Đóng khoảng trống poll/cancel/download đúng nghĩa lại yêu cầu MỘT trong hai:

- **(a) Di trú happy path**: thay `VideoBackend.generate()`/`resume_video()`
  bằng vòng lặp polling của `ExecutionAttemptService` cho MỌI video generation,
  kể cả khi worker không hề crash. Đây là thay runtime path chính, ảnh hưởng
  mọi video task đang chạy, rủi ro cao, đúng loại việc sponsor đã nói "chỉ nối
  sau khi test kỹ".
- **(b) Đường phục hồi hẹp**: chỉ thêm một service mới
  (`ExecutionAttemptRecoveryPoller` hay tương tự) kích hoạt CHỈ khi
  `reconcile_expired`/một scan khác phát hiện một attempt đã `ACCEPTED`/`RUNNING`
  (có `provider_job_id`) nhưng không có worker sống giữ lease — tức đúng kịch
  bản "process chết giữa poll, phục hồi bằng route đã lưu" mà H5 mô tả. Đường
  happy-path không-crash giữ nguyên tầng cũ, không đổi hành vi người dùng đang
  thấy hôm nay.

(b) khoanh vùng rủi ro nhỏ hơn nhiều và đúng tinh thần "scanner trước, nối
worker.start() thật sau" mà sponsor đã chọn cho Task C3 phần trước.

## 2.5 Quyết định: (b), không phải lựa chọn mới — đây là default đã chốt từ
nghiên cứu gốc

Trước khi tự chọn giữa (a)/(b), tôi đọc lại
`docs/research/2026-09-12-r2-m7-host-production-hardening-research.md` (nghiên
cứu gốc của cả M7, viết trước khi M7-A/B/C tồn tại) — đúng theo nguyên tắc
research-first (kiểm tra nghiên cứu/ADR đã có trước khi đề xuất). Tài liệu đó
ĐÃ trả lời chính xác câu hỏi (a) so với (b) từ 2026-09-12, ở hai chỗ:

> "Restart scanner chỉ lấy lease hết hạn. Nó resume poll/cancel nếu có remote
> ID, reconcile unknown nếu adapter khai báo capability, hoặc để operator xử
> lý; **nó không biến mọi running task thành queued**." (§2.4, dòng 180-182)

> "khi backend down, later exact-route poll/reconciliation ghi observation/outbox
> độc lập với worker; **restart scanner** resume từ durable state" (§4.1, dòng
> 248-250)

Cả hai câu đều mô tả đúng (b) — một scanner phục hồi hẹp, không phải di trú
happy path. Câu "nó không biến mọi running task thành queued" trực tiếp LOẠI
(a): (a) sẽ bắt MỌI task RUNNING (kể cả không hề crash) đi qua một cơ chế quản
lý mới — đúng cái nghiên cứu gốc đã cảnh báo không nên làm. Vậy đây không phải
một quyết định thiết kế MỚI của tôi — nó là default kiến trúc đã được chốt cho
M7 từ đầu; M7-C's Task C3 hiện có (`docs/superpowers/plans/2026-09-12-r2-m7c-restart-event-recovery.md`)
cũng gọi đúng cấu phần này là "Expired-attempt scanner" trong mục Interfaces,
khớp với cách đặt tên `reconcile_expired` đã xây.

**Kết luận: chọn (b).** Không cần nghiên cứu thêm để so hai phương án — câu hỏi
đã có câu trả lời trong tài liệu nền tảng của chính M7, và (b) cũng là phần mở
rộng tự nhiên, cùng một họ, với `reconcile_expired` vừa test xong qua PostgreSQL
thật.

### Reuse-first: hạ tầng đã có, chỉ cần nối dây

Kiểm tra thêm để tránh phát minh lại cái đã có (nguyên tắc reuse-first):

- **Download an toàn**: `lib/candidate_store.py::prepare_candidate` đã làm đúng
  toàn bộ phần "ghi file kết quả an toàn" (temp file cùng filesystem, fsync,
  verify digest/media probe, rename bất biến, replay idempotent nếu trùng
  identity+digest, quarantine nếu mismatch) — xây cho M7-B nhưng không đặc thù
  cho ảnh/candidate xuất bản, có thể dùng thẳng cho việc "tải xong rồi ghi an
  toàn" của recovery poller. Phần CÒN THIẾU chỉ là bước tải HTTP thật từ
  provider (đặc thù từng backend, đã có sẵn bên trong `resume_video`/`generate`
  của từng backend — chỉ cần bọc lại thành một hàm nhỏ, không viết lại).
- **Không double-charge**: `lib/db/repositories/usage_repo.py::UsageRepository.bind_execution`
  (dòng 170) đã ghi `ApiCall.execution_id` — tức mỗi `execution_id` đã có thể
  tra ngược ra đúng `api_call_id` đã mở lúc submit. Recovery poller khi chốt
  `SUCCEEDED`/`FAILED` có thể tái dùng đúng `ledger.resume_success`/`resume_failed`
  (đã có, đang dùng trong `resume_video_async`) keyed theo `api_call_id` tra
  ngược này — không cần cơ chế chống double-charge mới.
- **Cancel-intent idempotent**: `CommandReceiptRepository` (`lib/db/repositories/host_hardening.py:602`,
  đã dùng thật trong `task_repo.py:221-334` cho dedupe tạo task theo
  `(user_id, project_name, actor_scope, command_id)`) là đúng pattern cần cho
  authority cancel-intent thứ tư ở §3.1 — không cần phát minh cơ chế idempotency
  mới, chỉ tái dùng với `execution_id` thay vì `task_id` làm khoá kết quả.
- **`unsupported_poll` đã để lại đúng một câu gợi ý**: `r2/host_hardening/host_submit.py:112`
  (`AttemptSubmitter.submit`'s tạm adapter) cố tình raise
  `NotImplementedError("polling is owned by the backend adapter registered for
  this route")` — dòng comment này xác nhận ý định gốc: phải có một "registry"
  tra route → adapter thật (poll/cancel) cho recovery poller dùng, nhưng
  registry đó CHƯA tồn tại. Đây chính là mảnh ghép cần xây mới trong §3.2 bước
  2 ("dựng lại `ProviderExecutionAdapter` CHỈ từ `snapshot.route`") — không có
  gì để tái dùng ở đây, phải viết mới, nhưng phạm vi nhỏ (một hàm map
  `provider_id` + `adapter_version` → `BackendExecutionFunctions`, mỗi backend
  góp một entry).

## 3. Thiết kế đề xuất cho (b) — đường phục hồi hẹp

Không code trong đợt này; ghi lại để làm căn cứ khi được duyệt.

### 3.1 Cancel-intent: authority thứ tư

Thêm `ExecutionAttemptRepository.request_cancel(*, user_id, project_name,
execution_id, expected_version, command_id, actor_scope) -> AttemptSnapshot`:
CAS `ACCEPTED`/`RUNNING` -> `CANCEL_REQUESTED`, **không cần lease fence** (như
`apply_provider_observation`/`resolve_operator_review`), dedupe bằng
`CommandReceiptRepository` theo `(user_id, project_name, actor_scope,
command_id)` — tái dùng đúng pattern `task_repo.py:221-334` đã có, không phát
minh cơ chế idempotency mới. Method này KHÔNG tự gọi provider cancel API — nó
chỉ ghi Ý ĐỊNH; provider-side cancel (nếu backend hỗ trợ) là việc của adapter's
`cancel()` khi polling/recovery loop nhìn thấy `CANCEL_REQUESTED`.

### 3.2 Poll/cancel/download chỉ trong đường phục hồi

Một service mới (tạm gọi `AttemptRecoveryPoller`), chạy như một tác vụ nền độc
lập (không phải trong `GenerationWorker`'s slot loop hiện có), với chu kỳ:

1. Quét `ACCEPTED`/`RUNNING`/`CANCEL_REQUESTED` không có lease sống (mở rộng
   `list_lease_expired` hoặc thêm một scan tương tự cho các state này — chú ý
   `ACCEPTED`/`RUNNING` hôm nay không hề acquire lease qua host-hardening lease
   vì happy path chưa dùng service này, nên bước NÀY tự nó đã là một phần của
   việc di trú, không tránh được nếu muốn phục hồi thật).
2. Với mỗi attempt tìm thấy: acquire fence mới, dựng lại `ProviderExecutionAdapter`
   CHỈ từ `snapshot.route` (không đọc config hiện tại), gọi `.poll(attempt)`.
3. `SUCCEEDED` observation -> tải file bằng đúng `provider_job_id`/route (bước
   "download" thật), rồi `apply_provider_observation` để chốt state; lỗi tải
   file chỉ retry tải, không bao giờ submit lại (đúng spec §7).
4. `CANCEL_REQUESTED` quan sát thấy khi poll -> gọi `.cancel(attempt)` nếu
   backend hỗ trợ, rồi fold quan sát trả về.
5. Release fence, giống hệt pattern `release_lease` đã dùng trong
   `reconcile_expired` để không tự khóa `reconcile()`'s fence tiếp theo.

Điều kiện tiên quyết trước khi viết (a) hay (b) thật: mỗi backend
(`lib/video_backends/*.py`) cần một `BackendExecutionFunctions.poll`/`.cancel`
thật (bọc lại logic poll/cancel hiện có của chính backend đó, theo đúng lời
docstring của `execution_adapter.py` — "wiring... is that translation layer's
job, reused as-is rather than duplicated here"), và cần quyết định (a) so với
(b) trước, vì (b) vẫn để happy-path RUNNING poll ở tầng cũ (không dùng
`ExecutionAttemptState.RUNNING`/`ACCEPTED` một cách sống trong host-hardening
cho tới khi crash xảy ra) — nghĩa là attempt có thể ở `ACCEPTED` "âm thầm"
trong DB suốt cả quá trình chạy bình thường mà không ai theo dõi qua
host-hardening, chỉ được "nhìn thấy" nếu nó bị bỏ rơi.

## 4. Việc chưa biết / cần quyết định trước khi code

- Cancel provider-side thật: hôm nay dự án chưa có bất kỳ HTTP cancel call nào
  tới provider nào (kể cả ở tầng cũ) — cần xác nhận backend nào (Kling/Vidu/...)
  thực sự có API cancel trước khi hứa hẹn "provider-side cancel", nếu không
  `CancelFn` cho từng backend vẫn sẽ là `None` và `.cancel()` luôn raise
  `BackendCapabilityUnsupportedError` như hôm nay.
- SIGKILL subprocess test thật (barrier trước submit / sau chấp nhận / giữa
  poll / sau download / sau cancel) chỉ có ý nghĩa SAU KHI (a) hoặc (b) tồn
  tại — hiện tại không có gì để SIGKILL vì poll/cancel chưa chạy thật.

## 5. Nghiên cứu 2026-09-21: gỡ nút chặn "gia hạn lease" cho ACCEPTED/RUNNING

Sau khi D1-D3 xong (`dffbd892`), nút chặn còn lại duy nhất của H5 là:
happy-path không hề gia hạn lease của `execution_attempts` trong lúc
`ACCEPTED`/`RUNNING`, nên scanner theo kiểu `list_lease_expired` sẽ báo nhầm
mọi attempt đang chạy tốt là "bị bỏ rơi". Đào sâu thêm để xem có cách gỡ mà
KHÔNG cần "di trú toàn bộ happy path" (phương án (a) đã bị loại) hay không.

**Tìm thấy một seam có sẵn, đúng chỗ cần:** `poll_with_retry`
(`lib/video_backends/base.py:505`) — hàm polling dùng chung cho **mọi**
backend (cả đường `generate()` lẫn `resume_video()`, tức cả happy path lẫn
đường resume-sau-restart) — đã có sẵn tham số
`on_progress: Callable[[T, float], None] | None`, được gọi **mỗi vòng poll
chưa xong** (dòng 577-578), trước khi sleep. Đây đúng là điểm để "nhịp tim"
gia hạn lease, không cần phát minh cơ chế mới.

**Nhưng seam này chưa đủ dùng ngay, vì hai lý do cụ thể:**

1. `on_progress` hiện được **7 backend** (`kling`, `vidu`, `gemini`, `openai`,
   `ark`, `agnes`, `dashscope`) gọi riêng lẻ, mỗi nơi tự viết một lambda
   CHỈ để log (`lambda v, elapsed: logger.info(...)`), không hề nhận
   `execution_id`/context nào để biết phải gia hạn lease của attempt nào. Muốn
   dùng cho gia hạn lease, phải sửa **cả 7 điểm gọi** — đúng nghĩa "sửa vào
   đường chạy thật" của mọi video generation đang chạy hôm nay, không có cách
   nào làm ít hơn nếu muốn seam áp dụng cho toàn bộ backend.
2. `on_progress` là hàm **đồng bộ** (`Callable[[T, float], None]`), trong khi
   gia hạn lease cần một lệnh ghi DB **bất đồng bộ**. Hai lựa chọn, cả hai đều
   có đánh đổi thật:
   - Đổi `on_progress` sang async (`Callable[[T, float], Awaitable[None]]`) —
     đổi chữ ký hàm dùng chung, ảnh hưởng cả 7 call site cùng lúc dù chỉ muốn
     thêm 1 tính năng.
   - Giữ nguyên chữ ký, bắn `asyncio.create_task(renew())` kiểu fire-and-forget
     — không đổi chữ ký, nhưng phải tự quản lý: giữ tham chiếu task (tránh bị
     GC giữa chừng), bắt lỗi renew thất bại (exception trong task rời không ai
     await sẽ chỉ log ra global handler, không chặn được poll loop), và quyết
     định renew thất bại có nên làm gì khác không (hay chỉ log rồi thôi, chấp
     nhận có thể mất "quyền sở hữu" tạm thời).

**Kết luận:** cơ chế tồn tại, khả thi, phạm vi được xác định rõ (không phải
"di trú toàn bộ", nhưng CŨNG không phải "chỉ thêm code mới không đụng gì cũ" —
đây là sửa 7 file backend đang chạy thật). Đây đúng loại thay đổi runtime thật
mà sponsor đã yêu cầu hoãn cho tới khi có quyết định mở khóa rõ ràng — dừng ở
nghiên cứu, không code, đúng ranh giới đã áp dụng xuyên suốt D1-D3.

**Việc cần quyết định nếu mở khóa:** (i) đổi chữ ký `on_progress` thành async
hay giữ fire-and-forget; (ii) TTL gia hạn nên bao lâu (poll_interval hiện tại
là `VIDEO_POLL_INTERVAL_SECONDS`, cần TTL lease đủ lớn hơn khoảng đó để không
tự hết hạn giữa hai lần gọi `on_progress`); (iii) renew thất bại liên tục (vd.
mất kết nối DB) có nên làm gián đoạn poll loop đang chạy hay không — khuynh
hướng an toàn là KHÔNG (đừng để một lỗi ghi lease làm hỏng một video generation
đang chạy tốt), nhưng cần ghi rõ thành quyết định, không để ngầm định.
