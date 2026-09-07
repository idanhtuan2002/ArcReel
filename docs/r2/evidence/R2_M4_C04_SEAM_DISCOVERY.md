# R2-M4 C04 seam discovery

Date: 2026-09-07

## Pinned execution state

- Original R2 baseline: `1985b815d70dd600519839973b1da20472012d8f`.
- Remediation verified head: `e72cce2272e1e496a7c8a52df2d3513fd20e815d`.
- Remediation clean handoff and C04 starting head: `521aad2f83a19bdb03219923b6bd2268a338f617`.
- The verified head is an ancestor of the handoff. The only paths after the verified head are the three approved remediation evidence documents.
- Current Alembic head at the pinned baseline is exactly `9f3c7a52d1b4`. Planned revision `c04b7d93e5a1` is unused.

The approved M4 design and C04 amendment were materialized with SHA-256 digests `7fda57922ea24e4253968818c90995271f86068a22007d4e6d102aeb3f8d3f09` and `dc59109c08dc6899a0f9b932acfb14722c787e19fe391a821d688e7b5484b813`, respectively.

## Discovery method and coverage

Codebase Memory Tier 2 was queried first against project `home-anhtuan-content-production-os`, generation `2026-09-07T08:54:05Z`. Searches covered `UsageRepository`, cost quotation/admission, task checkpoint persistence, `submitted_base_url`, `execute_generation_task`, `execute_reference_video_task`, and the video generator submit boundary. Inbound/outbound traces were inspected for the material seams. Some broad trace edges had heuristic confidence and were not used as source truth.

Coverage checks reported no recorded issue and matching metadata for the material Python/config paths except `CLAUDE.md`, which was not graph-tracked and was read directly. This signal is best-effort. The C04 worktree is not a separately indexed graph project, so exact source was read at the pinned C04 head. Of the seam files, only `pyproject.toml` differs from the original R2 graph baseline; the remediation diff is the approved inclusion of `r2` in import-linter, deptry and basedpyright.

## Existing actual-cost seam

`UsageRepository.get_calls(call_id=..., page_size=...)` already performs an exact `ApiCall.id` filter, applies the repository scope hook, and returns the persisted row through `_row_to_dict`, including `id`, `status`, `cost_amount`, `currency`, `project_name`, `segment_id` and provider identity (`lib/db/repositories/usage_repo.py:643`). C04 therefore selects the plan branch **reuse the existing by-id lookup unchanged**. No modification to `usage_repo.py` is authorized or required for lookup alone.

The persisted `ApiCall.cost_amount` is a legacy SQLAlchemy `Float`. C04 money and counters remain `Decimal`; the service boundary must convert the persisted value from its decimal string representation and must never persist a binary float in the new authorization tables. Existing Usage/Spend remains the actual-cost authority.

The existing `quote_video_request` path resolves provider pricing and returns a display/admission quote (`server/services/cost_estimation.py:148`). It catches lookup errors and can return `None`; it is not an atomic reservation and must not be reused as hard-budget authorization. Existing video batch admission produces readiness/tickets but owns no durable budget hold.

## Paid submission and checkpoint seam

The concrete reference-video path is:

```text
execute_reference_video_task
  -> MediaGenerator.generate_video_async(before_submit=checkpoint_hook)
  -> MediaGenerator._run_with_reference_compression
  -> _call_once
  -> await before_submit()
  -> await build_and_call(compressed)
  -> video_backend.generate(...)
```

`execute_reference_video_task` builds and persists `ReferenceSubmissionCheckpoint`, including its `api_call_id` and provider identity, at `server/services/reference_video_tasks.py:699`. `MediaGenerator._run_with_reference_compression` calls the hook before `build_and_call` at `lib/media_generator.py:441`; `_call_video` constructs the backend request at `lib/media_generator.py:1031`. Tests at `tests/integration/server/services/test_execute_reference_video_task.py:2276` and `:2348` prove checkpoint-before-provider ordering and staged request identity.

This is the narrow first-paid-side-effect seam to be consumed later by M4: C04 exposes `submit_with_budget_guard`, while C04 itself does not rewire legacy Host tasks. H1 remains open because a claim committed immediately before a network submit does not establish whether an interrupted remote submission actually occurred.

`TaskRepository.persist_execution_checkpoint`, `persist_api_call_id`, and `get(task_id)` are existing durable links between a task/attempt and the usage call. Reconciliation must verify the referenced `ApiCall` belongs to the reservation's execution/attempt correlation. `ApiCall` itself has no `task_id` column, so checking only that `api_call:<id>` exists is insufficient. Task 5 must use the existing task/checkpoint correlation or fail closed; it must not invent a second cost record.

## Model and repository registration

`lib/db/models/__init__.py` imports every ORM model and exports it in `__all__`; importing a model class registers it with `Base.metadata`. C04 must add `BudgetScopeModel` and `BudgetReservationModel` there. `lib/db/repositories/__init__.py` exports its public repository classes, so C04 will add `BudgetReservationRepository` there as the plan permits.

The scope row is the transaction serialization anchor. PostgreSQL must use a row lock. SQLite requires a real concurrent-writer test and one transaction for expiry, availability calculation, reservation insert and counter update; no process mutex is permitted.

## Architecture tooling

- `pyproject.toml` already has `root_packages = ["lib", "r2"]`, includes `r2` in basedpyright and deptry, and has two existing import-linter contracts.
- The C04 extension point is an additional forbidden import contract preventing `r2.production.budget_port` from reaching Host DB models/repositories.
- `uv run lint-imports` passed with 2 contracts kept and 0 broken.
- `scripts/audit_tests.py --help` succeeded.
- The two existing R2 architecture selections passed: 10 tests, 0 failures (one SQLAlchemy reflection warning).

## Bounded implementation decisions

1. Add exactly one migration after `9f3c7a52d1b4` and the two approved tables.
2. Reuse `UsageRepository.get_calls(call_id=...)`; do not add `get_call_by_id` unless later RED evidence proves the existing result cannot enforce an approved invariant.
3. Use the existing task/checkpoint-to-`api_call_id` link for attempt correlation during reconciliation.
4. Add a Host service and R2 delegation port; neither owns provider routing, Usage writes, queue state or artifact truth.
5. Keep `server/services/generation_tasks.py` and all legacy provider paths read-only in C04.
6. Keep H1 explicitly open.

No production code changed at this checkpoint.
