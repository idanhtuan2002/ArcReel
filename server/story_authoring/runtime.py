"""Durable run state of one story-authoring run.

The whole run state — node heads with their generation epochs, the revision index, the attempt ledger,
budget usage and the checkpoint — is one JSON document in the run task's ``execution_checkpoint_json``.
It changes only through :class:`RunStateStore.apply`, which reads it, applies a pure transition and writes
it back through ``TaskRepository.write_story_run_state`` (row lock + version compare-and-set). Budget
reservation and the attempt record therefore change in one atomic step.

Model calls go through :class:`StoryAttemptSink`: a call is reserved before it is sent, marked dispatched
immediately before sending, and settled after. Budget is charged at its reserved maximum until the actual
usage is known; an attempt whose outcome is unknown keeps its full charge. Usage rows in ``api_calls`` are
observability (currency ``LOCAL``, cost 0; ``request_id`` is the attempt ID, one provider request per
attempt); the run state is the authority.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.api_call import ApiCall
from lib.db.repositories.task_repo import StoryRunStateConflict, StoryRunStateRace, TaskRepository
from lib.db.repositories.usage_repo import SettlementInput, UsageRepository
from server.story_authoring.contracts import (
    LOCAL_CURRENCY,
    AttemptKind,
    StoryFailureCode,
    StoryLimits,
    StoryScope,
)
from server.story_authoring.generation import StoryStepError

logger = logging.getLogger(__name__)

RUN_STATE_SCHEMA = "story-run-state-v1"
MAX_TRANSFORM_RETRIES = 20
NO_GENERATION_CODES = frozenset({StoryFailureCode.MODEL_UNAVAILABLE, StoryFailureCode.INPUT_OVER_CONTEXT})


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RunPhase(StrEnum):
    RUNNING = "RUNNING"
    AWAITING_GATE_A = "AWAITING_GATE_A"
    READY_FOR_APPROVAL = "READY_FOR_APPROVAL"
    APPROVING = "APPROVING"
    PARTIALLY_COMMITTED = "PARTIALLY_COMMITTED"
    COMMIT_BLOCKED = "COMMIT_BLOCKED"
    COMMITTED = "COMMITTED"
    WITHDRAWN = "WITHDRAWN"
    DISCARDED = "DISCARDED"
    ABORTED_PARTIAL = "ABORTED_PARTIAL"
    BLOCKED_BUDGET = "BLOCKED_BUDGET"
    BLOCKED_QUALITY = "BLOCKED_QUALITY"
    BLOCKED_BINDING_MISMATCH = "BLOCKED_BINDING_MISMATCH"
    BLOCKED_PROPAGATION = "BLOCKED_PROPAGATION"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    RECOVERY_INCONSISTENT = "RECOVERY_INCONSISTENT"


class AttemptState(StrEnum):
    RESERVED = "RESERVED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class RevisionOutcome(StrEnum):
    HEAD = "HEAD"
    STALE_RESULT = "STALE_RESULT"


class AttemptRecord(_Frozen):
    attempt_id: str
    step_id: str
    kind: AttemptKind
    request_digest: str
    state: AttemptState
    reserved_input_tokens: int = Field(ge=0)
    reserved_output_tokens: int = Field(ge=0)
    charged_input_tokens: int = Field(ge=0)
    charged_output_tokens: int = Field(ge=0)
    duration_ms: int = Field(default=0, ge=0)
    done_reason: str | None = None
    failure_code: StoryFailureCode | None = None
    ledger_call_id: int | None = None
    reserved_at: datetime


class BudgetUsage(_Frozen):
    """Charged usage, including the outstanding reservations of unsettled attempts."""

    count_calls: int = 0
    generate_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    model_milliseconds: int = 0


class RevisionRecord(_Frozen):
    revision_id: str
    node_id: str
    digest: str
    fingerprint: str
    attempt_id: str | None
    outcome: RevisionOutcome
    created_at: datetime


class NodeHead(_Frozen):
    node_id: str
    head_revision_id: str | None = None
    generation_epoch: int = Field(default=0, ge=0)
    required_fingerprint: str | None = None


class Checkpoint(_Frozen):
    node_id: str
    revision_id: str
    attempt_id: str | None
    digest: str


class ApprovalRecord(_Frozen):
    """The touchpoint-2 Approve, persisted before any decision is sent so every step reuses it exactly."""

    manifest_digest: str
    actor_id: str
    grant_event_digest: str
    approved_at: datetime
    accepted_exceptions: tuple[str, ...] = ()


class CommitProgress(_Frozen):
    offered_manifest_digest: str
    approval: ApprovalRecord | None = None
    completed_steps: tuple[str, ...] = ()
    blocked_step: str | None = None


class HandoffRecord(_Frozen):
    """The run's one hand-off to video: written ``PENDING`` before the source upload, ``DONE`` after it."""

    command_id: str
    filename: str
    export_digest: str
    done: bool = False
    path: str | None = None


class RunState(_Frozen):
    schema_id: str = RUN_STATE_SCHEMA
    state_version: int = Field(ge=1)
    run_id: str
    phase: RunPhase
    block_reason: str | None = None
    limits: StoryLimits
    started_at: datetime
    usage: BudgetUsage = BudgetUsage()
    attempts: tuple[AttemptRecord, ...] = ()
    nodes: Mapping[str, NodeHead] = Field(default_factory=dict)
    revisions: Mapping[str, RevisionRecord] = Field(default_factory=dict)
    checkpoint: Checkpoint | None = None
    commit: CommitProgress | None = None
    intents: Mapping[str, tuple[str, ...]] = Field(default_factory=dict)
    handoff: HandoffRecord | None = None
    blocked_findings: tuple[Mapping[str, str], ...] = ()
    retries: int = Field(default=0, ge=0)

    def attempt(self, attempt_id: str) -> AttemptRecord:
        for record in self.attempts:
            if record.attempt_id == attempt_id:
                return record
        raise KeyError(attempt_id)

    def node(self, node_id: str) -> NodeHead:
        return self.nodes.get(node_id) or NodeHead(node_id=node_id)


class BudgetExhausted(Exception):
    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class RunNotRunning(Exception):
    pass


def new_run_state(*, run_id: str, limits: StoryLimits, now: datetime) -> RunState:
    return RunState(state_version=1, run_id=run_id, phase=RunPhase.RUNNING, limits=limits, started_at=now)


def _replace_attempt(state: RunState, record: AttemptRecord) -> tuple[AttemptRecord, ...]:
    return tuple(record if a.attempt_id == record.attempt_id else a for a in state.attempts)


def _usage(state: RunState, **delta: int) -> BudgetUsage:
    values = state.usage.model_dump()
    for key, change in delta.items():
        values[key] += change
    return BudgetUsage(**values)


def reserve(
    state: RunState,
    *,
    attempt_id: str,
    step_id: str,
    kind: AttemptKind,
    request_digest: str,
    reserved_input_tokens: int,
    reserved_output_tokens: int,
    now: datetime,
) -> RunState:
    if state.phase is not RunPhase.RUNNING:
        raise RunNotRunning(f"run is {state.phase.value}")
    if any(a.attempt_id == attempt_id for a in state.attempts):
        raise ValueError(f"attempt {attempt_id} already exists")
    limits, usage = state.limits, state.usage
    calls_key = "count_calls" if kind is AttemptKind.COUNT else "generate_calls"
    calls_max = limits.count_calls_max if kind is AttemptKind.COUNT else limits.generate_calls_max
    checks = (
        (getattr(usage, calls_key) + 1 > calls_max, f"{calls_key} {calls_max}"),
        (
            usage.input_tokens + reserved_input_tokens > limits.input_tokens_max,
            f"input_tokens {limits.input_tokens_max}",
        ),
        (
            usage.output_tokens + reserved_output_tokens > limits.output_tokens_max,
            f"output_tokens {limits.output_tokens_max}",
        ),
        (
            usage.model_milliseconds > limits.wall_clock_max_seconds * 1000,
            f"wall_clock {limits.wall_clock_max_seconds}s",
        ),
    )
    for exceeded, cap in checks:
        if exceeded:
            raise BudgetExhausted(f"cap {cap} reached")
    record = AttemptRecord(
        attempt_id=attempt_id,
        step_id=step_id,
        kind=kind,
        request_digest=request_digest,
        state=AttemptState.RESERVED,
        reserved_input_tokens=reserved_input_tokens,
        reserved_output_tokens=reserved_output_tokens,
        charged_input_tokens=reserved_input_tokens,
        charged_output_tokens=reserved_output_tokens,
        reserved_at=now,
    )
    return state.model_copy(
        update={
            "attempts": (*state.attempts, record),
            "usage": _usage(
                state,
                **{calls_key: 1},
                input_tokens=reserved_input_tokens,
                output_tokens=reserved_output_tokens,
            ),
        }
    )


def mark_dispatched(state: RunState, *, attempt_id: str, ledger_call_id: int | None) -> RunState:
    if state.phase is not RunPhase.RUNNING:
        raise RunNotRunning(f"run is {state.phase.value}")
    record = state.attempt(attempt_id)
    if record.state is not AttemptState.RESERVED:
        raise ValueError(f"attempt {attempt_id} is {record.state.value}, not RESERVED")
    updated = record.model_copy(update={"state": AttemptState.DISPATCHED, "ledger_call_id": ledger_call_id})
    return state.model_copy(update={"attempts": _replace_attempt(state, updated)})


def _settle(
    state: RunState,
    record: AttemptRecord,
    *,
    new_state: AttemptState,
    input_tokens: int,
    output_tokens: int,
    duration_ms: int,
    done_reason: str | None = None,
    failure_code: StoryFailureCode | None = None,
    released_call: bool = False,
) -> RunState:
    calls_key = "count_calls" if record.kind is AttemptKind.COUNT else "generate_calls"
    updated = record.model_copy(
        update={
            "state": new_state,
            "charged_input_tokens": input_tokens,
            "charged_output_tokens": output_tokens,
            "duration_ms": duration_ms,
            "done_reason": done_reason,
            "failure_code": failure_code,
        }
    )
    usage = _usage(
        state,
        input_tokens=input_tokens - record.charged_input_tokens,
        output_tokens=output_tokens - record.charged_output_tokens,
        model_milliseconds=duration_ms,
        **({calls_key: -1} if released_call else {}),
    )
    return state.model_copy(update={"attempts": _replace_attempt(state, updated), "usage": usage})


def complete(
    state: RunState, *, attempt_id: str, input_tokens: int, output_tokens: int, done_reason: str, duration_ms: int
) -> RunState:
    record = state.attempt(attempt_id)
    if record.state is not AttemptState.DISPATCHED:
        raise ValueError(f"attempt {attempt_id} is {record.state.value}, not DISPATCHED")
    return _settle(
        state,
        record,
        new_state=AttemptState.COMPLETED,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        duration_ms=duration_ms,
        done_reason=done_reason,
    )


def fail(
    state: RunState,
    *,
    attempt_id: str,
    code: StoryFailureCode,
    input_tokens: int | None = None,
    duration_ms: int = 0,
) -> RunState:
    """Settle a failed attempt. A never-dispatched attempt releases its whole reservation and its call."""
    record = state.attempt(attempt_id)
    if record.state is AttemptState.RESERVED:
        return _settle(
            state,
            record,
            new_state=AttemptState.FAILED,
            input_tokens=0,
            output_tokens=0,
            duration_ms=0,
            failure_code=code,
            released_call=True,
        )
    if record.state is not AttemptState.DISPATCHED:
        raise ValueError(f"attempt {attempt_id} is {record.state.value}")
    return _settle(
        state,
        record,
        new_state=AttemptState.FAILED,
        input_tokens=record.reserved_input_tokens if input_tokens is None else input_tokens,
        output_tokens=0 if code in NO_GENERATION_CODES else record.reserved_output_tokens,
        duration_ms=duration_ms,
        failure_code=code,
    )


def mark_unknown(state: RunState, *, attempt_id: str) -> RunState:
    record = state.attempt(attempt_id)
    if record.state is not AttemptState.DISPATCHED:
        raise ValueError(f"attempt {attempt_id} is {record.state.value}, not DISPATCHED")
    updated = record.model_copy(
        update={"state": AttemptState.UNKNOWN, "failure_code": StoryFailureCode.OUTCOME_UNKNOWN}
    )
    return state.model_copy(update={"attempts": _replace_attempt(state, updated)})


def add_intent(state: RunState, *, node_ids: tuple[str, ...], note: str) -> RunState:
    """Attach a revision note (a Human request or the critic's ending rewrite) to nodes; it enters their fingerprints."""
    intents = dict(state.intents)
    for node_id in node_ids:
        intents[node_id] = (*intents.get(node_id, ()), note)
    return state.model_copy(update={"intents": intents})


def set_phase(state: RunState, phase: RunPhase, *, reason: str | None = None) -> RunState:
    """Change the phase; a new phase replaces the block reason and clears the blocking findings."""
    return state.model_copy(update={"phase": phase, "block_reason": reason, "blocked_findings": ()})


def reopen_unconverged(state: RunState) -> RunState:
    """A Human retry: every node whose head does not carry its required fingerprint gets a new generation epoch,
    so its call cap starts again and any late result of the old epoch is fenced."""
    nodes = dict(state.nodes)
    for node_id, node in state.nodes.items():
        head = state.revisions.get(node.head_revision_id) if node.head_revision_id is not None else None
        if head is None or head.fingerprint != node.required_fingerprint:
            nodes[node_id] = node.model_copy(update={"generation_epoch": node.generation_epoch + 1})
    return state.model_copy(update={"nodes": nodes, "retries": state.retries + 1})


def require(state: RunState, *, node_id: str, fingerprint: str) -> RunState:
    """Record the fingerprint the node's next head must carry; any change bumps the generation epoch."""
    node = state.node(node_id)
    if node.required_fingerprint == fingerprint:
        return state
    updated = node.model_copy(
        update={"required_fingerprint": fingerprint, "generation_epoch": node.generation_epoch + 1}
    )
    return state.model_copy(update={"nodes": {**state.nodes, node_id: updated}})


def promote(
    state: RunState,
    *,
    revision_id: str,
    node_id: str,
    digest: str,
    fingerprint: str,
    attempt_id: str | None,
    expected_head_revision_id: str | None,
    generation_epoch: int,
    now: datetime,
) -> tuple[RunState, bool]:
    """Record a revision and make it the node head only if nothing changed since its attempt was dispatched.

    A revision that fails any condition is stored as ``STALE_RESULT``; the head and epoch stay unchanged.
    The first promotion bumps the epoch, so a second result dispatched with the same expectations is stale.
    """
    if revision_id in state.revisions:
        raise ValueError(f"revision {revision_id} already exists")
    node = state.node(node_id)
    promoted = (
        state.phase is RunPhase.RUNNING
        and node.required_fingerprint is not None
        and node.required_fingerprint == fingerprint
        and node.head_revision_id == expected_head_revision_id
        and node.generation_epoch == generation_epoch
    )
    record = RevisionRecord(
        revision_id=revision_id,
        node_id=node_id,
        digest=digest,
        fingerprint=fingerprint,
        attempt_id=attempt_id,
        outcome=RevisionOutcome.HEAD if promoted else RevisionOutcome.STALE_RESULT,
        created_at=now,
    )
    update: dict[str, Any] = {"revisions": {**state.revisions, revision_id: record}}
    if promoted:
        update["nodes"] = {
            **state.nodes,
            node_id: node.model_copy(
                update={"head_revision_id": revision_id, "generation_epoch": node.generation_epoch + 1}
            ),
        }
        update["checkpoint"] = Checkpoint(
            node_id=node_id, revision_id=revision_id, attempt_id=attempt_id, digest=digest
        )
    return state.model_copy(update=update), promoted


def reconcile(state: RunState, *, blob_exists: Callable[[str], bool]) -> tuple[RunState, tuple[str, ...]]:
    """Settle attempts interrupted by a restart and verify heads and checkpoint against the revision index.

    ``RESERVED`` attempts were never sent and are released; ``DISPATCHED`` attempts become ``UNKNOWN`` and keep
    their reserved charge. Any head or checkpoint that names a missing revision or blob moves the run to
    ``RECOVERY_INCONSISTENT`` with the exact problems; nothing is regenerated here.
    """
    for record in state.attempts:
        if record.state is AttemptState.RESERVED:
            state = fail(state, attempt_id=record.attempt_id, code=StoryFailureCode.NOT_DISPATCHED)
        elif record.state is AttemptState.DISPATCHED:
            state = mark_unknown(state, attempt_id=record.attempt_id)
    problems: list[str] = []
    for node in state.nodes.values():
        if node.head_revision_id is None:
            continue
        revision = state.revisions.get(node.head_revision_id)
        if revision is None or revision.node_id != node.node_id or revision.outcome is not RevisionOutcome.HEAD:
            problems.append(
                f"head of {node.node_id} names revision {node.head_revision_id} that is not its HEAD record"
            )
        elif not blob_exists(revision.digest):
            problems.append(f"head of {node.node_id} names missing content {revision.digest}")
    checkpoint = state.checkpoint
    if checkpoint is not None:
        revision = state.revisions.get(checkpoint.revision_id)
        if (
            revision is None
            or revision.node_id != checkpoint.node_id
            or revision.digest != checkpoint.digest
            or revision.attempt_id != checkpoint.attempt_id
        ):
            problems.append(f"checkpoint names revision {checkpoint.revision_id} that does not match the index")
    if problems:
        state = set_phase(state, RunPhase.RECOVERY_INCONSISTENT, reason="; ".join(problems))
    return state, tuple(problems)


def orphan_digests(state: RunState, stored: Iterable[str]) -> tuple[str, ...]:
    """Stored content no revision names: written before a crash prevented its revision. Kept, never used."""
    referenced = {revision.digest for revision in state.revisions.values()}
    return tuple(sorted(set(stored) - referenced))


type Factory = async_sessionmaker[AsyncSession]


class RunStateStore:
    def __init__(self, session_factory: Factory, *, task_id: str) -> None:
        self._session_factory = session_factory
        self._task_id = task_id

    @property
    def task_id(self) -> str:
        return self._task_id

    async def load(self) -> RunState:
        async with self._session_factory() as session:
            _, state_json = await TaskRepository(session).read_story_run_state(self._task_id)
        if state_json is None:
            raise StoryRunStateConflict(f"story run {self._task_id} has no state yet")
        return RunState.model_validate_json(state_json)

    async def initialize(self, state: RunState) -> RunState:
        async with self._session_factory() as session:
            await TaskRepository(session).write_story_run_state(
                self._task_id,
                expected_version=None,
                state_json=state.model_dump_json(),
                new_version=state.state_version,
            )
        return state

    def _transform[T](
        self, change: Callable[[RunState], tuple[RunState, T]], outcome: list[tuple[RunState, T]]
    ) -> Callable[[str | None], str | None]:
        def transform(current_json: str | None) -> str | None:
            if current_json is None:
                raise StoryRunStateConflict(f"story run {self._task_id} has no state yet")
            current = RunState.model_validate_json(current_json)
            changed, result = change(current)
            if changed == current:
                outcome.append((current, result))
                return None
            written = changed.model_copy(update={"state_version": current.state_version + 1})
            outcome.append((written, result))
            return written.model_dump_json()

        return transform

    async def apply[T](self, change: Callable[[RunState], tuple[RunState, T]]) -> tuple[RunState, T]:
        """Apply a pure transition under the run row's lock; the state version increases on every write.

        On PostgreSQL the row lock serializes writers. SQLite reports a concurrent writer as a lock error or
        a conflict, and the transition is re-applied to the fresh state.
        """
        for _ in range(MAX_TRANSFORM_RETRIES):
            outcome: list[tuple[RunState, T]] = []
            transform = self._transform(change, outcome)
            try:
                async with self._session_factory() as session:
                    await TaskRepository(session).transform_story_run_state(self._task_id, transform)
            except (StoryRunStateRace, OperationalError):
                continue
            return outcome[-1]
        raise StoryRunStateConflict(
            f"story run {self._task_id} kept changing; gave up after {MAX_TRANSFORM_RETRIES} tries"
        )


def _only(transition: Callable[[RunState], RunState]) -> Callable[[RunState], tuple[RunState, None]]:
    return lambda state: (transition(state), None)


class StoryAttemptSink:
    """The durable :class:`~server.story_authoring.generation.AttemptSink` for one run."""

    def __init__(
        self,
        *,
        store: RunStateStore,
        session_factory: Factory,
        provider_id: str,
        model_id: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        attempt_ids: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self._store = store
        self._session_factory = session_factory
        self._provider_id = provider_id
        self._model_id = model_id
        self._clock = clock
        self._attempt_ids = attempt_ids
        self._scopes: dict[str, StoryScope] = {}
        self._dispatched_at: dict[str, datetime] = {}

    async def reserve(
        self,
        *,
        scope: StoryScope,
        step_id: str,
        kind: AttemptKind,
        request_digest: str,
        reserved_input_tokens: int,
        reserved_output_tokens: int,
    ) -> str:
        attempt_id = f"{self._store.task_id}:{self._attempt_ids()}"
        now = self._clock()

        def change(state: RunState) -> tuple[RunState, str | None]:
            try:
                return reserve(
                    state,
                    attempt_id=attempt_id,
                    step_id=step_id,
                    kind=kind,
                    request_digest=request_digest,
                    reserved_input_tokens=reserved_input_tokens,
                    reserved_output_tokens=reserved_output_tokens,
                    now=now,
                ), None
            except BudgetExhausted as exc:
                return set_phase(state, RunPhase.BLOCKED_BUDGET, reason=exc.detail), exc.detail
            except RunNotRunning as exc:
                return state, f"not running: {exc}"

        _, refusal = await self._store.apply(change)
        if refusal is not None:
            code = (
                StoryFailureCode.RUN_NOT_RUNNING
                if refusal.startswith("not running")
                else StoryFailureCode.BUDGET_EXHAUSTED
            )
            raise StoryStepError(code, refusal, step_id=step_id)
        self._scopes[attempt_id] = scope
        return attempt_id

    async def dispatched(self, attempt_id: str) -> None:
        scope = self._scopes[attempt_id]
        call_id = await self._open_usage_row(attempt_id, scope)

        def change(state: RunState) -> tuple[RunState, bool]:
            try:
                return mark_dispatched(state, attempt_id=attempt_id, ledger_call_id=call_id), True
            except RunNotRunning:
                return fail(state, attempt_id=attempt_id, code=StoryFailureCode.NOT_DISPATCHED), False

        _, sendable = await self._store.apply(change)
        if not sendable:
            await self._close_usage_row(call_id, status="failed", error=StoryFailureCode.NOT_DISPATCHED.value)
            step = (await self._store.load()).attempt(attempt_id).step_id
            raise StoryStepError(StoryFailureCode.RUN_NOT_RUNNING, "run stopped before dispatch", step_id=step)
        self._dispatched_at[attempt_id] = self._clock()

    async def completed(
        self, attempt_id: str, *, input_tokens: int, output_tokens: int, done_reason: str, duration_ms: int
    ) -> None:
        state, _ = await self._store.apply(
            _only(
                lambda s: complete(
                    s,
                    attempt_id=attempt_id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    done_reason=done_reason,
                    duration_ms=duration_ms,
                )
            )
        )
        await self._close_usage_row(
            state.attempt(attempt_id).ledger_call_id,
            status="success",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    async def failed(
        self, attempt_id: str, *, code: StoryFailureCode, detail: str, input_tokens: int | None = None
    ) -> None:
        duration_ms = self._elapsed_ms(attempt_id)
        state, _ = await self._store.apply(
            _only(
                lambda s: fail(s, attempt_id=attempt_id, code=code, input_tokens=input_tokens, duration_ms=duration_ms)
            )
        )
        await self._close_usage_row(
            state.attempt(attempt_id).ledger_call_id,
            status="failed",
            error=f"{code.value}: {detail}",
            input_tokens=input_tokens,
        )

    async def unknown(self, attempt_id: str, *, detail: str) -> None:
        state, _ = await self._store.apply(_only(lambda s: mark_unknown(s, attempt_id=attempt_id)))
        await self._close_usage_row(
            state.attempt(attempt_id).ledger_call_id,
            status="failed",
            error=f"{StoryFailureCode.OUTCOME_UNKNOWN.value}: {detail}",
        )

    def _elapsed_ms(self, attempt_id: str) -> int:
        started = self._dispatched_at.get(attempt_id)
        return 0 if started is None else max(0, int((self._clock() - started).total_seconds() * 1000))

    async def _open_usage_row(self, attempt_id: str, scope: StoryScope) -> int | None:
        try:
            async with self._session_factory() as session:
                return await UsageRepository(session).start_call(
                    project_name=scope.project_name,
                    call_type="text",
                    model=self._model_id,
                    provider=self._provider_id,
                    user_id=scope.user_id,
                    task_id=self._store.task_id,
                    request_id=attempt_id,
                )
        except Exception:
            logger.exception(
                "usage row for story attempt %s could not be opened; the run state stays authoritative", attempt_id
            )
            return None

    async def _close_usage_row(
        self,
        call_id: int | None,
        *,
        status: str,
        error: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        if call_id is None:
            return
        try:
            async with self._session_factory() as session:
                await UsageRepository(session).finish_call(
                    call_id,
                    status=status,
                    settlement=SettlementInput(
                        cost_amount=0.0,
                        currency=LOCAL_CURRENCY,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    ),
                    error_message=error,
                )
        except Exception:
            logger.exception("usage row %s for a story attempt could not be closed", call_id)


async def recover_run(
    store: RunStateStore, *, session_factory: Factory, blob_exists: Callable[[str], bool]
) -> tuple[RunState, tuple[str, ...]]:
    """Reconcile a run after a restart, then close the usage rows of every attempt it settled."""
    before = await store.load()
    state, problems = await store.apply(lambda s: reconcile(s, blob_exists=blob_exists))
    settled = [record for record in state.attempts if before.attempt(record.attempt_id).state is not record.state]
    async with session_factory() as session:
        for record in settled:
            call_id = record.ledger_call_id
            if call_id is None:
                call_id = (
                    await session.execute(
                        select(ApiCall.id).where(
                            ApiCall.task_id == store.task_id, ApiCall.request_id == record.attempt_id
                        )
                    )
                ).scalar_one_or_none()
            if call_id is None:
                continue
            code = record.failure_code.value if record.failure_code else "RECOVERED"
            await UsageRepository(session).finish_call(
                call_id,
                status="failed",
                settlement=SettlementInput(cost_amount=0.0, currency=LOCAL_CURRENCY),
                error_message=f"{code}: settled by restart recovery",
            )
    return state, problems
