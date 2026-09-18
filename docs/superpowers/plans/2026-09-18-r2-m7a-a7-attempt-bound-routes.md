# R2-M7A A7 Attempt-Bound Routes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bind every paid asynchronous Host video submit to the durable M7-A
attempt service and deduplicate its terminal result and usage effects.

**Architecture:** Keep `ProviderRequest` as the sole adapter/runtime request.
Backends build their provider-specific request immediately before network I/O and
delegate the actual submit through an injected `AttemptSubmitter`; direct calls
without a task remain compatibility-only. The submitter plans or reloads attempt
1 for the durable task, invokes A6 exactly once, binds the resulting execution ID
to usage, and returns the accepted job identity so existing polling/download
flows continue unchanged.

**Tech Stack:** Python 3.12+, Pydantic 2.12+, SQLAlchemy async, Alembic,
PostgreSQL 18, pytest, Ruff, basedpyright and Codebase Memory.

**Spec:** `docs/superpowers/specs/2026-09-18-r2-m7-provider-request-origin-amendment-design.md`

## Global Constraints

- Continue from clean M7 HEAD `2a366267`; preserve commits A0-A6.
- Use the existing queue, video backends, attempt repository, usage repository
  and `ProviderRequest`; create no parallel authority.
- A worker request with `task_id` must fail before network I/O when its route is
  missing from the inventory.
- A request without `task_id` remains a compatibility path and creates no M7
  acceptance evidence.
- Existing M4 `ProviderRequest` canonical bytes remain unchanged.
- Route entries added here are `UNQUALIFIED`; production-candidate mode remains
  fail-closed.
- Tests follow RED-GREEN-REFACTOR and comments describe only current behavior.

---

### Task 1: Add explicit ProviderRequest origin authority

**Files:**
- Modify: `r2/contracts/execution.py:103-120`
- Modify: `tests/unit/r2/contracts/test_execution.py`
- Modify: `tests/unit/r2/production_intelligence/test_prompt_compiler.py`

**Interfaces:**
- Produces: `ProviderRequest.method_decision_ref: NonEmptyStr | None`
- Produces: `ProviderRequest.host_task_ref: NonEmptyStr | None`
- Invariant: exactly one origin field is non-null; the null field is excluded
  from serialization.

- [ ] **Step 1: Add failing contract tests**

```python
def test_provider_request_requires_exactly_one_origin_ref() -> None:
    with pytest.raises(ValidationError):
        _request(method_decision_ref=None, host_task_ref=None)
    with pytest.raises(ValidationError):
        _request(method_decision_ref="MD:1", host_task_ref="task-1")


def test_m4_provider_request_dump_omits_host_origin() -> None:
    request = _request(method_decision_ref="MD:1")
    assert "host_task_ref" not in request.model_dump(mode="json")


def test_host_provider_request_dump_omits_method_origin() -> None:
    request = _request(method_decision_ref=None, host_task_ref="task-1")
    assert "method_decision_ref" not in request.model_dump(mode="json")
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `uv run pytest tests/unit/r2/contracts/test_execution.py tests/unit/r2/production_intelligence/test_prompt_compiler.py -q`

Expected: failures because `host_task_ref` is forbidden and a null
`method_decision_ref` is rejected.

- [ ] **Step 3: Implement the additive XOR contract**

```python
class ProviderRequest(R2ContractModel):
    id: NonEmptyStr
    method_decision_ref: NonEmptyStr | None = Field(default=None, exclude_if=lambda value: value is None)
    host_task_ref: NonEmptyStr | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def require_one_origin(self) -> ProviderRequest:
        if (self.method_decision_ref is None) == (self.host_task_ref is None):
            raise ValueError("provider request requires exactly one origin reference")
        return self
```

- [ ] **Step 4: Run contract and M4 compiler tests and verify GREEN**

Run: `uv run pytest tests/unit/r2/contracts/test_execution.py tests/unit/r2/production_intelligence/test_prompt_compiler.py -q`

- [ ] **Step 5: Commit**

```bash
git add r2/contracts/execution.py tests/unit/r2/contracts/test_execution.py tests/unit/r2/production_intelligence/test_prompt_compiler.py
git commit -m "feat(r2): admit host task provider requests"
```

### Task 2: Add reloadable attempt identity and the Host submitter

**Files:**
- Modify: `r2/host_hardening/ports.py`
- Modify: `lib/db/repositories/host_hardening.py`
- Create: `r2/host_hardening/host_submit.py`
- Modify: `r2/host_hardening/__init__.py`
- Create: `tests/unit/r2/host_hardening/test_host_submit.py`
- Modify: `tests/integration/lib/db/repositories/test_execution_attempt_repository.py`

**Interfaces:**
- Produces: `ExecutionAttemptRepository.get_for_task_attempt(*, user_id: str,
  project_name: str, task_id: str, attempt_no: int) -> AttemptSnapshot | None`
- Produces: `ProviderSubmitReceipt[T](observation: ProviderObservation, value: T)`
- Produces: `AttemptSubmitter.submit(*, task_id: str, api_call_id: int | None,
  route: ProviderRouteSnapshot, request: ProviderRequest,
  submit: Callable[[], Awaitable[ProviderSubmitReceipt[T]]]) -> AttemptSubmitResult[T]`
- Attempt 1 is the only automatic attempt for a queue task. A later paid retry
  requires a new explicit attempt number and is outside this automatic path.
- Consumes an optional `UsageExecutionBinder`; Task 3 supplies the production
  adapter while this task tests the interface with an in-memory binder.

- [ ] **Step 1: Add failing repository and submitter tests**

```python
async def test_submitter_reloads_attempt_one_and_never_calls_submit_twice() -> None:
    first = await submitter.submit(task_id="task-1", api_call_id=7, route=route, request=request, submit=submit)
    second = await submitter.submit(task_id="task-1", api_call_id=7, route=route, request=request, submit=submit)
    assert first.execution_id == second.execution_id
    assert submit.await_count == 1


async def test_submitter_rejects_request_route_digest_drift_before_network() -> None:
    await submitter.submit(task_id="task-1", api_call_id=7, route=route, request=request, submit=submit)
    with pytest.raises(AttemptIdentityMismatch):
        await submitter.submit(task_id="task-1", api_call_id=7, route=changed_route, request=request, submit=submit)
    submit.assert_awaited_once()
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `uv run pytest tests/unit/r2/host_hardening/test_host_submit.py tests/integration/lib/db/repositories/test_execution_attempt_repository.py -q`

Expected: import or missing-method failures.

- [ ] **Step 3: Implement scoped reload and the deep submit module**

```python
@dataclass(frozen=True)
class ProviderSubmitReceipt(Generic[T]):
    observation: ProviderObservation
    value: T


@dataclass(frozen=True)
class AttemptSubmitResult(Generic[T]):
    execution_id: str
    snapshot: AttemptSnapshot
    value: T | None


class AttemptSubmitter:
    async def submit(self, *, task_id, api_call_id, route, request, submit):
        existing = await self._repository.get_for_task_attempt(
            user_id=self._user_id, project_name=self._project_name,
            task_id=task_id, attempt_no=1,
        )
        planned = self._planned_attempt(existing=existing, task_id=task_id, route=route, request=request)
        captured: ProviderSubmitReceipt[Any] | None = None

        async def submit_observation(_attempt, _request):
            nonlocal captured
            captured = await submit()
            return captured.observation

        snapshot = await self._service.plan_and_submit(
            user_id=self._user_id, project_name=self._project_name,
            attempt=planned, request=request,
            adapter=BackendExecutionAdapter(self._capability(route), BackendExecutionFunctions(submit=submit_observation, poll=self._unsupported_poll)),
        )
        if api_call_id is not None and self._usage_binder is not None:
            await self._usage_binder.bind_execution(call_id=api_call_id, execution_id=snapshot.execution_id)
        return AttemptSubmitResult(execution_id=snapshot.execution_id, snapshot=snapshot, value=None if captured is None else captured.value)
```

Use repository-standard opaque UUIDs for a new attempt, canonical JSON SHA-256
for `request_digest`, and the stored snapshot fields for exact replay.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `uv run pytest tests/unit/r2/host_hardening/test_host_submit.py tests/integration/lib/db/repositories/test_execution_attempt_repository.py -q`

- [ ] **Step 5: Commit**

```bash
git add r2/host_hardening lib/db/repositories/host_hardening.py tests/unit/r2/host_hardening/test_host_submit.py tests/integration/lib/db/repositories/test_execution_attempt_repository.py
git commit -m "feat(host): materialize durable submit identity"
```

### Task 3: Bind usage to execution identity

**Files:**
- Modify: `lib/db/models/api_call.py`
- Modify: `alembic/versions/7a7c4a0e0001_add_execution_attempts.py`
- Modify: `lib/db/repositories/usage_repo.py`
- Modify: `lib/ledger.py`
- Modify: `tests/integration/lib/db/repositories/test_usage_repo.py`
- Modify: `tests/unit/lib/test_ledger.py`

**Interfaces:**
- Produces: nullable `api_calls.execution_id` with a unique partial index and
  scoped foreign key to `execution_attempts`.
- Produces: `UsageRepository.bind_execution(call_id: int, execution_id: str) -> None`
- Exact replay of the same binding is a no-op; a different execution ID for the
  same call raises `UsageExecutionMismatch`.

- [ ] **Step 1: Add failing model/repository tests**

```python
async def test_bind_execution_is_exactly_idempotent(repo, pending_call, attempt) -> None:
    await repo.bind_execution(call_id=pending_call.id, execution_id=attempt.execution_id)
    await repo.bind_execution(call_id=pending_call.id, execution_id=attempt.execution_id)
    assert (await repo.get_by_id(pending_call.id)).execution_id == attempt.execution_id


async def test_one_execution_cannot_finalize_two_usage_rows(repo, attempt, two_pending_calls) -> None:
    await repo.bind_execution(call_id=two_pending_calls[0].id, execution_id=attempt.execution_id)
    with pytest.raises(UsageExecutionMismatch):
        await repo.bind_execution(call_id=two_pending_calls[1].id, execution_id=attempt.execution_id)
```

- [ ] **Step 2: Run usage and migration selections and verify RED**

Run: `uv run pytest tests/integration/lib/db/repositories/test_usage_repo.py tests/unit/lib/test_ledger.py tests/integration/lib/db/migrations/test_alembic_execution_attempts.py -q`

- [ ] **Step 3: Add the nullable column, unique index, scoped FK and bind CAS**

```python
async def bind_execution(self, *, call_id: int, execution_id: str) -> None:
    result = await self.session.execute(
        update(ApiCall)
        .where(ApiCall.id == call_id, or_(ApiCall.execution_id.is_(None), ApiCall.execution_id == execution_id))
        .values(execution_id=execution_id)
        .returning(ApiCall.execution_id)
    )
    if result.scalar_one_or_none() is None:
        raise UsageExecutionMismatch(call_id)
```

- [ ] **Step 4: Run the focused selection and verify GREEN**

Run: `uv run pytest tests/integration/lib/db/repositories/test_usage_repo.py tests/unit/lib/test_ledger.py tests/integration/lib/db/migrations/test_alembic_execution_attempts.py -q`

- [ ] **Step 5: Commit**

```bash
git add lib/db/models/api_call.py alembic/versions/7a7c4a0e0001_add_execution_attempts.py lib/db/repositories/usage_repo.py lib/ledger.py tests/integration/lib/db/repositories/test_usage_repo.py tests/unit/lib/test_ledger.py tests/integration/lib/db/migrations/test_alembic_execution_attempts.py
git commit -m "feat(host): bind usage to execution attempts"
```

### Task 4: Freeze and verify the paid asynchronous route inventory

**Files:**
- Modify: `r2/provider_capabilities/registry.json`
- Create: `r2/host_hardening/route_inventory.py`
- Create: `tests/unit/r2/host_hardening/test_route_inventory.py`
- Modify: `scripts/r2/verify_m7_scope.py`
- Modify: `tests/unit/scripts/r2/test_verify_m7_scope.py`

**Interfaces:**
- Produces: `require_submit_route(provider_id: str, endpoint_id: str,
  adapter_version: str) -> ProviderCapabilityProfile`
- Produces machine-readable `M7_SUBMIT_ROUTE_UNBOUND` for any missing or stale
  inventory tuple.
- Inventory covers Gemini, DashScope, Ark, Agnes, Vidu, Kling, OpenAI, Grok and
  declarative custom-video submit families discovered at `2a366267`.

- [ ] **Step 1: Add failing inventory tests**

```python
def test_every_paid_async_submit_family_is_inventoried() -> None:
    assert discovered_submit_families() == registered_submit_families()


def test_new_unlisted_submit_route_fails_closed() -> None:
    with pytest.raises(SubmitRouteUnboundError, match="M7_SUBMIT_ROUTE_UNBOUND"):
        require_submit_route("new-provider", "videos.create", "adapter-v1")
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `uv run pytest tests/unit/r2/host_hardening/test_route_inventory.py tests/unit/scripts/r2/test_verify_m7_scope.py -q`

- [ ] **Step 3: Add unqualified entries and strict tuple lookup**

Each registry entry uses `qualification_status="UNQUALIFIED"`,
`supports_webhook=false`, the conservative `idempotency_mode="NONE"` unless an
existing exact adapter test proves a stronger mode, and a self-consistent entry
digest. The verifier compares the frozen source-symbol inventory to registry
tuples and reports `M7_SUBMIT_ROUTE_UNBOUND:<qualified-symbol>`.

- [ ] **Step 4: Run registry schema, loader and verifier tests and verify GREEN**

Run: `uv run pytest tests/unit/r2/host_hardening/test_provider_capabilities.py tests/unit/r2/host_hardening/test_route_inventory.py tests/unit/scripts/r2/test_verify_m7_scope.py -q`

- [ ] **Step 5: Commit**

```bash
git add r2/provider_capabilities/registry.json r2/host_hardening/route_inventory.py tests/unit/r2/host_hardening/test_route_inventory.py scripts/r2/verify_m7_scope.py tests/unit/scripts/r2/test_verify_m7_scope.py
git commit -m "feat(r2): freeze paid submit route inventory"
```

### Task 5: Inject attempt-bound submission into video requests

**Files:**
- Modify: `lib/video_backends/base.py`
- Modify: `lib/media_generator.py`
- Modify: `server/services/execution_attempts.py`
- Modify: `server/services/generation_tasks.py`
- Modify: `tests/integration/lib/test_media_generator_module.py`
- Create: `tests/integration/server/services/test_attempt_bound_video_execution.py`

**Interfaces:**
- Produces: `VideoGenerationRequest.attempt_submitter: AttemptSubmitter | None`
- Produces: `VideoGenerationRequest.api_call_id: int | None`
- Produces: `VideoGenerationRequest.execution_id: str | None`
- Worker tasks require the submitter; direct non-task generation keeps it null.

- [ ] **Step 1: Add failing worker-path tests**

```python
async def test_worker_video_request_carries_submitter_and_api_call_id() -> None:
    await generator.generate_video_async(..., task_id="task-1", attempt_submitter=submitter)
    request = backend.requests[0]
    assert request.attempt_submitter is submitter
    assert request.api_call_id == ledger_call_id


async def test_worker_route_missing_submitter_fails_before_backend() -> None:
    with pytest.raises(RuntimeError, match="M7_SUBMIT_ROUTE_UNBOUND"):
        await generator.generate_video_async(..., task_id="task-1")
    assert backend.generate_calls == 0
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `uv run pytest tests/integration/lib/test_media_generator_module.py tests/integration/server/services/test_attempt_bound_video_execution.py -q`

- [ ] **Step 3: Thread one submitter from task execution to backend request**

Build the submitter in `execute_video_task()` after provider resolution and
inject it into `MediaGenerator.generate_video_async()`. Store the returned
execution ID on the request and copy it into version metadata and the task
result. No import from `lib/` to `server/` is introduced.

- [ ] **Step 4: Run focused worker/media tests and verify GREEN**

Run: `uv run pytest tests/integration/lib/test_media_generator_module.py tests/integration/server/services/test_attempt_bound_video_execution.py tests/unit/server/services/test_generation_tasks_dispatch.py -q`

- [ ] **Step 5: Commit**

```bash
git add lib/video_backends/base.py lib/media_generator.py server/services/execution_attempts.py server/services/generation_tasks.py tests/integration/lib/test_media_generator_module.py tests/integration/server/services/test_attempt_bound_video_execution.py
git commit -m "refactor(host): inject attempt-bound video submission"
```

### Task 6: Route every backend submit through A6

**Files:**
- Modify: `lib/video_backends/{gemini,dashscope,ark,agnes,vidu,kling,openai,grok}.py`
- Modify: `lib/kling_backend_base.py`
- Modify: `lib/custom_provider/declarative_backend.py`
- Modify: `lib/custom_provider/backends.py`
- Modify: `lib/video_backends/execution_adapter.py`
- Modify: affected tests under `tests/unit/lib/video_backends/` and
  `tests/unit/lib/custom_provider/`

**Interfaces:**
- Worker submit closures return `ProviderSubmitReceipt` with an ACCEPTED
  observation and job ID, or a terminal observation plus opaque SDK result.
- Non-worker requests continue using the existing direct submit path.
- Legacy `_persist_provider_job_id()` runs only as a projection after the
  attempt observation is durable.

- [ ] **Step 1: Add one RED test per submit family**

```python
async def test_worker_submit_uses_attempt_submitter_before_network() -> None:
    result = await backend.generate(_request(task_id="task-1", attempt_submitter=submitter))
    submitter.submit.assert_awaited_once()
    network.assert_awaited_once()
    assert submitter.call_args.kwargs["request"].host_task_ref == "task-1"
```

Add equivalent assertions for HTTP (`submit_post`), SDK, Kling and declarative
families. Add an ambiguous-failure assertion that the attempt becomes
`SUBMIT_OUTCOME_UNKNOWN` and the backend does not retry.

- [ ] **Step 2: Run affected backend tests and verify RED**

Run: `uv run pytest tests/unit/lib/video_backends tests/unit/lib/custom_provider -q`

- [ ] **Step 3: Add one backend helper and replace every worker network submit**

```python
async def submit_attempt_bound(request, *, route, provider_request, submit):
    if request.task_id is None:
        return await submit()
    if request.attempt_submitter is None:
        raise RuntimeError("M7_SUBMIT_ROUTE_UNBOUND")
    result = await request.attempt_submitter.submit(
        task_id=request.task_id,
        api_call_id=request.api_call_id,
        route=route,
        request=provider_request,
        submit=submit,
    )
    request.execution_id = result.execution_id
    if result.value is None:
        raise AttemptReplayRequiresResume(result.snapshot.execution_id)
    return result.value
```

Each backend keeps its existing payload builder and poll/download behavior; only
the network submit call moves inside the supplied closure. ProviderRequest
payload uses normalized semantic input plus content digests, with provider,
model, endpoint and adapter version outside the payload.

- [ ] **Step 4: Run backend, checkpoint and resume suites and verify GREEN**

Run: `uv run pytest tests/unit/lib/video_backends tests/unit/lib/custom_provider tests/unit/lib/test_media_generator_resume.py tests/unit/lib/reference_video -q`

- [ ] **Step 5: Commit**

```bash
git add lib/video_backends lib/kling_backend_base.py lib/custom_provider tests/unit/lib/video_backends tests/unit/lib/custom_provider
git commit -m "refactor(host): enforce attempt-bound provider submits"
```

### Task 7: Prove route, restart and terminal-effect idempotency

**Files:**
- Modify: `tests/integration/server/services/test_attempt_bound_video_execution.py`
- Create: `tests/integration/server/services/test_execution_terminal_idempotency.py`
- Modify: `tests/integration/lib/test_generation_worker_module.py`
- Modify: `tests/unit/lib/test_media_generator_resume.py`
- Modify: `scripts/r2/verify_m7_scope.py`

**Interfaces:**
- Exact restart replay uses the stored attempt route even after defaults change.
- Duplicate terminal ingestion yields one task result, one version commit and one
  usage finalization for the execution ID.

- [ ] **Step 1: Add the end-to-end RED cases**

```python
async def test_restart_after_default_change_polls_original_route() -> None:
    first = await run_until_provider_acceptance(default_provider="provider-a")
    set_default_provider("provider-b")
    result = await resume_task(first.task_id)
    assert result.execution_id == first.execution_id
    assert provider_a.poll_count == 1
    assert provider_b.submit_count == provider_b.poll_count == 0


async def test_duplicate_terminal_observation_finalizes_effects_once() -> None:
    await ingest_success(execution_id)
    await ingest_success(execution_id)
    assert await task_result_count(execution_id) == 1
    assert await version_commit_count(execution_id) == 1
    assert await finalized_usage_count(execution_id) == 1
```

- [ ] **Step 2: Run the integration selection and verify RED**

Run: `uv run pytest tests/integration/server/services/test_attempt_bound_video_execution.py tests/integration/server/services/test_execution_terminal_idempotency.py tests/integration/lib/test_generation_worker_module.py tests/unit/lib/test_media_generator_resume.py -q`

- [ ] **Step 3: Close replay and terminal guards at existing commit seams**

Use the stored `AttemptSnapshot.route` for resume construction, include
`execution_id` in task result/version metadata, return the existing exact
terminal effect on duplicate replay, and reject a mismatched replay. Do not add
a second result, version or usage store.

- [ ] **Step 4: Run affected domain gates**

Run: `uv run pytest tests/integration/server/services/test_attempt_bound_video_execution.py tests/integration/server/services/test_execution_terminal_idempotency.py tests/unit/lib/video_backends tests/unit/lib/custom_provider tests/integration/lib/test_generation_worker_module.py tests/unit/lib/test_generation_queue.py tests/unit/lib/test_media_generator_resume.py tests/unit/lib/test_ledger.py -q`

- [ ] **Step 5: Run static and test-structure gates**

Run: `uv run ruff check r2/host_hardening r2/contracts lib/video_backends lib/custom_provider lib/media_generator.py lib/db/repositories server/services tests/unit/r2/host_hardening tests/integration/server/services`

Run: `uv run ruff format --check r2/host_hardening r2/contracts lib/video_backends lib/custom_provider lib/media_generator.py lib/db/repositories server/services tests/unit/r2/host_hardening tests/integration/server/services`

Run: `uv run basedpyright r2/host_hardening r2/contracts lib/video_backends lib/media_generator.py server/services/execution_attempts.py`

Run: `uv run python scripts/audit_tests.py --check`

Run: `git diff --check`

- [ ] **Step 6: Commit A7**

```bash
git add scripts/r2/verify_m7_scope.py tests/integration/server/services tests/integration/lib/test_generation_worker_module.py tests/unit/lib/test_media_generator_resume.py
git commit -m "refactor(host): enforce attempt-bound generation effects"
```

After this commit, run the complete A7 affected-suite selection again on the
clean HEAD and record its exact counts for Task A8 evidence. Do not start M7-B.
