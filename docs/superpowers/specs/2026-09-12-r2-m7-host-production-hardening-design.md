# R2-M7 Host Production Hardening Design

**Status:** Accepted for implementation planning
**Date:** 2026-09-12
**ADR:** `docs/adr/0078-durable-execution-evidence-and-recoverable-production-boundaries.md`
**Research:** `docs/research/2026-09-12-r2-m7-host-production-hardening-research.md`

## 1. Goal and boundary

M7 re-earns the frozen Host maturity gates after R2 extensions. It closes H1-H8
without replacing ArcReel's queue, task state machine, provider backends,
Artifact Manifest, version history, usage accounting, recovery ownership or
export path.

The implementation is split into five independently reviewed checkpoints:

1. `M7-A`: execution identity and idempotency (H1-H2);
2. `M7-B`: immutable candidates and atomic promotion (H3-H4);
3. `M7-C`: restart/cancel/event recovery (H5);
4. `M7-D`: backup/restore and observability (H6-H7);
5. `M7-E`: upstream compatibility, provider qualification, Golden/browser and
   operator evidence (H8 and `PRODUCTION_CANDIDATE`).

M7 starts only from the final accepted, clean M6 handoff whose Alembic head is
`6c7c4a0e0002`. A different accepted head or changed seam is a design-review stop,
not permission to invent a parallel implementation.

## 2. Existing seams and measured gaps

The implementation plan must reverify these surfaces at its accepted base:

- `TaskRepository.persist_provider_job_id()` currently persists remote job ID,
  endpoint and base URL only after submit in a separate transaction.
- `ProviderJobIdPersistenceMixin._persist_provider_job_id()` is called by all
  asynchronous video backends after remote acceptance and intentionally
  propagates persistence failure.
- `VideoSubmissionCheckpoint` and `classify_video_resume_state()` preserve much
  of the exact route and reject resume without a job ID, but cannot reconcile a
  remote job whose acceptance response was lost.
- the queue already provides active-task deduplication and a process-level worker
  lease; M7 extends rather than replaces both.
- `ProductionApprovalService` and `ArcReelVersionRestorePromoter` already protect
  selected-master semantics and roll back a manifest callback failure, but their
  filesystem/manifest view is not a PostgreSQL transaction spanning durable R2
  approval, usage and event evidence.
- the frontend already sends `Last-Event-ID`; `SseChannel.broadcast()` is
  process-memory only, so the server cannot replay missed project events.

These are positive source findings, not an exhaustive absence claim. The Tier-2
Codebase Memory coverage pass at generation `2026-09-12T10:40:56Z` reported no
recorded issue for the cited source files; generated `__pycache__` directories
were the only declared scope gaps and are irrelevant. The signal remains
best-effort and Task 0 must refresh it.

## 3. Canonical vocabulary

- **ExecutionAttempt:** immutable identity plus monotonic observations for one
  possible paid provider execution of a local generation task.
- **CommandReceipt:** durable idempotency result for one actor-scoped mutation
  command. Reuse with different semantic bytes is a mismatch, never a new task.
- **ProviderCapabilityProfile:** versioned, qualified facts about one exact
  provider/API route; configuration intent is not capability proof.
- **ProviderObservation:** authenticated/polled evidence about remote state. An
  observation cannot make an attempt state move backwards.
- **SubmitOutcomeUnknown:** the request may have reached the provider but no
  unique remote identity is locally known.
- **CandidateObject:** immutable verified media bytes addressed by candidate and
  content digest; it is not an approved master.
- **MasterHead:** the sole authoritative selected candidate/version for one
  production artifact, advanced by expected-version CAS.
- **ProjectEvent:** durable tenant-scoped domain event. SSE is one delivery
  projection of this record.
- **BackupSet:** exact database recovery point plus immutable media inventory and
  release/configuration identity, validated by a clean-target restore.

`task`, `api_call`, `provider_job`, `execution_checkpoint`, `resume` and
`ApprovedMaster` retain their existing glossary meanings.

## 4. Fixed contracts

All persisted timestamps are timezone-aware UTC. Public IDs are opaque UUIDv7 or
repository-standard opaque IDs; callers may compare but not parse ordering from
them. Hashes are lowercase `sha256:<64 hex>` strings over canonical UTF-8 JSON.
Enums use the exact serialized values below.

```python
class ExecutionAttemptState(StrEnum):
    PLANNED = "PLANNED"
    SUBMITTING = "SUBMITTING"
    SUBMIT_OUTCOME_UNKNOWN = "SUBMIT_OUTCOME_UNKNOWN"
    ACCEPTED = "ACCEPTED"
    RUNNING = "RUNNING"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCEL_OUTCOME_UNKNOWN = "CANCEL_OUTCOME_UNKNOWN"
    SUCCEEDED = "SUCCEEDED"
    FAILED_BEFORE_ACCEPTANCE = "FAILED_BEFORE_ACCEPTANCE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    NEEDS_OPERATOR = "NEEDS_OPERATOR"

class ProviderIdempotencyMode(StrEnum):
    NATIVE_TOKEN = "NATIVE_TOKEN"
    LOOKUP_BY_METADATA = "LOOKUP_BY_METADATA"
    NONE = "NONE"

class ProviderTokenScope(StrEnum):
    PROVIDER_ACCOUNT = "PROVIDER_ACCOUNT"
    PROVIDER_ACCOUNT_REGION = "PROVIDER_ACCOUNT_REGION"
    PROVIDER_ACCOUNT_ENDPOINT = "PROVIDER_ACCOUNT_ENDPOINT"

class ProviderNotFoundSemantics(StrEnum):
    NON_AUTHORITATIVE = "NON_AUTHORITATIVE"
    AUTHORITATIVE_AFTER_SETTLING_WINDOW = "AUTHORITATIVE_AFTER_SETTLING_WINDOW"

class ProviderObservationKind(StrEnum):
    ACCEPTED = "ACCEPTED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    NOT_FOUND = "NOT_FOUND"

class ProjectEventType(StrEnum):
    ATTEMPT_TRANSITIONED = "ATTEMPT_TRANSITIONED"
    CANDIDATE_VERIFIED = "CANDIDATE_VERIFIED"
    MASTER_PROMOTED = "MASTER_PROMOTED"
    USAGE_FINALIZED = "USAGE_FINALIZED"
    RESYNC_REQUIRED = "RESYNC_REQUIRED"

class BackupSetState(StrEnum):
    PREPARING = "PREPARING"
    COMPLETE = "COMPLETE"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"

class ProviderQualificationStatus(StrEnum):
    UNQUALIFIED = "UNQUALIFIED"
    OFFLINE_VERIFIED = "OFFLINE_VERIFIED"
    SANDBOX_VERIFIED = "SANDBOX_VERIFIED"
    QUALIFIED = "QUALIFIED"

class UpstreamDisposition(StrEnum):
    UNCHANGED = "UNCHANGED"
    ADAPTED = "ADAPTED"
    DEFERRED = "DEFERRED"
    REJECTED = "REJECTED"

class OperatorResolutionAction(StrEnum):
    BIND_REMOTE_JOB = "BIND_REMOTE_JOB"
    CONFIRM_NOT_SUBMITTED = "CONFIRM_NOT_SUBMITTED"
    CONFIRM_TERMINAL = "CONFIRM_TERMINAL"
```

```python
@dataclass(frozen=True)
class ProviderRouteSnapshot:
    provider_id: str
    provider_account_ref: str
    provider_model_id: str
    backend_model_id: str
    endpoint_id: str | None
    submitted_base_url: str
    adapter_version: str
    capability_profile_ref: str

@dataclass(frozen=True)
class PlannedExecutionAttempt:
    execution_id: str
    task_id: str
    attempt_no: int
    request_digest: str
    route: ProviderRouteSnapshot
    client_token: str | None
    trace_id_at_creation: str | None
    created_at: datetime

@dataclass(frozen=True)
class CommandReceipt:
    actor_scope: str
    command_id: str
    command_digest: str
    task_id: str
    result_digest: str
    created_at: datetime

@dataclass(frozen=True)
class AttemptSnapshot:
    execution_id: str
    task_id: str
    attempt_no: int
    request_digest: str
    route: ProviderRouteSnapshot
    client_token: str | None
    provider_job_id: str | None
    state: ExecutionAttemptState
    state_version: int
    lease_owner: str | None
    lease_token: int | None
    lease_expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
    submitted_at: datetime | None
    last_observed_at: datetime | None
    terminal_at: datetime | None

@dataclass(frozen=True)
class ProviderCapabilityProfile:
    ref: str
    provider_id: str
    api_version: str
    adapter_version: str
    idempotency_mode: ProviderIdempotencyMode
    token_scope: ProviderTokenScope | None
    token_scope_value: str | None
    token_ttl_seconds: int | None
    not_found_semantics: ProviderNotFoundSemantics
    lookup_settling_window_seconds: int | None
    supports_poll: bool
    supports_cancel: bool
    supports_webhook: Literal[False]
    supports_lookup: bool
    provider_sequence_is_monotonic: bool
    evidence_digest: str

@dataclass(frozen=True)
class ProviderObservation:
    observation_id: str
    kind: ProviderObservationKind
    observed_at: datetime
    provider_sequence: int | None
    provider_job_id: str | None
    reason_code: str | None
    evidence_digest: str

@dataclass(frozen=True)
class PersistedProviderObservation:
    observation: ProviderObservation
    received_seq: int
    received_at: datetime

@dataclass(frozen=True)
class AttemptLeaseFence:
    owner: str
    token: int

@dataclass(frozen=True)
class OperatorResolutionReceipt:
    resolution_id: str
    execution_id: str
    expected_attempt_version: int
    operator_id: str
    action: OperatorResolutionAction
    resolved_state: ExecutionAttemptState
    provider_job_id: str | None
    terminal_kind: ProviderObservationKind | None
    evidence_digest: str
    resolved_at: datetime

@dataclass(frozen=True)
class AttemptIntegrityIncident:
    incident_id: str
    execution_id: str
    first_observation_id: str
    conflicting_observation_id: str
    evidence_digest: str
    resolved_by_receipt_id: str | None

@dataclass(frozen=True)
class ReconcileResult:
    execution_id: str
    state: ExecutionAttemptState
    provider_job_id: str | None
    operator_reason: str | None
```

### 4.1 Attempt ports

```python
class ExecutionAttemptRepository(Protocol):
    async def plan(self, *, user_id: str, project_name: str,
                   attempt: PlannedExecutionAttempt) -> AttemptSnapshot: ...
    async def get_exact(self, *, user_id: str, project_name: str,
                        execution_id: str) -> AttemptSnapshot | None: ...
    async def transition_worker(self, *, user_id: str, project_name: str,
                                execution_id: str, expected_version: int,
                                expected_states: frozenset[ExecutionAttemptState],
                                new_state: ExecutionAttemptState,
                                fence: AttemptLeaseFence,
                                reason_code: str | None = None) -> AttemptSnapshot: ...
    async def apply_provider_observation(
        self, *, user_id: str, project_name: str, execution_id: str,
        expected_version: int, observation: ProviderObservation,
    ) -> AttemptSnapshot: ...
    async def resolve_operator_review(
        self, *, user_id: str, project_name: str, execution_id: str,
        expected_version: int, receipt: OperatorResolutionReceipt,
    ) -> AttemptSnapshot: ...
    async def acquire_lease(self, *, user_id: str, project_name: str,
                            execution_id: str, expected_version: int,
                            owner: str, expires_at: datetime) -> AttemptSnapshot: ...
    async def release_lease(self, *, user_id: str, project_name: str,
                            execution_id: str, expected_version: int,
                            fence: AttemptLeaseFence) -> AttemptSnapshot: ...

class CommandReceiptRepository(Protocol):
    async def get_exact(self, *, user_id: str, project_name: str,
                        actor_scope: str,
                        command_id: str) -> CommandReceipt | None: ...
    async def add(self, *, user_id: str, project_name: str,
                  receipt: CommandReceipt) -> None: ...

class ProviderExecutionAdapter(Protocol):
    capability_profile: ProviderCapabilityProfile
    async def submit(self, *, attempt: AttemptSnapshot,
                     request: ProviderRequest) -> ProviderObservation: ...
    async def reconcile(self, attempt: AttemptSnapshot) -> ProviderObservation | None: ...
    async def poll(self, attempt: AttemptSnapshot) -> ProviderObservation: ...
    async def cancel(self, attempt: AttemptSnapshot) -> ProviderObservation: ...

class ExecutionAttemptService(Protocol):
    async def plan_and_submit(
        self, *, user_id: str, project_name: str,
        attempt: PlannedExecutionAttempt, request: ProviderRequest,
        adapter: ProviderExecutionAdapter,
    ) -> AttemptSnapshot: ...
    async def reconcile(
        self, *, user_id: str, project_name: str, execution_id: str,
    ) -> ReconcileResult: ...
```

```python
def fold_observation(
    snapshot: AttemptSnapshot,
    observation: PersistedProviderObservation,
    capability: ProviderCapabilityProfile,
) -> AttemptSnapshot: ...
```

The idempotent identity of `plan()` is `(user_id, project_name, task_id,
attempt_no)`. Exact replay requires equality of `execution_id`, `request_digest`,
`route`, `client_token` and `created_at`; any unequal field raises
`AttemptIdentityMismatch`. All public reads include `(user_id, project_name)`;
unknown and foreign IDs are indistinguishable.

`CommandReceipt.result_digest` is the hash of canonical UTF-8 JSON with exact
shape `{"schema_version": 1, "task_id": str, "result": object}`. Map keys sort
lexicographically, arrays retain order and non-finite numbers are forbidden. A
generation command receipt is immutable and never backfilled with an execution
ID; the task-to-attempt relation supplies that join.

`CommandReceiptRepository.add()` only stages the immutable row. Its caller must
use the same SQLAlchemy session and transaction as `TaskRepository`, so either
the new task and receipt both commit or neither does. Exact replay reads the
original receipt; a matching key with a different command digest is rejected.

`acquire_lease()` increments and returns `lease_token`. `transition_worker()` and
`release_lease()` compare owner, token, expected state version and
`lease_expires_at > database_now` in the same statement. Provider observations
and operator resolutions use their dedicated methods: the adapter returns facts
only and never mutates state; `ExecutionAttemptService` passes those facts to the
repository fold.

### 4.2 Transition rules

Only the following edges are legal:

```text
PLANNED -> SUBMITTING | FAILED_BEFORE_ACCEPTANCE
SUBMITTING -> ACCEPTED | SUBMIT_OUTCOME_UNKNOWN | FAILED_BEFORE_ACCEPTANCE
SUBMIT_OUTCOME_UNKNOWN -> ACCEPTED | RUNNING | SUCCEEDED | FAILED | CANCELLED
                       | FAILED_BEFORE_ACCEPTANCE | NEEDS_OPERATOR
ACCEPTED -> RUNNING | SUCCEEDED | FAILED | CANCEL_REQUESTED
RUNNING -> SUCCEEDED | FAILED | CANCEL_REQUESTED
CANCEL_REQUESTED -> CANCELLED | SUCCEEDED | FAILED | CANCEL_OUTCOME_UNKNOWN
CANCEL_OUTCOME_UNKNOWN -> CANCELLED | SUCCEEDED | FAILED | NEEDS_OPERATOR
NEEDS_OPERATOR -> ACCEPTED | RUNNING | SUCCEEDED | FAILED | CANCELLED
                | FAILED_BEFORE_ACCEPTANCE
```

Terminal states are `SUCCEEDED`, `FAILED_BEFORE_ACCEPTANCE`, `FAILED`,
and `CANCELLED`. `NEEDS_OPERATOR` is a non-terminal, fail-closed pause and its
outgoing edges require an exact `OperatorResolutionReceipt`; it cannot be changed
by a worker command. Terminal provider truth may complete a pending cancel, but
no transition leaves a terminal state.

Operator actions are closed and evidence-bearing: `resolved_state` is mandatory;
`BIND_REMOTE_JOB` requires a non-empty provider job ID and resolves only to
`ACCEPTED` or `RUNNING`;
`CONFIRM_NOT_SUBMITTED` requires proof of non-submission and resolves only to
`FAILED_BEFORE_ACCEPTANCE`; `CONFIRM_TERMINAL` requires a terminal observation
kind plus evidence and resolves to its matching terminal state. No operator
receipt may submit a new remote job or mutate attempt identity.

An observation discovered while an attempt is unknown may take a direct legal
edge to its observed remote state; the fold must not invent an intermediate
`ACCEPTED` observation. `NOT_FOUND` remains unknown during the qualified settling
window. After the window it becomes `FAILED_BEFORE_ACCEPTANCE` only when the
profile declares `AUTHORITATIVE_AFTER_SETTLING_WINDOW`; otherwise it becomes
`NEEDS_OPERATOR`. Duplicate `observation_id` is a no-op. PostgreSQL returns a
`PersistedProviderObservation` with monotonic `received_seq` per attempt.
Conflicting terminal facts that cannot be ordered never replace the first
committed terminal state. They append an `AttemptIntegrityIncident`, block
candidate promotion and usage finalization, and require an operator receipt to
resolve the incident. Resolution on an already-terminal attempt confirms the
first committed terminal truth and closes the incident without a state
transition; it cannot replace that truth with the conflicting terminal fact. A
provider sequence participates in ordering only when it is an integer and the
exact qualified profile declares `provider_sequence_is_monotonic=true`.
`received_seq`, not timestamp or UUID, makes local replay deterministic.

Every attempt mutation checks `expected_version`, appends the applicable
observation/resolution evidence, and writes one `ProjectEvent` in the same
transaction. Therefore `project_events` is created by migration
`7a7c4a0e0001`, before any attempt repository is implemented.

## 5. H1-H2 submission and recovery protocol

1. The existing task is claimed using its current scheduler semantics.
2. Canonical request bytes and exact `ProviderRouteSnapshot` are computed once.
3. The command receipt is committed atomically with task creation. The `PLANNED`
   attempt is committed before network I/O and binds that durable task.
4. The attempt CASes to `SUBMITTING` and receives a fenced attempt lease.
5. The adapter submits with the attempt's stable client token when its qualified
   profile is `NATIVE_TOKEN`.
6. A definite pre-send error may retry the same attempt/token with bounded
   backoff. A response with job ID CASes to `ACCEPTED` and persists the exact
   route/job identity atomically.
7. Any error after bytes may have been sent CASes to `SUBMIT_OUTCOME_UNKNOWN`.
   Native-token or exact-metadata lookup may reconcile. `NONE` goes to
   `NEEDS_OPERATOR`; it never enqueues a blind resubmit.
8. Poll, download and cancel use only the persisted route snapshot. Mutable
   provider defaults are not consulted.

The existing task row may retain provider/job columns as a compatibility
projection, but `ExecutionAttempt` is the recovery authority. Projection failure
after attempt commit is repairable and may not change attempt truth.

## 6. H3-H4 candidate and promotion protocol

```python
@dataclass(frozen=True)
class CandidateIdentity:
    candidate_id: str
    user_id: str
    project_name: str
    artifact_key: str
    expected_content_digest: str

@dataclass(frozen=True)
class VerifiedCandidateObject:
    candidate_id: str
    project_name: str
    artifact_key: str
    object_ref: str
    byte_size: int
    content_digest: str
    media_probe_digest: str

@dataclass(frozen=True)
class MasterHeadSnapshot:
    artifact_key: str
    master_version: int
    candidate_id: str
    object_ref: str
    content_digest: str
    approval_record: str

class AtomicPromotionService:
    async def promote(self, *, user_id: str, project_name: str,
                      artifact_key: str, candidate_id: str,
                      expected_master_version: int,
                      approval_record: str, command_id: str) -> MasterHeadSnapshot: ...

class CandidateRetentionPolicy(Protocol):
    async def can_delete(self, *, user_id: str, project_name: str,
                         candidate_id: str) -> bool: ...

class MasterResolver(Protocol):
    async def get_exact(self, *, user_id: str, project_name: str,
                        artifact_key: str) -> MasterHeadSnapshot | None: ...
```

Candidate preparation writes a temporary file on the same filesystem, flushes,
fsyncs, verifies size/digest/media probe, then renames to an immutable final path.
For an object store, the adapter must prove versioned/create-only writes and
checksum verification; an S3-shaped API is not assumed to have S3 semantics.

Promotion locks/CASes exactly one master head. It verifies project scope,
candidate bytes, candidate lifecycle, content fingerprint and approval record,
then appends the head version, promotion receipt, usage link and event/outbox in
one PostgreSQL transaction. A manifest/version projection is updated after the
authority commit through an idempotent projector. Until all authoritative readers
consume the DB head, reads compare DB and manifest and fail closed on divergence.
Every existing candidate/media deletion route calls `CandidateRetentionPolicy`.
It returns false for a candidate referenced by a master head, incomplete backup
set, active attempt or retained promotion receipt. M7 adds this shared guard and
route-inventory tests, not another garbage-collection scheduler.

All authoritative master reads go through one `MasterResolver` that compares the
database head with the compatibility manifest/version projection and fails with
`M7_MASTER_DIVERGED` on mismatch. M7-B acceptance includes a graph-derived,
coverage-checked reader inventory and an architecture test rejecting direct
legacy current-version/manifest selection outside that resolver. The projection
may remain for compatibility; it cannot remain an unguarded authority.

## 7. H5 recovery and durable project events

Recovery scans only expired attempt leases or explicit unknown/cancel states. A
fenced worker must include `execution_id`, lease owner, lease token and expected
state version in every worker-authority write. Restart behavior is deterministic:

- remote ID present: exact-route poll/download/cancel resume;
- unknown + qualified lookup: bounded reconcile;
- unknown + no lookup: `NEEDS_OPERATOR`;
- completion while backend is down: later exact-route polling appends the
  terminal observation idempotently;
- local result-download failure: retry download for the same remote job, never
  submit again;
- SSE disconnect: no task or attempt state transition.

Provider webhook receivers are outside M7 v1. Every M7 capability profile has
`supports_webhook=false`; adding a receiver requires a later reviewed design for
signature verification, replay protection, tenancy and rate limiting.

```python
@dataclass(frozen=True)
class DurableProjectEvent:
    event_id: int
    user_id: str
    project_name: str
    task_id: str | None
    execution_id: str | None
    event_type: ProjectEventType
    state_version: int | None
    public_payload: dict[str, object]
    payload_schema_version: int
    trace_id: str | None
    dedupe_key: str

class ProjectEventRepository(Protocol):
    async def replay_after(self, *, user_id: str, project_name: str,
                           cursor: int | None, limit: int) -> list[DurableProjectEvent]: ...
    async def high_watermark(self, *, user_id: str, project_name: str) -> int: ...
```

The SSE route validates cursor syntax and project authorization, subscribes to a
wake-up channel, reads `(cursor, high_watermark]`, then repeatedly drains durable
events before waiting. This order permits duplicate wakeups but no gaps. Cursor
retention failure yields HTTP 409 with typed `EVENT_CURSOR_EXPIRED` and a
snapshot route; the frontend fetches snapshot, replaces projection state, clears
the cursor and reconnects. Event delivery is at least once.

## 8. H6 backup and clean-target restore

```python
@dataclass(frozen=True)
class MediaInventoryEntry:
    project_name: str
    artifact_key: str
    object_ref: str
    object_version: str | None
    byte_size: int
    content_digest: str

@dataclass(frozen=True)
class BackupSetManifest:
    backup_set_id: str
    source_deployment_id: str
    release_git_sha: str
    release_image_digest: str
    postgres_version: str
    alembic_head: str
    database_backup_ref: str
    recovery_target: str
    configuration_digest: str
    media: tuple[MediaInventoryEntry, ...]
    state: BackupSetState

@dataclass(frozen=True)
class BackupVerdict:
    backup_set_id: str
    accepted: bool
    reason_codes: tuple[str, ...]
    checked_master_count: int
    checked_media_count: int
    measured_rpo_seconds: int | None
    measured_rto_seconds: int | None
```

M7's baseline drill uses a maintenance/write fence and GC retention lease:

1. refuse new mutations and drain/fence in-flight promotions;
2. record release/config/schema identity and database recovery point;
3. produce the database backup and media inventory from the same authoritative
   snapshot; retain/copy every exact immutable object version;
4. verify database backup, media size/digest and inventory closure before marking
   the set `COMPLETE`;
5. restore to a fresh database and empty media root/prefix;
6. verify exact release/schema compatibility, all project/manifest/master refs,
   checksums and media probes, then run no-provider Golden A/B review/export;
7. record measured recovery point, RPO and RTO and mark `VERIFIED` only on pass.

Credentials are not stored in project media or the manifest. Their backup policy
and restore injection are separate access-controlled operator steps. PITR is an
optional production-candidate profile, never assumed from a base backup alone.

## 9. H7 correlation and secret policy

Every generation can be joined by durable IDs:

```text
request_id -> method_decision_id -> task_id -> execution_id
-> provider_job_ref -> candidate_id -> master_version -> usage_entry_id
```

OpenTelemetry supplies trace/span correlation within each process lifetime.
Restarted work begins a new trace/span and links to the prior trace when known;
durable IDs remain attributes. Required low-cardinality attributes are
`service.name`, `deployment.environment`, `operation.name`, `attempt.state`,
`provider.id` and `failure.reason_code`. Task/execution/candidate IDs may appear
in logs and exemplars but not metric labels.

An allowlist excludes raw content, credentials, authorization/cookie headers,
signed URLs, webhook secrets, provider response bodies, absolute local paths,
email and user ID. General telemetry uses an HMAC-derived provider-job reference;
raw job ID stays in the execution repository. W3C baggage is cleared at provider
boundaries and contains no user/project/provider identity. Secret-canary tests
scan application logs, exported spans and durable public event payloads.

## 10. H8 compatibility and provider qualification

Each upstream candidate is represented by a machine-readable report containing:

- current Host SHA, upstream URL, old/new SHA, merge base and integration method;
- verified source/license/dependency provenance and complete change inventory;
- migration rehearsal result on a restored production-like snapshot;
- static, type, import, dependency, i18n, frontend and website gate results;
- H1-H8 contract/fault suite results;
- Golden A/B no-provider restore smoke and approved bounded provider canary;
- browser create/generate/review/failed-regenerate/approve/export and cross-scope
  denial evidence;
- `UNCHANGED | ADAPTED | DEFERRED | REJECTED` disposition per relevant change;
- rollback target and evidence hashes.

Provider capability profiles are `UNQUALIFIED`, `OFFLINE_VERIFIED`,
`SANDBOX_VERIFIED`, or `QUALIFIED`. Only `QUALIFIED` routes may be enabled in a
production-candidate configuration. Paid canaries, production-like infrastructure
discovery, credential use and deployment require explicit operational approval;
local fixtures and offline contract tests do not.

## 11. Verification matrix

| Gate | Required executable evidence |
|---|---|
| H1 | provider A submit; exact route/job persisted; restart after defaults change to B; poll A; one result/usage |
| H2 | duplicate command, concurrent worker, retry and restart produce one task/attempt and at most one remote job under qualified native token |
| H3 | failed and successful-unapproved regeneration leave old master bytes/head unchanged |
| H4 | fault at every prepare/commit/project cut; readers observe complete old or complete new head; concurrent CAS has one winner |
| H5 | real process kill before/after submit receipt, mid-poll/download/cancel; remote completion while down; SSE loss has no execution effect |
| H6 | complete backup set restored to clean DB/media target; 100% approved-master refs resolve/probe; measured RPO/RTO |
| H7 | Golden join from request through usage/master; secret canary absent from log/span/event evidence |
| H8 | pinned compatibility report, migration rehearsal, full gates, Golden/browser evidence and rollback target |

Tests use controllable provider and media fakes at public ports, PostgreSQL for
locking/uniqueness/fencing assertions, and subprocess/SIGKILL for restart gates.
No test may claim a provider capability that was not proved against the exact
version. A zero-test selection, required skip, dirty evidence HEAD or historical
green run is a failure.

## 12. Exit states and stop conditions

- `M7-A ACCEPTED`: every paid async submit path is attempt-bound or explicitly
  disabled; H1/H2 fault suite passes.
- `M7-B ACCEPTED`: immutable candidate and atomic authoritative promotion pass
  bounded fault injection; H3/H4 pass.
- `M7-C ACCEPTED`: process restart/cancel/remote completion and durable SSE replay
  pass; H5 passes.
- `M7-D ACCEPTED`: clean-target restore and correlation/redaction evidence pass;
  state may advance to `RECOVERY_VERIFIED`.
- `M7-E ACCEPTED`: compatibility, qualified providers, near-production Golden
  A/B, browser and operator evidence pass; dossier may claim
  `PRODUCTION_CANDIDATE`.

Any changed authority seam, non-linear Alembic head, inability to enumerate all
paid submit routes, storage backend without the required immutable/CAS semantics,
or provider without safe reconciliation stops that route fail-closed with a
machine-readable reason. It does not authorize a new architecture.

Task 0 hashes the complete ordered Alembic revision graph, not only its current
head. After a checkpoint accepts a migration, that revision is immutable. A later
schema defect stops execution with `M7_ACCEPTED_SCHEMA_CHANGE_REQUIRED`, triggers
a design amendment and adds a new linear revision after the then-current head;
Claude Code may not edit or choose that revision autonomously.

`PRODUCTION_APPROVED` remains outside M7 implementation acceptance and requires
separate Human/operations approval after security, provider, restore and launch
review. This spec authorizes no production operation.
