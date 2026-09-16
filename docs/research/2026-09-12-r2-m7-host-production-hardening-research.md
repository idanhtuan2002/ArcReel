# R2-M7 Host Production Hardening: nghiên cứu và mặc định đề xuất

Ngày nghiên cứu: 2026-09-12
Phạm vi: H1-H8, Golden A/B gần production, browser workflow và operator
handoff.
Trạng thái: nghiên cứu để chuẩn bị ADR/spec; **không** phải production approval,
không chạy migration/provider trả phí/backup hay restore trên hệ thống thật.

## Kết luận điều hành

M7 không nên bổ sung một queue hoặc một workflow engine thứ hai. Mặc định có lợi
nhất cho ArcReel là gia cố host hiện hữu bằng bốn primitive nhỏ nhưng sâu:

1. **execution attempt journal** trong PostgreSQL, với identity và request digest
   bất biến, provider route snapshot, lease và trạng thái `SUBMIT_OUTCOME_UNKNOWN`;
2. **immutable candidate media + một authoritative master pointer** được đổi bằng
   transaction/CAS; promotion không overwrite master bytes đang dùng;
3. **durable task event log/outbox** làm nguồn replay cho SSE, còn in-memory
   channel chỉ là wake-up/low-latency projection;
4. **backup set manifest** liên kết PostgreSQL recovery point với toàn bộ media
   object/path/version/checksum, chỉ được công nhận sau restore drill sang target
   sạch.

Những primitive này khép cùng lúc H1-H7 và giữ một authority cho task, artifact
và master. H8 nên là compatibility pipeline có pin SHA, range/inventory diff,
migration rehearsal, contract/regression/Golden smoke và review thủ công; không
merge upstream thẳng vào release branch.

Đề xuất checkpoint M7 là `M7-A identity/idempotency`, `M7-B promotion`, `M7-C
recovery/events`, `M7-D backup/telemetry`, `M7-E compatibility/qualification`.
Chỉ `M7-E` mới có thể tạo hồ sơ `PRODUCTION_CANDIDATE`; production vẫn cần
approval riêng sau provider canary, security check, clean-target restore và
launch checklist.

## 1. Cơ sở nội bộ và giới hạn bằng chứng

Frozen roadmap định nghĩa M7 là chặng re-earn production maturity và yêu cầu H1-
H8, execution identity, idempotency, atomic promotion, restart recovery,
backup/restore, observability và upstream compatibility
([roadmap](../r2/R2_06_FROZEN_IMPLEMENTATION_ROADMAP.md)). Project review cụ thể
hóa thêm failed regeneration giữ master cũ, kill/restart/cancel/backend-down/SSE
loss, restore PostgreSQL + media sang target sạch, Golden A/B gần production,
browser E2E, runbooks và human/operations approval
([status review](../r2/evidence/PROJECT_STATUS_REVIEW_2026-09-07.md)). Reuse research
đã kết luận H1-H8 là host-specific; donor provider scripts chỉ phù hợp làm
reference adapter, không thay ArcReel runtime
([reuse map](2026-09-07-r2-reuse-map-and-completion-gates.md),
[donor review](2026-09-09-r2-donor-reuse-maximization.md)).

Đối chiếu source hiện tại bằng Codebase Memory Tier 2 trên worktree M5C gần nhất,
generation `2026-09-12T10:40:56Z`, full index, HEAD
`2dbfad701dc11dd3127e8fefd4e6830de3c73b09`; coverage check trả
`no_recorded_issue` và `metadata_match` cho các path dưới đây. Đây vẫn là tín
hiệu best-effort, không phải chứng minh đã audit toàn codebase.

- `TaskRepository.persist_execution_provider_id()` tự mô tả `provider_id` là
  advisory và **không phải execution identity**
  (`lib/db/repositories/task_repo.py:1058-1069`).
- `persist_provider_job_id()` lưu job ID/endpoint/base URL sau submit trong một
  transaction riêng, không có status guard (`lib/db/repositories/task_repo.py:966-992`).
  Vì job ID chỉ tồn tại sau response, vẫn có failure window: provider nhận việc,
  process chết hoặc mất response trước khi local DB biết remote ID.
- `should_retry_submit()` đã làm đúng một phần quan trọng: chỉ retry transport
  error chắc chắn chưa gửi và không retry `AmbiguousSubmitError`
  (`lib/video_backends/base.py:280-292`). Nhưng fail-fast một ambiguous submit
  chưa đồng nghĩa đã reconcile remote outcome.
- R2 promotion hiện có compare-and-swap manifest callback
  (`r2/production/artifact_bridge.py:116-144`) và test về rollback/concurrency.
  M7 vẫn phải chứng minh failure boundary giữa database, manifest và media store.
- Frontend giữ `lastEventId` và gửi `Last-Event-ID` khi reconnect
  (`frontend/src/utils/sse-stream.ts:63-213`), trong khi `SseChannel.broadcast()`
  chỉ phát vào subscriber queues trong memory (`server/sse_channel.py:200-207`).
  Client cursor không thể tự phục hồi event mà server không lưu bền.

## 2. H1-H2: execution identity, idempotency và ambiguous outcome

### 2.1 Hai phương án khả thi

| Phương án | Failure window | Chi phí | Hệ quả kiểm thử |
|---|---|---|---|
| A. Mở rộng một dòng `task` bằng `provider_job_id`, retry count và status | Vẫn có cửa sổ provider đã nhận nhưng DB chưa có job ID; retry/concurrency khó phân biệt cùng attempt với attempt mới; lịch sử bị overwrite | Ít migration/code nhất | Unit tests dễ, nhưng kill đúng giữa submit/response không thể được chứng minh an toàn nếu provider không có client token |
| B. Bảng execution attempt bất biến + task head + client idempotency token + reconciliation | Cửa sổ dual-write vẫn tồn tại về vật lý, nhưng trở thành trạng thái quan sát được `SUBMIT_OUTCOME_UNKNOWN`; provider-native token biến retry thành cùng remote operation | Thêm bảng, transitions, sweeper và adapter capability | Có thể fault-inject tại mọi edge; kiểm tra uniqueness, restart, duplicate webhook/poll và remote completion |
| C. Đưa toàn workflow sang durable workflow engine | Engine có thể replay orchestration, nhưng provider call vẫn cần idempotency/reconciliation; thêm một control plane và migration lớn | Cao nhất cho single-operator host | Cần test determinism, worker versioning và vận hành engine ngoài toàn bộ host tests |

**Khuyến nghị: B.** C giải quyết nhiều hơn phạm vi M7 và tạo authority/runtime thứ
hai. A không thể biểu diễn trung thực unknown outcome. Provider API có client
token cho thấy một request có thể retry an toàn với cùng token; AWS EC2 yêu cầu
`ClientToken` để tạo idempotent request và công bố retry rules theo response
([AWS EC2 idempotency](https://docs.aws.amazon.com/ec2/latest/devguide/ec2-api-idempotency.html)).
Đây là pattern cần qualification trên từng provider, không phải giả định mọi
provider đều hỗ trợ.

### 2.2 Identity và invariant đề xuất

Mỗi logical task có một `task_id`; mỗi lần thực thi được cấp một `execution_id`
và một `attempt_no`. Record attempt phải chốt trước submit:

```text
execution_id (UUID/ULID, PK)
task_id + attempt_no (UNIQUE)
request_digest
provider_kind + provider_account_ref + endpoint + model/version
client_token (UNIQUE trong provider/account scope, nếu provider hỗ trợ)
provider_job_id (nullable, unique trong provider/account scope khi đã biết)
state + state_version
lease_owner + lease_expires_at
submitted_at/last_observed_at/terminal_at
cancel_requested_at
trace_id_at_creation
```

ADR/spec refinement after adversarial review: the persisted lease also carries a
monotonically increasing `lease_token`; owner name alone cannot fence a stale
worker that reacquires under the same name. Attempt identity is the scoped
`(user_id, project_name, task_id, attempt_no)` key, with `execution_id` and all
semantic fields required to match on exact replay.

`request_digest` phải bao phủ payload canonical, asset/version refs, provider
route/model và generation parameters; cùng idempotency key nhưng digest khác phải
fail `IDEMPOTENCY_PARAMETER_MISMATCH`, tương tự cách client-token API từ chối
tham số không khớp. Không dùng trace ID, process ID hoặc lease ID làm execution
identity: chúng đổi qua restart/retry.

Idempotency cần bốn lớp độc lập:

1. API command: `(actor_scope, command_id)` trả lại cùng task/receipt;
2. queue claim: lease không tạo execution mới nếu attempt đang recoverable;
3. provider submit: cùng `client_token + request_digest`, không blind retry unknown;
4. result ingest/promotion: provider event và candidate receipt có dedupe key,
   master CAS chỉ áp dụng một lần.

### 2.3 State machine đề xuất

```text
PLANNED
  -> SUBMITTING
      -> ACCEPTED(provider_job_id)
      -> SUBMIT_OUTCOME_UNKNOWN
      -> FAILED_BEFORE_ACCEPTANCE
ACCEPTED -> RUNNING -> SUCCEEDED | FAILED | CANCEL_REQUESTED
RUNNING  -> SUCCEEDED | FAILED | CANCEL_REQUESTED
CANCEL_REQUESTED -> CANCELLED | SUCCEEDED | FAILED | CANCEL_OUTCOME_UNKNOWN
SUBMIT_OUTCOME_UNKNOWN -> ACCEPTED | RUNNING | SUCCEEDED | FAILED | CANCELLED
                       | FAILED_BEFORE_ACCEPTANCE | NEEDS_OPERATOR
CANCEL_OUTCOME_UNKNOWN -> CANCELLED | SUCCEEDED | FAILED | NEEDS_OPERATOR
NEEDS_OPERATOR -> ACCEPTED | RUNNING | SUCCEEDED | FAILED | CANCELLED
                | FAILED_BEFORE_ACCEPTANCE
```

ADR/spec refinement after adversarial review: `NEEDS_OPERATOR` is non-terminal
and only an immutable operator-resolution receipt can leave it. Unknown states
also accept direct proved terminal observations without inventing a synthetic
`ACCEPTED` event. `NOT_FOUND` proves non-submission only for a qualified lookup
that is authoritative after its declared settling window; otherwise it remains
unknown or pauses for operator evidence.

`SUBMIT_OUTCOME_UNKNOWN` và `CANCEL_OUTCOME_UNKNOWN` là non-terminal, không đồng
nghĩa failed/cancelled. Terminal observation từ provider thắng event cũ hoặc
cancel intent: cancel là yêu cầu, không phải bằng chứng remote job đã dừng.
Replicate minh họa vì async create trả prediction ID cùng `get`/`cancel` URL,
polling có thể tiếp tục sau timeout
([create/poll prediction](https://replicate.com/docs/topics/predictions/create-a-prediction));
webhook terminal có retry, có thể duplicate và hiếm khi out of order
([webhook semantics](https://replicate.com/docs/topics/webhooks/receive-webhook)).
Do đó ingestion phải monotonic và idempotent; không cho event `processing` đến
muộn làm lùi một terminal state.

### 2.4 Reconciliation policy

- Provider có native idempotency token và get-by-token/create replay: retry bằng
  **cùng** token/digest; không cấp token mới.
- Provider trả job ID trước khi stream body hoàn tất: persist ngay receipt tối
  thiểu, rồi poll bằng endpoint snapshot đã chốt.
- Provider không có native token nhưng có list/search theo metadata: reconcile
  bằng bounded time range + exact digest metadata; >1 match thành
  `NEEDS_OPERATOR`, không chọn tùy ý.
- Provider không có token hay lookup: ambiguous submit **không tự submit lại**.
  Giữ attempt unknown, cảnh báo khả năng tính phí và chỉ cho operator xác nhận
  retry mới. Đây là fail-closed cần thiết, không phải một retry bug.
- Restart scanner chỉ lấy lease hết hạn. Nó resume poll/cancel nếu có remote ID,
  reconcile unknown nếu adapter khai báo capability, hoặc để operator xử lý; nó
  không biến mọi running task thành queued.

## 3. H3-H4: giữ master cũ và atomic promotion

### 3.1 So sánh

| Phương án | Failure window | Chi phí | Test implication |
|---|---|---|---|
| A. Render/ghi đè trực tiếp đường dẫn master rồi cập nhật DB/manifest | Process chết giữa overwrite và metadata commit có thể làm master bytes mới nhưng pointer/approval cũ; rollback phải copy ngược | Code ngắn, recovery đắt và mơ hồ | Fault injection dễ chứng minh mất master; không chấp nhận cho M7 |
| B. Candidate immutable, checksum trước; promotion chỉ CAS một pointer trong DB/manifest | Upload thành công nhưng DB fail chỉ tạo orphan an toàn; DB không trỏ candidate cho đến khi bytes đã durable | Cần immutable naming, staging, CAS và GC | Kiểm tra được mọi cut point; old master luôn resolve hoặc new master đã fully staged |
| C. Distributed transaction giữa DB và object store | Object store phổ biến không tham gia XA; vận hành coordinator vượt nhu cầu | Rất cao | Phải chứng minh coordinator recovery và heuristic outcomes |

**Khuyến nghị: B.** Với local filesystem, ghi temp cùng filesystem, flush/fsync,
verify size/hash rồi atomic rename vào immutable final path; Linux `rename()` có
atomic replace nhưng không hoạt động xuyên mount và NFS có ambiguous failure
semantics
([rename(2)](https://www.man7.org/linux/man-pages/man2/renameat.2.html)). Với
object store, upload vào content-addressed/versioned key và verify HEAD/checksum,
sau đó DB pointer commit. S3 có strong read-after-write cho một object, nhưng
không có atomic multi-key update và concurrent same-key PUT là last-writer-wins
([S3 consistency](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html));
do đó không dùng overwrite nhiều key như transaction. Conditional writes có thể
ép create-only/CAS semantics
([S3 conditional writes](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes-enforce.html)).

### 3.2 Promotion protocol

1. Tạo `candidate_id` và immutable destination từ content hash; không đổi master.
2. Stage bytes, verify expected length/hash/media probe; fsync hoặc chờ successful
   object PUT/HEAD.
3. Trong DB transaction, lock/CAS master head theo `expected_master_version`, xác
   minh candidate thuộc đúng project/artifact, approved và bytes resolve được.
4. Ghi master pointer, promotion receipt, usage link và outbox event trong cùng
   transaction. Transactional outbox tránh dual-write DB/event; consumer vẫn
   phải idempotent vì delivery có thể lặp
   ([AWS transactional outbox](https://docs.aws.amazon.com/en_en/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html)).
5. Publish event sau commit. Orphan candidate được GC bằng retention policy riêng;
   GC không nằm trong promotion transaction.

Regeneration failed ở bất kỳ bước nào trước 4 chỉ làm candidate/attempt failed;
master pointer cũ và bytes cũ không đổi. CAS conflict không tự promote candidate
trên một master head mới. Restore/retry cũng cần `expected_master_version` và
new promotion receipt thay vì mutate lịch sử.

Fault injection tối thiểu: trước/sau temp write, trước/sau fsync/PUT, sau rename,
trước lock, trước DB commit, ngay sau commit trước publish, duplicate publish,
CAS conflict, disk-full, checksum mismatch, object timeout và process SIGKILL.
Mỗi cut phải chứng minh đúng một trong hai trạng thái: old master hoàn chỉnh hoặc
new master hoàn chỉnh; không có pointer dangling.

## 4. H5: kill/restart/cancel/remote completion/timeout/SSE loss

### 4.1 Recovery architecture

Hai lựa chọn chính là (A) rebuild trạng thái từ task row + provider poll khi
worker start, hoặc (B) execution journal + leases + durable observation/event
log. A ít schema hơn nhưng không giữ được transitions, duplicate provider events
hay submit unknown. **Chọn B**; current queue/task remains scheduler authority,
journal chỉ làm execution evidence và recovery seam.

Worker protocol:

- claim bằng conditional lease; mọi mutation kiểm tra `execution_id` và
  `state_version` để fenced worker cũ không ghi sau khi lease mất;
- persist attempt trước network call; heartbeat không đổi identity;
- poll timeout chỉ kết thúc một poll request, không tự kết luận remote failed;
- khi backend down, later exact-route poll/reconciliation ghi observation/outbox
  độc lập với worker;
  restart scanner resume từ durable state;
- result download vào immutable candidate, verify rồi ingest idempotently;
- cancel ghi intent trước, gọi provider sau; restart tiếp tục reconciliation;
- terminal state không lùi, duplicate/out-of-order observation chỉ bổ sung raw
  evidence hoặc no-op.

Webhook behavior remains valuable research input, but M7 v1 deliberately does
not add a receiver. Every M7 profile records `supports_webhook=false`; signature,
replay protection, tenant routing and rate limiting require a later reviewed
extension.

### 4.2 SSE là projection, không phải authority

WHATWG định nghĩa `Last-Event-ID` để client gửi cursor khi tái kết nối
([HTML SSE standard](https://html.spec.whatwg.org/dev/server-sent-events.html)).
Để cursor có ý nghĩa, server cần durable ordered event sequence:

```text
event_id (monotonic per project/stream)
project_id, task_id, execution_id
event_type, state_version, occurred_at
public_payload, payload_schema_version
trace_id, outbox_published_at
dedupe_key UNIQUE
```

SSE handler đọc `Last-Event-ID`, authorize project scope, replay `(cursor, high
watermark]` từ DB, sau đó subscribe live và bù lại gap giữa watermark/subscription.
Delivery là at-least-once; frontend dedupe bằng event ID. Nếu cursor đã ngoài
retention, trả typed `EVENT_CURSOR_EXPIRED` kèm snapshot/resync route, không giả
vờ stream liên tục. In-memory broadcast chỉ đánh thức reader; event tồn tại dù
không subscriber hoặc process chết.

## 5. H6: PostgreSQL + media backup/restore nhất quán

### 5.1 Hai mức khả thi

| Phương án | RPO/RTO và failure window | Chi phí | Khi phù hợp |
|---|---|---|---|
| A. Write fence/maintenance window, logical/physical DB backup + copy media + manifest | RPO bằng chu kỳ backup; RTO gồm full restore; có downtime nhưng consistency dễ giải thích | Thấp, hợp first drill/single operator | Baseline M7 và dataset vừa; vẫn phải test restore sạch |
| B. `pg_basebackup` + continuous WAL/PITR, immutable/versioned media và retention-fenced manifest | RPO theo WAL archive lag; RTO phụ thuộc base size + WAL replay; ít/no downtime nhưng nhiều monitoring | Cao hơn, tốt cho production candidate | Khi benchmark và operator runbook chứng minh archive/restore |

PostgreSQL mô tả base backup + WAL archive cho PITR và lưu ý phải giữ đủ chuỗi
WAL từ base backup
([PITR](https://www.postgresql.org/docs/current/continuous-archiving.html)).
`pg_verifybackup` kiểm tra manifest/files/checksums/WAL nhưng tài liệu chính thức
vẫn yêu cầu test restore thực
([pg_verifybackup](https://www.postgresql.org/docs/current/app-pgverifybackup.html)).
RPO là mức mất dữ liệu tối đa tính từ recovery point; RTO là thời gian gián đoạn
tối đa cho phép
([AWS Well-Architected definitions](https://docs.aws.amazon.com/wellarchitected/2022-03-31/framework/rel_planning_for_recovery_objective_defined_recovery.html)).

**Khuyến nghị theo hai chặng:** M7-D trước hết phải qua A để có clean-target proof,
đồng thời thiết kế schema/media immutable để B khả thi. `PRODUCTION_CANDIDATE`
chỉ chấp nhận B nếu deployment target yêu cầu RPO thấp và archive-lag/restore
benchmark đã đạt. Mặc định đo thử ban đầu cho single operator là `RPO <= 15 phút`
và `RTO <= 4 giờ`; đây là test hypothesis để benchmark, không phải cam kết kinh
doanh chưa được phê duyệt.

### 5.2 Backup set protocol

Một backup set phải có ID, source deployment, exact app/image/PostgreSQL version,
schema/Alembic head, DB backup identifier + WAL range/recovery target, và media
manifest gồm project/artifact/version/key-or-path/object-version/size/checksum.
Nếu dùng versioned object store, lưu exact version ID; S3 chỉ định rõ GET với
`versionId` lấy đúng biến thể, không nhất thiết current
([retrieve object versions](https://docs.aws.amazon.com/AmazonS3/latest/userguide/RetrievingObjectVersions.html)).

Protocol an toàn:

1. tạo backup lease/fence ngăn GC xóa media referenced trong lúc backup;
2. chốt DB recovery point và backup ID;
3. tạo media manifest từ cùng authoritative snapshot/recovered DB, không từ một
   directory listing không gắn DB;
4. copy/retain immutable media versions, verify checksum; chỉ sau đó mark backup
   set `COMPLETE`;
5. restore vào PostgreSQL cluster/database và media root/bucket prefix **trống**;
6. chạy migrations ở chế độ phù hợp với exact release (không tự nâng version),
   integrity queries, enumerate toàn bộ approved master/candidate refs và mở/probe
   media;
7. chạy Golden A/B read/review/export smoke không gọi provider, ghi measured RTO
   và recovery point/RPO; destroy test target sau lưu evidence nếu runbook cho phép.

Chỉ copy media rồi backup DB sau (hoặc ngược lại) mà không có immutable refs/fence
sẽ tạo split snapshot. DB-only restore không đạt H6 dù SQL integrity xanh.

## 6. H7: correlation và redaction

### 6.1 Hai phương án

| Phương án | Lợi ích | Rủi ro/chi phí |
|---|---|---|
| Structured logs với custom correlation IDs | Nhanh, ít dependency | Context propagation/restart links tự viết; dễ cardinality cao và field lệch |
| OpenTelemetry trace + correlated logs + durable domain IDs | Chuẩn hóa trace/span context, backend-neutral; domain IDs tồn tại qua async/restart | Cần sampling, Collector config, allowlist/redaction và storage budget |

**Khuyến nghị: OTel + domain identity.** OTel Logs có `TraceId` và `SpanId` để
correlate log với execution context
([OTel Logs specification](https://opentelemetry.io/docs/specs/otel/logs/)).
Nhưng trace ID không thay task/execution/candidate/master/usage IDs; khi một worker
resume ở trace mới, dùng span link và các durable IDs làm attributes để giữ chuỗi:

```text
request_id -> method_id -> task_id -> execution_id
-> provider_kind + provider_job_ref_hash
-> candidate_id -> master_version -> usage_entry_id
```

Không đưa raw prompt/script, signed URL, API key, Authorization/Cookie, provider
token, webhook secret, local absolute path, email hay full provider response vào
span/log. Dùng allowlist attribute schema; provider job ID có thể hash/HMAC cho
dashboard chung và chỉ lưu raw trong access-controlled operational store. OTel
nhấn mạnh data minimization và cung cấp attribute/filter/redaction/transform
processors
([handling sensitive data](https://opentelemetry.io/docs/security/handling-sensitive-data/)).
Baggage có thể bị tự động gửi tới third-party API, nên không đặt project/user/
secret/provider refs trong baggage và clear baggage tại provider boundary
([OTel baggage security](https://opentelemetry.io/docs/concepts/signals/baggage/)).

Acceptance phải có secret canary strings trong config/request/provider response
và scan toàn log/span/event evidence khẳng định không xuất hiện; đồng thời mỗi
Golden execution phải join được theo durable IDs từ request tới usage/master.

## 7. H8: upstream compatibility gates

### 7.1 Lựa chọn

| Phương án | Failure window | Chi phí |
|---|---|---|
| A. Manual cherry-pick/merge rồi chạy full suite | Dễ bỏ sót upstream file deleted/renamed, migration/config/dependency changes; khó tái lập quyết định | Thấp mỗi lần, cao khi regression |
| B. Pinned compatibility candidate pipeline | Không loại hết semantic regression, nhưng biến input/diff/gates thành reproducible evidence | Vừa; cần scripts/manifests |
| C. Continuous mirror/rebase | Drift ít nhưng conflict liên tục và có thể kéo upstream change chưa qualified vào fork | Cao cho single operator |

**Khuyến nghị: B**, vẫn có manual acceptance. Mỗi candidate ghi current host SHA,
upstream remote URL + old/new SHA, merge-base, exact integration method và
generated change inventory. `git range-diff` hữu ích để con người so hai phiên
bản patch series, nhưng output là porcelain không ổn định nên không dùng làm
machine gate duy nhất
([Git range-diff](https://git-scm.com/docs/git-range-diff)).

Gate theo thứ tự:

1. verify source/pin/signature hoặc checksum và license manifest;
2. inventory file/API/config/env/dependency/migration/provider changes;
3. build merge in isolated worktree; no unresolved conflict;
4. schema upgrade rehearsal trên restored production-like snapshot và downgrade/
   forward-fix plan; không chạy trên production;
5. static/type/import/dependency/i18n/frontend/website gates;
6. host contract tests H1-H8, provider adapter recordings và full regression;
7. Golden A/B no-provider restore smoke, rồi bounded qualified-provider canary khi
   credentials/budget được duyệt;
8. browser create -> generate -> review -> regenerate failed -> old master intact
   -> approve -> export; kiểm tra cross-project/user denial;
9. compatibility report phân loại `UNCHANGED`, `ADAPTED`, `DEFERRED`, `REJECTED`
   cho từng relevant upstream change, có rollback target.

Không dùng “merge sạch” hay “full tests xanh” riêng lẻ làm bằng chứng compatible:
schema, provider semantics, recovery và browser behavior là các gate độc lập.

## 8. Provider qualification và fault/chaos matrix

Qualification có ba tầng; mock-only không thể cấp `QUALIFIED`:

1. offline contract: canonical request, redaction, retry classification, recorded
   responses, malformed payload, status monotonicity;
2. provider sandbox/test mode nếu có: native token/dedupe, get/cancel/webhook
   verification, quota/rate-limit, output retention;
3. bounded paid canary sau explicit credentials/budget approval: một nhỏ nhất cho
   mỗi route Golden cần dùng, đo cost/latency/artifact integrity và cleanup.

| Fault/case | Điểm tiêm | Evidence bắt buộc |
|---|---|---|
| Concurrent duplicate submit | hai workers/cùng command | một execution attempt; một remote job nếu native token; không double usage |
| Connect failure chắc chắn chưa gửi | trước request bytes | bounded retry cùng attempt/token |
| Read timeout/connection loss mơ hồ | sau request, trước response | `SUBMIT_OUTCOME_UNKNOWN`; reconcile hoặc operator, không blind resubmit |
| Kill worker | trước submit, sau remote accept, sau persist ID, giữa poll, sau download, trước/after promotion commit | restart đi đúng endpoint/attempt; không duplicate; old master giữ nguyên cho đến commit |
| Backend down khi remote completes | webhook refused và worker absent | provider observation nhận lại hoặc poll reconciliation; terminal/result ingest một lần |
| Duplicate/out-of-order webhook | handler | signature/auth check; monotonic terminal state; one candidate/usage |
| Cancel races completion | cancel request song song terminal success/failure | intent lưu bền; observed terminal truth thắng; không báo cancelled giả |
| Provider timeout/rate-limit/5xx/4xx | submit và poll riêng | retry policy theo phase/capability; cost cap; typed terminal/unknown |
| SSE disconnect/proxy drop/browser sleep | trước/sau event commit và publish | replay từ cursor, dedupe, hoặc typed resync khi retention gap |
| Disk full/object timeout/checksum mismatch | candidate stage/promotion | no master pointer change; orphan quarantined/GC later |
| DB deadlock/serialization/CAS conflict | attempt transition/promotion | whole transaction retry bounded; state_version/master expected ref enforced |
| PostgreSQL unavailable | event ingest/promotion | không ack authoritative transition nếu chưa commit; remote poll later |
| Restore missing/corrupt media | clean target verification | backup rejected; exact refs/checksums identify loss |

Provider capability record cần chốt theo exact provider+API version: native
idempotency, token scope/TTL, lookup by token, poll/get, cancel semantics,
webhook signature/retry/order, deadline, output retention, rate-limit headers,
request/response size, data region và cost signal. Capability không chứng minh
bằng interface mock; phải có official doc snapshot và probe evidence tại version
được qualified.

## 9. Checkpoint và exit evidence đề xuất

### M7-A — H1/H2 Identity and Idempotency

- persisted attempt journal và exact transition table;
- concurrency + kill-after-submit tests;
- adapter capability contract, unknown-outcome reconciliation;
- machine evidence: exact HEAD/schema head, test IDs, fault points, duplicate
  remote count và usage count.

Exit: `EXECUTION_RECOVERY_VERIFIED`; không còn đường submit trả phí nào chạy ngoài
attempt identity hoặc waiver fail-closed được phê duyệt.

### M7-B — H3/H4 Candidate and Promotion

- immutable candidate protocol, checksum, CAS master pointer, outbox;
- exhaustive bounded fault injection quanh stage/commit/publish;
- failed regeneration và concurrent promotion giữ old master.

Exit: `ATOMIC_PROMOTION_VERIFIED`; mọi fault point chứng minh pointer resolve và
không mất approved master.

### M7-C — H5 Restart and Event Recovery

- lease fencing, restart scanner, cancel reconciliation, remote-complete-while-
  down;
- durable event log + SSE replay/resync;
- real process kill/restart test, không chỉ tạo object/service mới trong cùng
  process.

Exit: `RESTART_AND_STREAM_RECOVERY_VERIFIED`.

### M7-D — H6/H7 Restore and Observability

- backup-set manifest và retention fence;
- `pg_verifybackup`/tool-equivalent **và** clean-target restore drill;
- enumerate/open/probe 100% approved master refs và Golden A/B export smoke;
- measured RPO/RTO; complete correlation joins; secret canary scan zero leak.

Exit: `RECOVERY_VERIFIED`.

### M7-E — H8 Compatibility, Golden and Operations

- pinned upstream candidate report và toàn compatibility gates;
- qualified real provider cho mọi path được release; unqualified routes disabled;
- Golden A và dual-profile Golden B trên near-production config với cost/latency/
  lineage/approval evidence;
- browser workflow create -> review -> regenerate -> approve -> export, cross-
  project/user denial và reconnect/resume;
- runbooks deploy/config/secrets/backup/restore/retry/cancel/rollback/incident/cost
  cap, image/dependency pins và launch checklist.

Exit: hồ sơ `PRODUCTION_CANDIDATE`. Hồ sơ phải machine-readable, bind exact Git
SHA/image digest/schema head/provider capability versions/config fingerprint và
evidence hashes; clean worktree, không required skip và waiver phải explicit.
Production activation, migration, provider spend lớn, cleanup hay publish vẫn
cần approval riêng.

## 10. Near-production Golden A/B và browser evidence

Near-production không có nghĩa dùng production data hoặc public endpoint. Nó
nghĩa cùng release image, PostgreSQL major/config class, queue/worker process
boundaries, media backend mode, reverse proxy/SSE behavior, auth/project scope,
telemetry/redaction và resource/cost caps; secrets là dedicated test credentials.

- Golden A: explainer có nội dung/audio/caption, generation failure rồi retry,
  review/approval/master/export, process restart và stream reconnect.
- Golden B: cùng Canon Golden B chạy cả Western generic và CN short-drama 爽文
  profile, preserve exact approved adaptation lineage; một failed regeneration
  không đổi master; browser review chọn/approve/export đúng project scope.
- Mỗi run lưu request/method/task/execution/provider/candidate/master/usage IDs,
  cost/latency, artifact checksums, screenshots hoặc browser trace đã redacted,
  và exact config/provider qualification refs.
- Chạy ít nhất một restore-derived no-provider smoke trước paid canary để chứng
  minh restored artifacts thực sự review/export được.

## 11. Những fact chỉ có thể đóng ở vòng live/operations sau

Các mục này không chặn ADR/spec/local fixtures, và không nên biến thành câu hỏi
kiến trúc chung cho người dùng. Chúng là evidence gate tại đúng checkpoint:

- deployment thật dùng local filesystem, shared/NFS hay object store nào; atomic
  rename/versioning/conditional-write/checksum capability thực tế;
- exact PostgreSQL major, backup tool/storage, WAL archive latency, dataset/media
  size và measured backup/restore throughput;
- provider/account nào được release, native idempotency token scope/TTL, lookup,
  cancellation, webhook signature/retry, result retention, quotas và pricing;
- approved credentials, canary budget/cost ceiling và data-region/security terms;
- production RPO/RTO do business chấp nhận sau benchmark;
- reverse proxy/load balancer idle timeout/buffering và browser auth topology;
- log/trace backend retention, access controls và acceptable telemetry cost;
- production hostname/network/private-access, secret manager và launch window;
- explicit approval để chạy paid provider, restore drill trên infrastructure,
  migration/activation/publish hoặc cleanup.

Không được “mặc định provider có idempotency” hay “S3-like có S3 semantics” nếu
chưa probe exact service/version. Nếu live fact không đạt capability, adapter bị
disable hoặc đi vào fail-closed operator path, không nới invariant.

## 12. ADR đề xuất và kiểm chứng bắt buộc khi triển khai

Các ADR nên tách theo authority/failure boundary để review độc lập:

1. **ADR-M7-1 — Durable Execution Attempt Identity and Ambiguous Outcome:**
   identity, digest, state machine, lease fencing, adapter capability và operator
   path.
2. **ADR-M7-2 — Immutable Candidate and Atomic Master Promotion:** media staging,
   content/version refs, DB CAS, outbox, orphan GC và fault contract.
3. **ADR-M7-3 — Durable Task Events and SSE Replay:** event schema, authorization,
   cursor retention/resync, at-least-once delivery.
4. **ADR-M7-4 — Consistent PostgreSQL/Media Backup Sets:** recovery point,
   manifest/fence, RPO/RTO, clean-target proof và retention.
5. **ADR-M7-5 — Telemetry Identity and Secret-Safe Attribute Policy:** span model,
   async links, allowlist/redaction, evidence retention.
6. **ADR-M7-6 — Upstream Compatibility and Provider Qualification Gates:** pins,
   change classification, migration/Golden/browser gates, capability lifecycle.

Các kiểm chứng dưới đây không thay đổi lựa chọn kiến trúc trong tài liệu này,
nhưng phải được Task 0 và các checkpoint M7 thực hiện trên accepted base trước
khi nhận claim tương ứng:

- source audit có trace inbound/outbound cho mọi submit/poll/cancel/result ingest,
  task terminal transition, promotion và SSE route; lập complete write-route map;
- exact PostgreSQL schema/concurrency audit để chọn task-head/attempt-head lock
  order và transaction isolation, kèm counterexamples;
- deployment/media backend inventory để chọn local rename hay object-version
  adapter, không thiết kế lowest-common-denominator mơ hồ;
- provider-by-provider official-doc matrix, sau đó sandbox/bounded live probes khi
  được duyệt;
- backup tool/version benchmark trong disposable near-production environment và
  clean-target drill design;
- upstream ArcReel old-pin -> candidate-pin range/inventory diff và migration
  rehearsal plan;
- browser/reverse-proxy SSE fault prototype để đo retention, buffering và resync
  UX trước khi khóa spec.

## Nguồn chính bên ngoài

- [AWS EC2 API idempotency](https://docs.aws.amazon.com/ec2/latest/devguide/ec2-api-idempotency.html)
- [AWS transactional outbox](https://docs.aws.amazon.com/en_en/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html)
- [PostgreSQL continuous archiving and PITR](https://www.postgresql.org/docs/current/continuous-archiving.html)
- [PostgreSQL pg_verifybackup](https://www.postgresql.org/docs/current/app-pgverifybackup.html)
- [Linux rename(2)](https://www.man7.org/linux/man-pages/man2/renameat.2.html)
- [Amazon S3 consistency model](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html)
- [Amazon S3 conditional writes](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes-enforce.html)
- [WHATWG server-sent events](https://html.spec.whatwg.org/dev/server-sent-events.html)
- [OpenTelemetry Logs specification](https://opentelemetry.io/docs/specs/otel/logs/)
- [OpenTelemetry sensitive-data guidance](https://opentelemetry.io/docs/security/handling-sensitive-data/)
- [Replicate prediction lifecycle](https://replicate.com/docs/topics/predictions/create-a-prediction)
- [Replicate webhook delivery semantics](https://replicate.com/docs/topics/webhooks/receive-webhook)
- [Git range-diff](https://git-scm.com/docs/git-range-diff)
