# Autonomous Production Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mặc định một lần Start tự chạy ý tưởng → truyện → kịch bản → phim → current Quality PASS → verified export; chế độ semi chỉ dừng ở các checkpoint đã chọn.

**Architecture:** Backend controller giữ durable run/step/intent và gọi các owner hiện có. Queue, Story/Canon/Plan, media, master authority và M10 tiếp tục là authority cho domain của mình. Run-scoped automation grants thay Human impersonation; scanner và command replay bảo đảm phục hồi.

**Tech Stack:** Python, FastAPI, Pydantic, SQLAlchemy/Alembic/PostgreSQL, existing GenerationWorker/M7/M10, FFmpeg, React/TypeScript/Zustand/i18n. Không thêm workflow engine.

**Spec:** [Approved design](../specs/2026-10-30-autonomous-production-workflow-design.md), approved 30/10/2026 after `5746be25f`; [source/reuse audit](../../research/2026-10-30-autonomous-production-reuse-and-authority.md).

## Global Constraints

- Mode mặc định `auto`; `semi` mặc định `SCRIPT_PACKAGE` + `FINAL_FILM`; optional checkpoint duy nhất `STORY_MANUSCRIPT`.
- Mặc định một phim; nhiều tập chỉ SUCCEEDED khi tất cả target có current PASS và export receipt. Không autostart project/run lịch sử.
- Launch: fiction narration/storyboard và fiction drama/storyboard, Vietnamese, 9:16, 576×1024, H.264/AAC, 30–60 giây; narration có voice/subtitles; drama phải qualify character voice/continuity/lip sync cần thiết.
- Routes media từ preset hiện có: `custom-3/flux2-klein-4b-gguf`, `custom-3/wan2.2-ti2v-5b-gguf`, `custom-2/vieneu-tts-v3-turbo`. Text/reviewer routes phải freeze exact config và qualify, không giả định model ID hiện có vẫn dùng được.
- Tối đa 2 repair/unit-stage, 3 final evaluations, còn chịu tổng cost/time/call/task caps. Không blind retry UNKNOWN, không auto-WAIVE, không tự chấp nhận blocking narrative exception hoặc hạ threshold.
- Auto profile được publish một lần bởi qualified publisher, runtime chỉ dùng; MODEL observation không thể đáp ứng HUMAN slot.
- Hai qualified reviewer identities khác writer và khác model identity nhau, blind contexts; mỗi profile 20 calibration (10 clean/10 defect) + 20 hold-out (10/10), chặn mọi critical negative, nhận đúng ít nhất 8/10 clean hold-out; mỗi creative dimension bắt buộc >=4/5 từ cả hai reviewer.
- Start issuer phải có signed current Showrunner/operation authority; không suy từ admin/API login. Controller không giữ Human password/JWT, không cấp quyền publication/Gate D.
- Render từ exact presentation selections, giữ source media; external input movement → `BLOCKED_INPUT_CHANGED`, không adopt ngầm.
- Một managed GPU device admission xuyên Ollama/ComfyUI/TTS; lease expiry không chứng minh job dừng. Không tự xóa model/media để lấy dung lượng.
- Native execution bởi main agent theo project policy; không fan-out. Critical architecture/authority/DB review do main giữ trách nhiệm.

## Review Focus

1. Hai browser Start cùng project hoặc retry HTTP sau mất response phải trở lại cùng command/run, không sinh hai lượt tính phí — tests Task 2/3/6.
2. Parent Showrunner grant/profile/master thay đổi khi model/process đang chạy phải chặn write/READY cuối, nhưng giữ evidence — tests Task 3/5/9/10.
3. Task succeeded có result phase blocked, lost SSE và crash sau enqueue phải phục hồi đúng owner receipt — tests Task 6/7.
4. TTS dài hơn clip, thiếu âm thanh/phụ đề hoặc model reviewer ném lỗi không được xuất phim “đạt” — tests Task 8/9.
5. User đổi project/tab, thêm episode hoặc sửa source khi run đang chạy không được hiện/duyệt nhầm run hoặc auto-adopt dữ liệu — tests Task 6/11/12.

## Baseline, file structure và execution boundary

Verified source base `0cef69a772f1d2946e452b918a8839b0f37fd2d9`; docs commit `5746be25f` là descendant có **zero application-code diff** đối với base trong `lib/server/r2/frontend/alembic/scripts/agent_runtime_profile` và dependency files. Root `dbaf93a62` có unrelated dirty work, không dùng để implement. Tạo branch/worktree `impl/autonomous-production` / `.worktrees/r2-autonomous-production` từ commit chứa plan này khi bước thực thi được xác nhận; không checkout/clean worktree Claude hay release staging.

Hiện Alembic head `8a5d0f6b1e44` (`m10_export_custody`). Migration đầu đề xuất `b7a310300001_autonomous_production.py`; recheck head trước tạo file, nếu drift phải nối đúng lineage thay vì tạo head song song.

Phân lớp mới:

- `r2/contracts/automation.py`: public immutable run/policy/intent/decision/auth evidence contracts.
- `r2/automation/{policy,identity,transitions}.py`: pure logic; không import server/lib persistence.
- `lib/db/models/production_run.py`, `lib/db/repositories/{production_runs,automation_grants}.py`: run/step/policy/grant/decision/device persistence, owner receipt refs.
- `server/production_run/`: service, preflight, scheduler/controller, owner adapters, renderer, evaluators và resource orchestration. File chia theo domain owner, không tạo một mega executor.
- `server/routers/production_runs.py`: authenticated start/read/control/checkpoint API.
- `frontend/src/features/production-run/{api,ui}/`: typed client và panel; gắn vào existing WorkflowPanel, không biến UI thành scheduler.

Các interface mới dùng keyword-only args; các type tên dưới đây đều được định nghĩa ở Task 1. `Sessions` là `async_sessionmaker[AsyncSession]`; không dùng dataclass từ UI/API body làm proof authority.

Không activate scheduler/provider dispatch trong production trước Task 12. Test feature capability ở trạng thái disabled/incomplete trả lý do rõ; default mode vẫn auto trên run mới khi release đã qualified. Không ghi hồ sơ partial packet là full workflow acceptance.

---

### Task 1: Contracts, deterministic identities và pure transition policy

**Files:** create `r2/contracts/automation.py`, `r2/automation/__init__.py`, `r2/automation/identity.py`, `r2/automation/policy.py`, `r2/automation/transitions.py`; tests `tests/unit/r2/automation/test_{contracts,identity,transitions}.py`; create `docs/adr/0111-autonomous-production-run-authority.md` (check number not occupied).

**Interfaces:** produce `AutomationMode`, `RunStatus`, `RunStage`, `Checkpoint`, `RunPolicy`, `RunSnapshot`, `StepIdentity`, `DispatchIntent`, `OwnerReceipt`, `StageOutcome`, `RunCommand`, `ReviewCommand`, `GrantRequest`, `AutomationGrant`, `AuthorizationSubject`, `AutomationAuthorizationV1`, `AutomationDecision`, `PreflightReport`, `ModelAssessment`, `RenderInput`, `RenderReceipt`, `DeviceJob`, `DeviceLease`, `BudgetReservation`, `UsageReceipt`. StageOutcome is explicit WAIT/BLOCK/REWORK/PASS with immutable refs; no generic truthy success. DeviceLease is resource ownership/fencing evidence, not permission to approve content. DeviceJob carries actual provider/execution/task identity and optional run link, so managed manual tasks share GPU admission without inventing a production run. RenderInput is an immutable timeline/media-digest contract independent of server read-model classes. UsageReceipt references verified owner usage records; model-supplied cost is not authoritative.

Produce `derive_step_identity(*, run_id: str, stage: RunStage, unit_key: str, generation: int, input_digest: str, policy_digest: str, repair_index: int) -> StepIdentity`, `checkpoint_for(*, policy: RunPolicy, stage: RunStage) -> Checkpoint | None`, `advance(*, run: RunSnapshot, outcome: StageOutcome) -> RunSnapshot`.

- [ ] Write failing tests: `test_default_auto_and_semi_checkpoints` uses `assert policy.mode == AutomationMode.AUTO` and `assert semi.checkpoints == {Checkpoint.SCRIPT_PACKAGE, Checkpoint.FINAL_FILM}`; limits 2/3; `test_identity_changes_with_input_or_generation` asserts equal inputs yield equal identity and changed generation/input/policy/unit yields different identity; `test_task_success_cannot_complete_blocked_story` uses `assert updated.status != RunStatus.SUCCEEDED`; all-target success enforced. Import new symbols inside test functions for the first red run if the package does not exist yet, so the tests actually collect.
- [ ] Run `uv run python -m pytest tests/unit/r2/automation -q`; expect contract/import/assertion failure before implementation, nonzero tests collected.
- [ ] Implement frozen extra-forbid contracts, ordered/canonical digest construction and pure transitions; strict counters/caps/nonblank exact scope IDs. ADR records prospective A/B/C/narrative/Quality automation amendment, Human historical compatibility and Gate D exclusion.
- [ ] Run the same unit suite, `uv run ruff check r2/contracts/automation.py r2/automation tests/unit/r2/automation`; expect pass. Add missing/failed-validator-as-block and no automatic WAIVE tests.
- [ ] Commit only task files: `feat: define autonomous production contracts and transitions`.

### Task 2: Durable run, intent, grant, policy and resource storage

**Files:** create `lib/db/models/production_run.py`, `lib/db/repositories/production_runs.py`, `lib/db/repositories/automation_grants.py`, `alembic/versions/b7a310300001_autonomous_production.py`; modify `lib/db/models/__init__.py`; tests `tests/integration/lib/db/repositories/test_production_runs.py`, `test_automation_grants.py`, `tests/integration/lib/db/test_autonomous_production_migration.py`.

**Interfaces:** consume Task 1 contracts. `ProductionRunRepository(session)` exposes async `create(*, command: RunCommand, policy: RunPolicy) -> RunSnapshot`, `claim_due(*, owner_id: str, lease_seconds: int) -> RunSnapshot | None`, `stage_intent(*, run: RunSnapshot, intent: DispatchIntent) -> DispatchIntent`, `attach_receipt(*, intent: DispatchIntent, receipt: OwnerReceipt, fencing_epoch: int) -> None`, `transition(*, expected: RunSnapshot, updated: RunSnapshot, fencing_epoch: int) -> RunSnapshot`, `get(*, user_id: str, project_name: str, run_id: str) -> RunSnapshot`. Grant repository stages immutable versions/decisions and locked revocation/currentness reads. Services own transactions; repository never commits unrelated caller work.

Budget methods: `reserve_budget(*, run: RunSnapshot, intent: DispatchIntent) -> BudgetReservation`, `settle_budget(*, reservation: BudgetReservation, usage: UsageReceipt) -> None`. Reserve locked conservative cost/call/task/time ceilings before dispatch; child attempts debit their allocated stage reservation rather than double-counting the parent. UNKNOWN retains its reservation until authoritative reconciliation, never frees it on TTL expiry. New schema includes immutable usage-ref dedupe and reservation accounting.

- [ ] Write PG integration tests: `test_start_command_replay_returns_same_run` asserts `first.run_id == replay.run_id`; different user/project cannot read/link; unique `(run, stage, unit, generation, repair_index, input/policy digest)` intent; CAS/fencing rejects stale worker; policy/grant/decision immutable and FK scoped; concurrent reservations cannot exceed frozen cap, settlement replay does not double-count, UNKNOWN cannot release budget; old Human rows retain exact bytes; migration upgrade/downgrade leaves unrelated rows intact.
- [ ] Run new files against isolated PostgreSQL fixture/database; verify failing missing schema/API. Existing `concurrent_session_factory` is dialect-aware: supply a PostgreSQL test URL, use separate sessions and assert dialect; `file_session_factory` is SQLite-only and cannot prove PG interleavings. No skipped PG assertions counted as pass.
- [ ] Implement tables with constraints, command replay digest conflicts, DB time, CAS/row locks and short run claims. Allow one nonterminal run per user/project to prevent shared-project concurrent writers; terminal outputs remain accessible. Store dispatch intent and receipt link durably; terminal SSE is not an outbox. Device lease has epoch, holder/job refs and quiescence state, not only an expiry float.
- [ ] Run migration and repository tests, existing task/grant repository consumers and affected-domain DB gates. Race test two sessions, not sequential mocks; inspect unique/check enforcement with invalid inserts.
- [ ] Commit only task files: `feat: persist production runs and fenced dispatch intents`.

### Task 3: Run-scoped delegation custodian and current authorization

**Files:** create `server/services/automation_grants.py`, `r2/automation/authorization.py`; modify `server/services/governance_grant_fence.py` only for shared lock-order helper if needed; tests `tests/unit/r2/automation/test_authorization.py`, `tests/integration/server/services/test_automation_grants.py`.

**Interfaces:** `AutomationGrantCustodian(sessions: Sessions, grant_reader_factory, clock)` exposes async `issue(*, interactive_token: str, request: GrantRequest) -> AutomationGrant`, `revoke(*, interactive_token: str, run_id: str, expected_version: int) -> AutomationGrant`; `RunAutomationAuthority.require_locked(session: AsyncSession, *, subject: AuthorizationSubject) -> AutomationAuthorizationV1`.

- [ ] Write `test_unqualified_actor_cannot_issue_delegation` using `with pytest.raises(PermissionError): await custodian.issue(interactive_token=api_key, request=grant_request)` for admin/API-key/embedded actors; real current signed Showrunner + exact Start request can delegate only possessed operations; wildcard/cross-run/cross-project/Gate D rejected; expired/revoked parent or child, budget escalation, changed command/subject/policy rejected; replay evidence grants no new side effect.
- [ ] Run new unit/integration files; confirm failures before implementation.
- [ ] Implement child delegation anchored to existing signed/checkpointed parent grant and issuer's interactive authorization. New custodian uses activated Governance reader and DB-bound delegation record; do not put private governance signing keys in host worker or invent a signed Human event for automation. Verify parent/child head versions inside final owner transaction, with existing owner lock order documented per adapter.
- [ ] Run revoke-during-command interleavings and grant checkpoint movement tests. Check request cannot supply trusted automation principal/proof, `HUMAN_OPERATOR` or `HUMAN_SHOWRUNNER` literal; grant remains separate versioned actor variant.
- [ ] Commit: `feat: authorize production automation with scoped delegation`.

### Task 4: Preflight and qualified launch profile registry

**Files:** create `server/production_run/preflight.py`, `r2/automation/profiles.py`, `r2/automation/launch_profiles/fiction_narration_vi_v1.json`, `fiction_drama_vi_v1.json`; tests `tests/unit/r2/automation/test_profiles.py`, `tests/integration/server/production_run/test_preflight.py`; research gate `docs/research/2026-10-30-drama-speech-route-qualification.md`.

**Interfaces:** `ProductionPreflight.check(*, user_id: str, project_name: str, policy: RunPolicy) -> PreflightReport`; `resolve_launch_profile(profile_id: str) -> RunPolicy` returns immutable qualified preset metadata, never authority. Report includes qualification state and frozen route/policy/input digests, no secrets.

- [ ] Write `test_missing_qualified_reviewer_refuses_before_dispatch` asserting `report.dispatch_allowed is False` and `provider_submit_count == 0`; also unsupported content/generation/language, missing voice, insufficient disk/GPU envelope, absent or unbounded paid-cost cap, silent cloud fallback, stale model config and unqualified profile; each refuses before any model/media dispatch. `dispatch_allowed` is the boolean field of Task 1 PreflightReport.
- [ ] Run new profile/preflight suites; expect missing adapter/registry failures.
- [ ] Resolve existing ConfigResolver/capability snapshots and host qualification receipts. Profile publication remains existing qualified Human setup, not controller privilege. Validate scope/target count/duration caps and output contract before reserve/dispatch.
- [ ] Close drama research prerequisite using pinned source/fixture checks of existing VieNeu + speech-composition route: character voices, voice ownership, measured timing, on-screen lip sync. If insufficient, document exact capability gap, qualify a concrete replacement route/cost scope in design addendum before implementing drama media. Do not mark drama launch supported on silent Wan + overlay alone; narration tasks may proceed independently.
- [ ] Run preflight tests including no-side-effect assertions, record qualification/unsupported states, commit `feat: preflight autonomous production profiles and capabilities` (profile qualification only where actually established).

### Task 5: Versioned automatic authority at narrative and master owners

**Files:** create `server/production_run/narrative_authority.py`, `master_authority.py`; modify `r2/contracts/narrative_lifecycle.py`, `r2/contracts/narrative_plan.py`, `r2/contracts/adaptation.py`, `r2/contracts/gates.py`, `server/story_authoring/{authority,commit,service}.py`, `server/routers/gates.py` shared Gate C core; add owner-specific migration if DB literal constraints need extension (next revision after Task 2, never rewrite applied migrations). Tests `tests/integration/server/production_run/test_narrative_authority.py`, `test_master_authority.py` plus existing narrative/commit/gate tests.

**Interfaces:** `AutomaticNarrativeAuthority` implements versioned automation decision methods returning Task 3 authorization, not legacy Human proof; `AutomaticMasterApproval.promote(*, subject: AuthorizationSubject, receipt: OwnerReceipt) -> OwnerReceipt` calls shared real master promotion/receipt core. Legacy Human API signatures/serialization remain accepted.

- [ ] Write `test_legacy_human_authorization_roundtrip` asserting `restored.model_dump(mode="json") == original_wire`; new explicitly tagged automation variant round-trips separately; forged/incomplete automation proofs rejected; exact manifest/script/source head checks persist; automatic approval cannot accept blocking story exceptions; parent revocation/master movement at transaction boundary blocks write and `new_master_count == 0`.
- [ ] Run new and mirrored owner tests; expect missing new authorization variant/adapter failures.
- [ ] Extend only required owner authorization ports/unions/DB serialization and locked checks. Share typed internal approval core rather than call Human HTTP route with synthetic user or write manifest directly. Preserve Canon/Plan approval contracts and factual-vs-drama admission distinctions.
- [ ] Verify real PG admission/approval interleavings, original Human scenarios, and immutable historical bytes. No new public path accepts arbitrary `selected_by`/approval record as authority.
- [ ] Commit `feat: support explicit automated narrative and master decisions` after affected owner gates pass.

### Task 6: Resumable controller, scheduler, Start/control/review API

**Files:** create `server/production_run/{service,controller,scheduler,ports}.py`, `server/routers/production_runs.py`; modify `server/app.py` lifecycle/router registration; tests `tests/unit/server/production_run/test_controller.py`, `tests/integration/server/production_run/test_controller_recovery.py`, `tests/integration/server/routers/test_production_runs.py`.

**Interfaces:** `OwnerAdapter` exposes async `dispatch(intent: DispatchIntent) -> OwnerReceipt` and `inspect(receipt: OwnerReceipt) -> StageOutcome`; adapters mapped by RunStage in server composition root. `ProductionController.tick(*, run_id: str, owner_id: str) -> RunSnapshot`; `ProductionScheduler.scan_once() -> int`; `ProductionRunService.start(*, interactive_token: str, command: RunCommand) -> RunSnapshot`, `control(*, interactive_token: str, command: RunCommand) -> RunSnapshot`, `review(*, interactive_token: str, command: ReviewCommand) -> RunSnapshot`.

API: `POST/GET /api/v1/projects/{project_name}/production-runs`, `GET /.../{run_id}`, `POST /.../{run_id}/{pause,resume,cancel,review,mode}`. All mutations carry command ID + expected run version/input/policy digest; server derives actor/user/project and grants. Read payload contains run/stages/outputs/reasons, no tokens or provider secrets.

- [ ] Write `test_crash_after_enqueue_replays_owner_command` asserting `resumed_receipt.task_id == first_receipt.task_id` and `provider_submit_count == 1`; also double Start, same command changed digest, two scanner claims, crash before dispatch/before attach, dropped/duplicate SSE, browser close, restart, story task succeeded with blocked phase, cancellation and stale fencing.
- [ ] Run unit/controller/route suites with real owner-persistence boundary where relevant; prove red before implementation.
- [ ] Implement intent-first, pre-dispatch budget reservation and owner replay; settle only from verified usage receipts, including reviewer/repair/internal story calls. Periodic DB reconciliation independently of SSE; use WorkflowPlan for production steps but continue beyond `export` into render/master/Quality/package. Recheck input/head/policy/grant before next command. No dispatch for stale generation, UNKNOWN, incomplete capability or semi WAITING_REVIEW.
- [ ] Add tests external edit → `BLOCKED_INPUT_CHANGED`; explicit digest-bound resume/new scope; mode changes create auditable policy version and renewed grant when privilege increases. Lifecycle stop does not cancel durable logical run; in-flight owner work follows M7 recovery. Run routes/controller tests and existing app-lifecycle tests.
- [ ] Commit `feat: orchestrate durable automatic and semi-automatic production runs` with activation disabled until release gate.

### Task 7: Story, episode planning, script and asset-analysis adapters

**Files:** create `server/production_run/{story,text,assets}_adapter.py`; modify `server/tool_runtime.py`, `server/services/generation_tasks.py` registry only for missing structured asset/prompt task, `server/story_authoring/runtime.py` and `executor.py` for the run-budget link in StoryAttemptSink; tests `tests/integration/server/production_run/test_{story,text,assets}_adapter.py`, `tests/unit/server/production_run/test_text_outcomes.py`.

**Interfaces:** `StoryAdapter`, `TextAdapter`, `AssetsAdapter` implement Task 6 OwnerAdapter. Intent payload is a validated stage-specific model in each adapter; media/script resource IDs and source/script revision digests are mandatory. All return owner receipts, never a bare boolean.

- [ ] Write `test_succeeded_task_with_blocked_story_never_handoffs` asserting `handoff_call_count == 0`; story RUNNING/READY_FOR_APPROVAL/COMMITTED/BLOCKED/UNKNOWN handling; policy commit/handoff once; multi-window episode planning and all target scripts; formal asset inventory revision/manifest; zero/missing structured results cannot PASS.
- [ ] Run new adapters plus existing story executor/driver/commit tests to demonstrate missing integration red.
- [ ] Connect existing brief/driver/commit/handoff and text tools using Task 5 automatic authority. Link StoryAttemptSink reservations/settlements to the parent run's allocated stage cap; preserve per-story limits and count COUNT/GENERATE/reviewer/repair attempts correctly without duplicate debit. Iterate planner windows/episodes with stable unit identities. Convert skill-only asset/prompt generation into bounded schema-validated executor/formal-write adapters, using existing prompt/provider owners and saved request/model identities; no unrestricted SDK Agent filesystem writes.
- [ ] Verify semantic phase rather than task status, exact input/source/script revision, checkpoint placement and safe retry. Preserve manually operated story APIs; run full relevant story/text/asset suites and test audit.
- [ ] Commit `feat: automate story to script and asset preparation`.

### Task 8: Media dispatch, shared resource admission and native final renderer

**Files:** create `server/production_run/{media_adapter,resource_admission,render_adapter}.py`, `lib/presentation_renderer.py`, `lib/generation_resources.py`; modify `server/services/generation_tasks.py`, `server/story_authoring/generation.py`, `lib/custom_provider/backends.py`, `lib/custom_provider/factory.py`, `lib/custom_provider/comfyui_image_backend.py`, `lib/custom_provider/comfyui_backend.py`, `lib/text_backends/ollama.py` at managed GPU submission/admission seams; reuse `server/services/presentation_read_model.py`. Tests `tests/integration/server/production_run/test_{media_adapter,resource_admission,render_adapter}.py`, `tests/integration/lib/test_presentation_renderer.py`.

**Interfaces:** `MediaAdapter`, `RenderAdapter` implement OwnerAdapter; `DeviceAdmissionPort` in `lib/generation_resources.py` exposes async `acquire(*, device_id: str, job: DeviceJob) -> DeviceLease` and `release_after_quiescence(*, lease: DeviceLease, receipt: OwnerReceipt) -> None`; `ManagedDeviceAdmission` is the server implementation, injected at composition/factory seams. `render_presentations(*, episode: RenderInput, output_dir: Path, contract: RunPolicy) -> RenderReceipt` consumes a snapshot converted by RenderAdapter from existing MaterializedEpisode. No `lib` module imports server ORM/services/read models; no `r2` domain module imports server/lib persistence.

- [ ] Write `test_busy_gpu_lease_is_not_freed_by_expiry` asserting `not second_acquire.done()` after first lease expiry while provider job is still active; late holder cannot commit. Add real-media fixtures with TTS longer than video, missing/subtitle drift, exact selections, stale script/audio, mixed character/narrator ownership and cancelled render. `test_renderer_preserves_exact_input_media` asserts `source_hashes_after == source_hashes_before`; also full decode, actual timestamps, audible narration/content correlation.
- [ ] Run integration fixtures using installed FFmpeg and simulated provider transport only for transport-specific boundaries; fail missing renderer/admission first. Model qualification is separate from deterministic renderer tests.
- [ ] Reuse batch/media tools and all prerequisites; TTS may follow script independently of storyboard. Freeze source/version/audio choices through PresentationReadModel once; render bounded argv with cleanup/staging/manifest/hash protocol. Do not copy Golden-only composer into generic authority or invoke scenes-only CLI on narration segments.
- [ ] Hook admission at common managed provider submission boundaries, including story/reviewer local inference and managed manual tasks, not just run controller, and reconcile external busy state without unproven process termination. One authoritative acquire per physical job across nested backend wrappers; test no double acquisition/deadlock. Persistent model residency counts as occupied capacity even after a request returns: release only after verified managed unload/quiescence or a measured safe coexistence envelope; no kill/unload of unrelated workload. Register final candidate and use Task 5 master adapter only after actual artifact verification. Run existing media/speech/presentation tests, import-layer lint and new real-render tests.
- [ ] Commit `feat: generate and render production films with shared resource admission` after drama route prerequisite is satisfied for drama-specific changes.

### Task 9: Qualified model evidence, Quality seal/disposition and bounded rework

**Files:** create `server/production_run/{quality_adapter,evaluators,rework}.py`, `r2/automation/assessment.py`, `tests/fixtures/automation/quality/{narration_vi,drama_vi}.json`; modify `server/services/quality_probes.py`, `quality_runs.py`, `quality_dispositions.py`, `r2/quality/{runs,dispositions}.py` only at existing verified authorization/observation ports; tests `tests/unit/r2/automation/test_assessment.py`, `tests/integration/server/production_run/test_{quality_adapter,rework,assessor_qualification}.py`.

**Interfaces:** `QualifiedEvaluator.assess(*, subject: AuthorizationSubject, model_route_digest: str, evidence: OwnerReceipt) -> ModelAssessment`; `QualityAdapter` implements OwnerAdapter; `build_rework(*, run: RunSnapshot, assessments: tuple[ModelAssessment, ...]) -> tuple[DispatchIntent, ...]`. Producer registry owns model/conflict/independence groups; model output cannot nominate itself qualified.

- [ ] Write `test_reviewer_exception_never_passes_quality` asserting `run.status != RunStatus.SUCCEEDED` and `pass_disposition_count == 0`; missing evidence/disagreement/wrong language/stale digest/HUMAN-required slot all block; 2 repair caps, 3 final evaluations and global budget stop; critical finding never auto-WAIVE. Old Human observations and signed authority still validate unchanged.
- [ ] Run new tests with deterministic assessor fixture responses before implementing integration; then run 20+20 cohort qualification protocol with configured real reviewers only within authorized run caps. Keep calibration labels/hold-out key out of reviewer context.
- [ ] Add versioned automatic authorization to probe execution/run closure/disposition, preserving existing owner locks, M7 attempt custody, profile/master/currentness and receipt replay. Record MODEL evidence through qualified producer admission, never HumanObservationService. Run pinned profiles only, no auto-publication privilege.
- [ ] Persist findings and scoped repair revision; invalidate correct downstream dependencies, not successful unrelated episodes. Ensure new master exists before its Quality subject, then PASS only after required evidence; failed model/probe is not pass. Run M10 profile/probe/run/disposition suites, real PG interleavings and applicable host probe integration; report actual unexecuted qualification as blocker.
- [ ] Commit `feat: assess and repair automatic production with qualified Quality evidence`.

### Task 10: Controlled packaging/export and all-target finality

**Files:** create `server/production_run/packaging_adapter.py`; modify `server/services/quality_package_selection.py`, `server/services/package_export.py`, `r2/contracts/packaging.py` only for explicitly versioned automatic actor/selection proof; tests `tests/integration/server/production_run/test_packaging_adapter.py`, `test_run_finality.py`.

**Interfaces:** `PackagingAdapter` implements OwnerAdapter; its receipt references existing package/selection/export records and immutable verified archive. `verify_run_outputs(*, run: RunSnapshot, receipts: tuple[OwnerReceipt, ...]) -> StageOutcome` returns PASS only when every target has current master/profile/run/PASS/selection/export and final/download digest/size verified.

- [ ] Write `test_failed_target_prevents_run_success` asserting `run.status != RunStatus.SUCCEEDED` despite another episode's valid export; revoked grant, moved master/profile, substituted archive/final bytes, wrong-user download, failed-quality candidate and retained old output. No success-download selection for partial/unknown/stale results.
- [ ] Run new integration tests and existing export/selection tests; observe missing automatic authorization failures first.
- [ ] Extend exact custodian admission paths with Task 3 authorization, preserve download descriptor pinning/stream cleanup/integrity. Reuse immutable package builder, include MP4/subtitle/Quality/lineage refs and run-level aggregate manifest. No anonymous public URL, no retention deletion or Gate D.
- [ ] Run real package generation/verified download and concurrent authority movement tests; archive and record receipts, ensure cross-project/private access checks persist.
- [ ] Commit `feat: export verified automatic production packages`.

### Task 11: Auto/semi UI, minimal checkpoints and Agent profile integration

**Files:** create `frontend/src/features/production-run/api/{types,productionRunClient}.ts`, `ui/{ProductionRunPanel,RunReviewCard}.tsx`; modify `frontend/src/components/workflow/WorkflowPanel.tsx`, `frontend/src/i18n/{en,vi,zh}/workflow.ts` (re-enumerate supported locales), `agent_runtime_profile/.claude/skills/video-workflow/SKILL.narration.md` and `SKILL.drama.md`; tests adjacent `*.test.ts(x)`.

**Interfaces:** client `startProductionRun(projectName: string, command: RunCommand, options?: {signal?: AbortSignal}): Promise<RunSnapshot>` plus typed get/control/review/mode calls; `ProductionRunPanel({projectName, episode})` consumes server snapshots, never derives authority/next_action from file existence. TS types mirror Task 1 wire schema; API user/actor fields remain server-derived.

- [ ] Write `defaultsToAutoAndStartsOnce` asserting `expect(startProductionRun).toHaveBeenCalledTimes(1)` after double click; exact two semi checkpoint cards, loading, stale review receipt, resume after reload, project switch with late response, cancellation, current blocked reason and private film download. `ignoresPreviousProjectResponse` asserts displayed run's project is the currently selected project; no routine Continue prompts in auto.
- [ ] Run exact Vitest files red before implementation, then implement with existing components/styles, abort/selection guards and SSE + polling recovery. Add translations for every discovered locale; preserve story-only/manual controls and active legacy run behavior.
- [ ] Embedded Agent profiles detect active production run, report/control via new API/tools and never parallel-dispatch competing stage work; per-action confirmation protocol remains for manually managed workflow only. Updating profile/agent guidance must follow writing-for-agents skill at execution time.
- [ ] Run `cd frontend && pnpm check`, backend i18n consistency test and `uv run python scripts/audit_tests.py --check`; browser smoke new auto/semi flows on isolated fixture projects without external publish. Add response-head-currentness test across project/tab changes.
- [ ] Commit `feat: expose automatic and semi-automatic production controls`.

### Task 12: End-to-end qualification, independent review and rollout

**Files:** create `tests/e2e/automation/test_production_run.py`, `tests/integration/server/production_run/test_crash_recovery.py`, `scripts/r2/qualify_autonomous_production.py`, `docs/r2/evidence/R2_AUTONOMOUS_PRODUCTION_ACCEPTANCE.json`, `docs/r2/evidence/R2_AUTONOMOUS_PRODUCTION_HANDOFF.md`; deployment docs update only after actual acceptance.

**Interfaces:** `qualify_autonomous_production.py` uses new API and existing owner receipts; outputs redacted exact HEAD/config/tool/model/input/manifest/task/Quality/export identities, actual timings/usage/interventions and acceptance limits. It never hardcodes expected PASS into assessor inputs.

- [ ] Write `test_new_idea_reaches_current_quality_pass_and_export`: `assert run.status == RunStatus.SUCCEEDED`, `assert disposition.decision == "PASS"`, `assert downloaded_sha256 == export_receipt.sha256`; one new idea per launch profile, no operator-authored script fixture. Semi stops at exactly configured checkpoints; user can request changes; multi-target finality; browser closed + backend/worker restart recovers without duplicate provider submits. Map existing receipt field names through the qualification script rather than invent a new export truth.
- [ ] Run deterministic crash/error/negative integration cases first: intent/dispatch/attach boundaries, lost events, unknown outcome, moved heads/revocation, GPU contention, disk/budget exhaustion and exact-scope rework. Run fresh model/media qualification only under saved authorized caps; preserve cloud UNKNOWN run outside this test scope.
- [ ] Run affected-domain final gates from CONTRIBUTING: `uv run ruff check .`, formatter on owned paths and clean-format verification, `uv run basedpyright --warnings`, `uv run lint-imports`, `uv run deptry lib server alembic scripts tests r2`, backend full pytest `-n 4 --dist loadfile`, test audit; `pnpm check` frontend and website if affected. DB/profile/i18n changes require full backend checks. Record actual PG host executions; skipped, collect-only and denied setups are not passes.
- [ ] Main performs critical full-branch review of auth/custody/lock ordering/currentness/finality and source/test claims. If an independently qualified reviewer is available under routing policy, request bounded review; main retains acceptance authority. Close findings, rerun impacted gates only, then record accepted profiles and all limits in JSON.
- [ ] Prepare concrete migration/config/rollback/backup evidence for deployment. Enable automatic capability and default-auto new runs only after complete acceptance; preserve stored legacy modes/data and service custody. Deploy within authorized scope, verify health and an actual run/control/download path, then commit deployment evidence. Do not call a design, focused test pass or model-only sample full launch completion.

## Self-review / requirements coverage

Spec §§1–3 mode/cardinality/launch/workflow → Tasks 1/4/6/7/8/11/12; §4 owner routing → Tasks 2/5–10; §5 recovery → Tasks 2/6/12; §6 authority → Tasks 3/5/9/10; §7 Quality → Tasks 4/9/12; §8 render/resources → Tasks 4/8; §9 API/UI/concurrent edits/export → Tasks 6/10/11; §10 acceptance/rollout → Task 12. All five Review Focus cases map to explicit tests above.

No proposed automatic actor is passed to a legacy Human-only constructor. No task claims to provide a qualified drama speech or model-assessor route before its research/fixture gate. New interface types originate Task 1; owner adapters use the same dispatch/inspect/receipt contract. Existing module path spellings and Alembic lineage must be revalidated at task entry; graph generation is old, so exact deployed-source verification remains required.

Planning verification: source/tree inspection, graph search/trace/snippet and coverage checks; migration head derived statically; no product source, DB, model/provider call, production config or service restart changed. Tests listed here are **planned**, not executed results. Review this plan before execution; native main-agent method follows project policy.
