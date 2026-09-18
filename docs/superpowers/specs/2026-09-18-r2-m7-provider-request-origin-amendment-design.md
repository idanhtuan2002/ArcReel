# R2-M7 Provider Request Origin Amendment

**Status:** Accepted for implementation planning

**Date:** 2026-09-18

**Amends:** `2026-09-12-r2-m7-host-production-hardening-design.md`

**Related contracts:** `2026-09-06-r2-m1-contract-kernel-design.md`,
`2026-09-06-r2-m4-production-intelligence-design.md`

## 1. Problem

M7-A requires every paid asynchronous provider submission to pass through the
durable attempt service. That service deliberately accepts the existing
`ProviderRequest` adapter/runtime contract.

The contract currently requires `method_decision_ref`. This is correct for the
M4 production-intelligence flow, where a real `MethodDecision`, admission and
`ExecutionDecision` exist before request compilation. Existing Host queue tasks
do not enter that flow. They carry durable task identity and resolve an exact
provider route when a worker materializes the execution.

A7 therefore cannot bind existing Host routes by inventing a MethodDecision
reference. Making the field simply nullable would also lose the request's
authority provenance. Introducing a second Host request contract would split
the adapter/runtime seam that M1 already owns.

The provider capability registry is also empty. Until each paid asynchronous
route has an entry, A7 cannot bind a route to the immutable capability reference
required by `ProviderRouteSnapshot`.

## 2. Decision

`ProviderRequest` remains the sole provider-specific adapter/runtime request
interface. It gains one additive optional field:

```python
class ProviderRequest(R2ContractModel):
    id: NonEmptyStr
    method_decision_ref: NonEmptyStr | None = None
    host_task_ref: NonEmptyStr | None = None
    # existing provider, model, endpoint, payload, execution_options and
    # adapter_version fields remain unchanged
```

Exactly one origin reference is required:

- `method_decision_ref` identifies an M4 production-intelligence decision;
- `host_task_ref` identifies the durable ArcReel task that authorized a legacy
  Host generation command.

Both present or both absent is invalid. Existing M4 constructors remain valid,
and canonical serialization omits the unused origin field so existing M4 request
bytes remain unchanged. `DefaultPromptCompiler` continues to populate only
`method_decision_ref`. The Host execution binder populates only `host_task_ref`.

The origin reference records why the request exists. Exact paid-effect identity
continues to live in `PlannedExecutionAttempt`: scoped task ID, attempt number,
request digest, immutable route snapshot and client token. A Host task reference
does not pretend that the task passed M4 admission.

## 3. Host execution binding

A7 adds one Host execution binder at the existing worker/backend seam. For every
queue task whose selected backend performs an asynchronous paid submit, it:

1. reads the durable task and current request payload;
2. resolves provider, model, endpoint, base URL and adapter version once;
3. resolves the matching capability-profile reference from the frozen route
   inventory;
4. builds a canonical `ProviderRequest` with `host_task_ref=task.id`;
5. hashes the canonical request and creates the next immutable
   `PlannedExecutionAttempt` before network I/O;
6. calls `ExecutionAttemptService.plan_and_submit()` with the existing backend
   adapter;
7. projects the accepted provider job identity into legacy task/checkpoint
   columns without making those columns authoritative.

The worker resumes from the attempt route snapshot. A changed default provider
after acceptance cannot redirect polling, download or reconciliation. An exact
replay of a progressed attempt never submits again.

Backends return `ProviderObservation` through the adapter. They do not persist
attempt state directly. Existing backend `generate()` entry points may remain as
compatibility surfaces for non-worker tests and explicitly non-paid use, but the
worker path must reach network submit only through the binder and attempt
service.

## 4. Route inventory and qualification

`r2/provider_capabilities/registry.json` is the A7 route inventory. Each
graph-discovered asynchronous route capable of creating paid remote work has one
versioned entry matching its provider, API route and adapter version.

Entries added by A7 are `UNQUALIFIED`. They must pass the current structural,
digest and freshness checks so local development and deterministic tests can use
the route. `PRODUCTION_CANDIDATE` continues to require `QUALIFIED`; this
amendment does not claim provider qualification.

The inventory is guarded mechanically:

- a paid async submit surface without an entry fails with
  `M7_SUBMIT_ROUTE_UNBOUND`;
- an entry that no longer maps to a submit surface fails the inventory check;
- an adapter-version or route change requires a new entry and request digest;
- synchronous text, image or audio calls are outside A7 unless discovery shows
  that they create asynchronous paid remote jobs.

## 5. Terminal effects

`execution_id` is the idempotency key for downstream attempt effects. Terminal
result ingestion, generation-candidate creation and authoritative usage
finalization each enforce at most one committed record per execution ID.
Duplicate observations may be stored according to the existing observation
identity rules, but they cannot duplicate a terminal result, candidate or usage
record.

Legacy task state, provider job columns and usage views are projections from the
attempt-bound operation. They remain readable for compatibility and cannot
select a different provider route or create a second paid effect.

## 6. Failure behavior

- Missing origin authority: reject request construction.
- Both origin authorities present: reject request construction.
- Missing or mismatched route inventory entry: fail before network I/O with
  `M7_SUBMIT_ROUTE_UNBOUND`.
- Definite pre-send failure: transition to `FAILED_BEFORE_ACCEPTANCE`.
- Ambiguous submit: transition to `SUBMIT_OUTCOME_UNKNOWN`; reconcile according
  to the frozen capability profile and never blind-resubmit.
- Duplicate terminal or usage ingestion: return the existing exact result or
  reject a mismatched replay; never append a second authoritative effect.

## 7. Verification

A7 must prove:

1. old M4 `ProviderRequest` JSON round-trips byte-for-byte unchanged;
2. Host requests require exactly one `host_task_ref` origin;
3. every graph-discovered paid asynchronous route is inventoried;
4. a new unlisted submit route fails the architecture check;
5. worker network submission cannot bypass `ExecutionAttemptService`;
6. changing provider defaults after acceptance preserves the attempt route;
7. concurrent/restarted execution produces one attempt and at most one remote
   job under the qualified idempotency behavior;
8. duplicate terminal observations produce one result, candidate and usage
   finalization;
9. provider, worker, queue, checkpoint, usage, static-analysis and test-audit
   selections remain green.

## 8. Scope

This amendment changes the origin provenance of the existing request interface
and completes the A7 route inventory. It does not create a new queue, request
surface, production-intelligence decision, provider qualification claim,
webhook path, artifact authority or deployment permission.
