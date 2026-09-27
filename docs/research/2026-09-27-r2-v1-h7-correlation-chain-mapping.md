# R2 V1 H7 — mapping the correlation chain onto live Host records

Date: 2026-09-27. Base: `feat/r2-m7e-v1-lineage` at `5c85ddb7`. Source was read
directly in this worktree. No license analysis is in scope.

Spec §9 chain: `request_id -> method_decision_id -> task_id -> execution_id ->
provider_job_ref -> candidate_id -> master_version -> usage_entry_id`.

## Facts (source-backed)

1. **No request ID exists.** Nothing in `server/` mints or propagates a
   per-request ID. Tasks are enqueued through `GenerationQueue.enqueue_task`
   (`lib/generation_queue.py:399`). Its callers are `server/routers/generate.py`,
   `grids.py`, `reference_videos.py`, `server/tool_runtime.py` and
   `server/agent_runtime/session_manager.py` (13 call sites).
   `command_id` (`command_receipts.task_id`) exists only when a client sends
   `idempotency_key` (`server/routers/generate.py:400`). It is optional and not a
   universal request identity.
2. **No MethodDecision reaches the Host.** `MethodDecision` / `ExecutionDecision`
   live in the pure `r2.production_intelligence` layer. No module in `server/`,
   `lib/` or `r2/` outside that package constructs an `ExecutionDecision` for a
   Host task. The V1 production path has no method decision.
3. **The M7 candidate/promotion store has no production caller.**
   `AtomicPromotionService` (`r2/host_hardening/promotion.py`) and
   `lib/candidate_store.py` are used only by tests. Production media and
   selection live in ArcReel version history (`lib/version_manager.py`). There
   the "candidate" is a `(project, resource_type, resource_id, version)` record
   and the "master" is the selected version.
4. **`execution_id` is already the durable spine for async video.**
   `execution_attempts(task_id, execution_id, provider_job_id)` is created at
   claim time (`lib/generation_queue.py:775`). Video version metadata stores
   `execution_id` (`lib/media_generator.py:1096`,
   `lib/version_manager.py:739`). `api_calls.execution_id` is bound through
   `UsageRepository.bind_execution` (`lib/db/repositories/usage_repo.py:170`).
5. **Image/audio/text tasks have no execution attempt.** Neither
   `api_calls` nor version records carry `task_id`, so these lanes have no durable
   `task -> version -> usage` join today.

## Inferences

- A span-only request ID would join to a task only within one process
  lifetime, and only while the exporter is enabled (ADR-0090 leaves it off by
  default).
- To satisfy "every generation can be joined by durable IDs", the entry join
  (`request -> task`) and the non-video joins (`task -> version`,
  `task -> usage`) need a durable carrier: a log line, a JSON field, or a column.

## Options for the decision

| Option | request -> task | task -> version / usage (non-video) | Migration |
|---|---|---|---|
| A. Durable log join | Middleware or agent entry mints `request_id` (contextvar). One structured log line at enqueue carries `request_id`, `task_id`. | Add `task_id` to version metadata JSON. One structured log line at ledger start carries `api_call_id`, `task_id`. | None |
| B. Persisted columns | Nullable `tasks.request_id` | Version metadata `task_id` plus nullable `api_calls.task_id` | One additive Alembic revision |

`method_decision_id` is **not applicable** on every V1 path (fact 2). It stays an
allowed, absent attribute until an R2 production path wires in. It is not
fabricated. `candidate_id` / `master_version` map to the version record and the
selected version (fact 3).

## Unknowns

- The log retention period of the target deployment, which option A depends on.
