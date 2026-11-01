"""Controller and scheduler recovery against real PostgreSQL run, step, allocation and grant rows."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from lib.db.models.production_run import ProductionBudgetModel, ProductionRunModel, ProductionStepModel
from lib.db.repositories.automation_grants import AutomationGrantRepository
from lib.db.repositories.production_runs import ProductionRunRepository, StaleProductionRunError
from r2.automation.authorization import automation_principal
from r2.automation.identity import digest_value, policy_digest
from r2.contracts.automation import (
    AutomationGrant,
    AutomationOperation,
    OwnerReceipt,
    RunPolicy,
    RunScope,
    RunStage,
    RunStatus,
    StageOutcome,
    UsageReceipt,
)
from server.production_run.controller import ProductionController
from server.production_run.ports import StepPlan
from server.production_run.scheduler import ProductionScheduler
from tests.integration.lib.db.repositories.test_production_runs import command, policy

INPUT = "sha256:" + "c" * 64


class SimulatedCrash(RuntimeError):
    pass


class FakeOwner:
    """An owner queue keyed by task ID: a replayed dispatch returns the first submission."""

    owner = "story"

    def __init__(self) -> None:
        self.submissions: dict[str, OwnerReceipt] = {}
        self.provider_submit_count = 0
        self.kind = "PASS"
        self.states: dict[RunStage, str] = {RunStage.STORY: "READY_FOR_APPROVAL", RunStage.STORY_COMMIT: "COMMITTED"}
        self.cost = 10
        self.crash_before_submit = False
        self.crash_after_submit = False
        self.crash_in_inspect = False
        self.usage_missing = False
        self.during_dispatch: Callable[[], Awaitable[None]] | None = None

    async def plan(self, *, run):
        return StepPlan(
            unit_key="project",
            estimated_cost_minor_units=self.cost,
            estimated_model_calls=1,
            estimated_tasks=1,
            estimated_runtime_seconds=30,
        )

    async def dispatch(self, intent):
        if self.crash_before_submit:
            self.crash_before_submit = False
            raise SimulatedCrash("before submit")
        task_id = intent.identity.task_id
        if task_id not in self.submissions:
            self.provider_submit_count += 1
            self.submissions[task_id] = OwnerReceipt(
                owner=self.owner,
                receipt_ref=f"task:{task_id}",
                digest=digest_value("test.task", {"task_id": task_id}),
                task_id=task_id,
            )
        if self.during_dispatch is not None:
            hook, self.during_dispatch = self.during_dispatch, None
            await hook()
        if self.crash_after_submit:
            self.crash_after_submit = False
            raise SimulatedCrash("after submit")
        return self.submissions[task_id]

    async def inspect(self, *, intent, receipt):
        if self.crash_in_inspect:
            self.crash_in_inspect = False
            raise SimulatedCrash("in inspect")
        identity = intent.identity
        return StageOutcome(
            stage=identity.stage,
            generation=identity.generation,
            input_digest=identity.input_digest,
            policy_digest=identity.policy_digest,
            kind=self.kind,
            receipts=(receipt,),
            owner_state=self.states.get(identity.stage),
        )

    async def usage(self, *, receipt, reservation):
        if self.usage_missing:
            return None
        return UsageReceipt(
            owner=self.owner,
            receipt_ref="usage:" + receipt.receipt_ref,
            digest=receipt.digest,
            task_id=receipt.task_id,
            reservation_id=reservation.reservation_id,
            currency=reservation.currency,
            cost_minor_units=5,
            model_calls=1,
            tasks=1,
            runtime_seconds=10,
            outcome="KNOWN",
        )


class Witness:
    def __init__(self, digest: str = INPUT) -> None:
        self.value = digest

    async def digest(self, *, user_id, project_name):
        return self.value


def grant_for(run, *, policy_value=None, expires_in=3600):
    now = datetime.now(UTC)
    return AutomationGrant(
        user_id=run.user_id,
        project_name=run.project_name,
        run_id=run.run_id,
        grant_id="grant-" + run.run_id,
        version=1,
        state="ACTIVE",
        principal=automation_principal(run.run_id),
        issuer_id="actor",
        start_command_id="start-1",
        request_digest="sha256:" + "1" * 64,
        parent_sequence=1,
        parent_event_digest="sha256:" + "2" * 64,
        policy_digest=policy_digest(policy_value or run.policy),
        input_digest=run.input_digest,
        operations=frozenset(AutomationOperation),
        issued_at=now - timedelta(seconds=5),
        expires_at=now + timedelta(seconds=expires_in),
    )


def scope_of(run) -> RunScope:
    return RunScope(user_id=run.user_id, project_name=run.project_name, run_id=run.run_id)


async def make_run(
    sessions, *, run_policy: RunPolicy | None = None, grant: bool = True, revoked: bool = False, **grant_changes
):
    run_policy = run_policy or policy()
    async with sessions() as session, session.begin():
        run = await ProductionRunRepository(session).create(
            command=command(policy_digest=policy_digest(run_policy), mode=run_policy.mode), policy=run_policy
        )
        if grant:
            grants = AutomationGrantRepository(session)
            issued = grant_for(run, **grant_changes)
            await grants.append(issued, previous=None)
            if revoked:
                await grants.append(issued.model_copy(update={"version": 2, "state": "REVOKED"}), previous=issued)
    return run


def harness(sessions, owner=None, *, adapters=None, witness=None, owner_id="worker-1"):
    owner = owner or FakeOwner()
    controller = ProductionController(
        sessions,
        adapters=adapters if adapters is not None else dict.fromkeys(RunStage, owner),
        witness=witness or Witness(),
        poll_seconds=0,
    )
    return owner, ProductionScheduler(sessions, controller, owner_id=owner_id, lease_seconds=30, max_runs_per_scan=1)


async def current(sessions, run):
    async with sessions() as session:
        return await ProductionRunRepository(session).get(
            user_id=run.user_id, project_name=run.project_name, run_id=run.run_id
        )


async def expire_leases(sessions):
    async with sessions() as session, session.begin():
        await session.execute(
            sa.update(ProductionRunModel)
            .where(ProductionRunModel.lease_owner.is_not(None))
            .values(lease_until=sa.func.clock_timestamp() - sa.text("interval '1 second'"))
        )


async def steps(sessions, stage: RunStage) -> list[ProductionStepModel]:
    async with sessions() as session:
        return list(
            (await session.execute(sa.select(ProductionStepModel).where(ProductionStepModel.stage == stage.value)))
            .scalars()
            .all()
        )


async def allocation_count(sessions) -> int:
    async with sessions() as session:
        return int(await session.scalar(sa.select(sa.func.count()).select_from(ProductionBudgetModel)) or 0)


async def test_crash_after_enqueue_replays_owner_command(concurrent_session_factory):
    sessions = concurrent_session_factory
    run = await make_run(sessions)
    owner, first_host = harness(sessions)
    owner.crash_after_submit = True

    await first_host.scan_once()
    [first_receipt] = owner.submissions.values()
    [staged] = await steps(sessions, RunStage.BRIEF)
    assert staged.receipt_json is None

    await expire_leases(sessions)
    _owner, restarted = harness(sessions, owner, owner_id="worker-2")
    assert await restarted.scan_once() >= 1

    [step] = await steps(sessions, RunStage.BRIEF)
    resumed_receipt = OwnerReceipt.model_validate_json(step.receipt_json)
    assert resumed_receipt.task_id == first_receipt.task_id
    assert owner.provider_submit_count == 1
    assert await allocation_count(sessions) >= 1
    assert (await current(sessions, run)).stage is not RunStage.BRIEF


async def test_crash_before_dispatch_replays_the_staged_intent_and_reservation(concurrent_session_factory):
    sessions = concurrent_session_factory
    run = await make_run(sessions)
    owner, host = harness(sessions)
    owner.crash_before_submit = True

    await host.scan_once()
    assert owner.provider_submit_count == 0
    assert len(await steps(sessions, RunStage.BRIEF)) == 1
    assert await allocation_count(sessions) == 1

    await expire_leases(sessions)
    await host.scan_once()
    assert owner.provider_submit_count == 1
    assert len(await steps(sessions, RunStage.BRIEF)) == 1
    assert (await current(sessions, run)).stage is RunStage.STORY


async def test_crash_after_attach_inspects_without_redispatch(concurrent_session_factory):
    sessions = concurrent_session_factory
    run = await make_run(sessions)
    owner, host = harness(sessions)
    owner.crash_in_inspect = True

    await host.scan_once()
    [step] = await steps(sessions, RunStage.BRIEF)
    assert step.receipt_json is not None

    await expire_leases(sessions)
    await host.scan_once()
    assert owner.provider_submit_count >= 1
    assert len(owner.submissions) == owner.provider_submit_count
    [brief] = await steps(sessions, RunStage.BRIEF)
    assert brief.command_id == step.command_id
    assert (await current(sessions, run)).stage is not RunStage.BRIEF


async def test_two_scanners_claim_one_run_once(concurrent_session_factory):
    sessions = concurrent_session_factory
    await make_run(sessions)
    owner = FakeOwner()
    owner.kind = "WAIT"
    _, first = harness(sessions, owner, owner_id="worker-1")
    _, second = harness(sessions, owner, owner_id="worker-2")

    claimed = await asyncio.gather(first.scan_once(), second.scan_once())

    assert sum(claimed) == 1
    assert owner.provider_submit_count == 1


async def test_wait_outcome_reconciles_from_the_database_without_events_or_redispatch(concurrent_session_factory):
    sessions = concurrent_session_factory
    run = await make_run(sessions)
    owner, host = harness(sessions)
    owner.kind = "WAIT"

    await host.scan_once()
    assert (await current(sessions, run)).status is RunStatus.WAITING_TASK

    owner.kind = "PASS"
    host.wake()
    host.wake()
    await host.scan_once()

    assert owner.provider_submit_count == 1
    assert (await current(sessions, run)).stage is RunStage.STORY


async def test_story_task_succeeded_with_blocked_phase_fails_quality(concurrent_session_factory):
    sessions = concurrent_session_factory
    run = await make_run(sessions)
    owner, host = harness(sessions)
    owner.states[RunStage.STORY] = "BLOCKED_QUALITY"

    await host.scan_once()
    await host.scan_once()
    final = await current(sessions, run)
    assert final.status is RunStatus.FAILED_QUALITY
    assert final.reason == "BLOCKED_QUALITY"


async def test_external_input_change_blocks_before_any_dispatch(concurrent_session_factory):
    sessions = concurrent_session_factory
    run = await make_run(sessions)
    owner, host = harness(sessions, witness=Witness("sha256:" + "e" * 64))

    await host.scan_once()
    blocked = await current(sessions, run)
    assert blocked.status is RunStatus.BLOCKED_INPUT_CHANGED
    assert blocked.reason == "EXTERNAL_INPUT_CHANGED"
    assert owner.provider_submit_count == 0
    assert await host.scan_once() == 0


@pytest.mark.parametrize(
    ("grant", "changes"),
    [
        (False, {}),
        (True, {"revoked": True}),
        (True, {"expires_in": 1}),
        (True, {"policy_value": policy().model_copy(update={"max_tasks": 9})}),
    ],
    ids=["missing", "revoked", "expired", "other-policy"],
)
async def test_missing_revoked_expired_or_moved_grant_blocks_before_dispatch(
    concurrent_session_factory, grant, changes
):
    sessions = concurrent_session_factory
    run = await make_run(sessions, grant=grant, **changes)
    owner, host = harness(sessions)
    if changes.get("expires_in"):
        await asyncio.sleep(1.1)

    await host.scan_once()
    blocked = await current(sessions, run)
    assert (blocked.status, blocked.reason) == (RunStatus.BLOCKED_CONFIGURATION, "AUTOMATION_GRANT_NOT_CURRENT")
    assert owner.provider_submit_count == 0


async def test_incomplete_stage_capability_blocks(concurrent_session_factory):
    sessions = concurrent_session_factory
    run = await make_run(sessions)
    owner, host = harness(sessions, adapters={})

    await host.scan_once()
    blocked = await current(sessions, run)
    assert (blocked.status, blocked.reason) == (RunStatus.BLOCKED_CONFIGURATION, "STAGE_CAPABILITY_INCOMPLETE")
    assert owner.provider_submit_count == 0


async def test_budget_is_reserved_before_dispatch(concurrent_session_factory):
    sessions = concurrent_session_factory
    run = await make_run(sessions)
    owner, host = harness(sessions)
    owner.cost = policy().max_cost_minor_units + 1

    await host.scan_once()
    blocked = await current(sessions, run)
    assert (blocked.status, blocked.reason) == (RunStatus.BLOCKED_BUDGET, "BUDGET_EXHAUSTED")
    assert owner.provider_submit_count == 0


async def test_finished_command_without_usage_receipt_cannot_advance(concurrent_session_factory):
    sessions = concurrent_session_factory
    run = await make_run(sessions)
    owner, host = harness(sessions)
    owner.usage_missing = True

    await host.scan_once()
    blocked = await current(sessions, run)
    assert (blocked.status, blocked.reason, blocked.stage) == (
        RunStatus.BLOCKED_UNKNOWN,
        "USAGE_UNKNOWN",
        RunStage.BRIEF,
    )


async def test_pause_during_dispatch_fences_the_controller_and_resume_replays(concurrent_session_factory):
    sessions = concurrent_session_factory
    run = await make_run(sessions)
    owner, host = harness(sessions)

    async def pause():
        async with sessions() as session, session.begin():
            repository = ProductionRunRepository(session)
            live = await repository.locked(scope_of(run))
            await repository.apply_command(
                expected=live,
                updated=live.model_copy(
                    update={
                        "status": RunStatus.PAUSED,
                        "version": live.version + 1,
                        "fencing_epoch": live.fencing_epoch + 1,
                    }
                ),
            )

    owner.during_dispatch = pause
    await host.scan_once()
    paused = await current(sessions, run)
    assert paused.status is RunStatus.PAUSED
    [step] = await steps(sessions, RunStage.BRIEF)
    assert step.receipt_json is None
    with pytest.raises(StaleProductionRunError):
        await host._controller.tick(run_id=run.run_id, owner_id="worker-1")
    assert await host.scan_once() == 0

    async with sessions() as session, session.begin():
        repository = ProductionRunRepository(session)
        live = await repository.locked(scope_of(run))
        await repository.apply_command(
            expected=live,
            updated=live.model_copy(
                update={
                    "status": RunStatus.RUNNING,
                    "version": live.version + 1,
                    "fencing_epoch": live.fencing_epoch + 1,
                }
            ),
        )
    await host.scan_once()
    assert owner.provider_submit_count == 1
    assert (await current(sessions, run)).stage is not RunStage.BRIEF


async def test_cancelled_run_is_never_claimed(concurrent_session_factory):
    sessions = concurrent_session_factory
    run = await make_run(sessions)
    async with sessions() as session, session.begin():
        repository = ProductionRunRepository(session)
        live = await repository.locked(scope_of(run))
        await repository.apply_command(
            expected=live,
            updated=live.model_copy(
                update={
                    "status": RunStatus.CANCELLED,
                    "version": live.version + 1,
                    "fencing_epoch": live.fencing_epoch + 1,
                }
            ),
        )
    owner, host = harness(sessions)

    assert await host.scan_once() == 0
    assert owner.provider_submit_count == 0


async def test_semi_checkpoint_waits_for_review_without_dispatch(concurrent_session_factory):
    from r2.contracts.automation import AutomationMode, Checkpoint

    sessions = concurrent_session_factory
    semi = RunPolicy.model_validate(
        {**policy().model_dump(), "mode": AutomationMode.SEMI, "checkpoints": frozenset({Checkpoint.STORY_MANUSCRIPT})}
    )
    run = await make_run(sessions, run_policy=semi)
    owner, host = harness(sessions)

    await host.scan_once()
    await host.scan_once()
    waiting = await current(sessions, run)
    assert waiting.status is RunStatus.WAITING_REVIEW
    assert waiting.pending_review is not None
    assert waiting.pending_review.checkpoint is Checkpoint.STORY_MANUSCRIPT
    submitted = owner.provider_submit_count
    assert await host.scan_once() == 0
    assert owner.provider_submit_count == submitted
