"""Production run persistence and interleavings on real PostgreSQL."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa


def policy():
    from r2.contracts.automation import RunPolicy

    return RunPolicy(
        profile_id="fiction_narration_vi_v1",
        profile_digest="sha256:" + "a" * 64,
        currency="USD",
        max_cost_minor_units=100,
        max_model_calls=10,
        max_tasks=10,
        max_runtime_seconds=600,
        route_digests=("sha256:" + "b" * 64,),
    )


def command(**changes):
    from r2.automation.identity import policy_digest
    from r2.contracts.automation import RunCommand

    return RunCommand.model_validate(
        {
            "user_id": "u1",
            "project_name": "film",
            "command_id": "start-1",
            "action": "START",
            "expected_version": 0,
            "expected_input_digest": "sha256:" + "c" * 64,
            "policy_digest": policy_digest(policy()),
            "idea": "Một chuyến đò cuối cùng.",
            **changes,
        }
    )


async def create_run(factory, **changes):
    from lib.db.repositories.production_runs import ProductionRunRepository

    async with factory() as session, session.begin():
        assert session.get_bind().dialect.name == "postgresql"
        return await ProductionRunRepository(session).create(command=command(**changes), policy=policy())


async def claim(factory, owner="worker-1"):
    from lib.db.repositories.production_runs import ProductionRunRepository

    async with factory() as session, session.begin():
        return await ProductionRunRepository(session).claim_due(owner_id=owner, lease_seconds=30)


def intent_for(run, unit="project", cost=60):
    from r2.automation.identity import derive_step_identity, policy_digest
    from r2.contracts.automation import DispatchIntent, RunScope

    return DispatchIntent(
        scope=RunScope(user_id=run.user_id, project_name=run.project_name, run_id=run.run_id),
        identity=derive_step_identity(
            run_id=run.run_id,
            stage=run.stage,
            unit_key=unit,
            generation=run.generation,
            input_digest=run.input_digest,
            policy_digest=policy_digest(run.policy),
            repair_index=0,
        ),
        owner="story",
        estimated_cost_minor_units=cost,
        estimated_model_calls=1,
        estimated_tasks=1,
        estimated_runtime_seconds=30,
    )


async def test_start_command_replay_returns_same_run(concurrent_session_factory):
    from lib.db.models.production_run import ProductionRunModel

    factory = concurrent_session_factory
    first = await create_run(factory)
    replay = await create_run(factory)
    assert first.run_id == replay.run_id
    async with factory() as session:
        assert await session.scalar(sa.select(sa.func.count()).select_from(ProductionRunModel)) == 1


async def test_concurrent_start_cannot_duplicate_run(concurrent_session_factory):
    factory = concurrent_session_factory
    results = await asyncio.gather(create_run(factory), create_run(factory))
    assert results[0].run_id == results[1].run_id


async def test_replayed_command_cannot_change_idea(concurrent_session_factory):
    from lib.db.repositories.production_runs import ProductionRunConflict

    await create_run(concurrent_session_factory)
    with pytest.raises(ProductionRunConflict, match="COMMAND_REPLAY_CONFLICT"):
        await create_run(concurrent_session_factory, idea="Một câu chuyện khác.")


async def test_two_active_runs_cannot_write_same_project(concurrent_session_factory):
    from lib.db.repositories.production_runs import ProductionRunConflict

    await create_run(concurrent_session_factory)
    with pytest.raises(ProductionRunConflict, match="PROJECT_RUN_ACTIVE"):
        await create_run(concurrent_session_factory, command_id="start-2")


async def test_repository_does_not_commit_callers_transaction(concurrent_session_factory):
    from lib.db.models.production_run import ProductionRunModel
    from lib.db.repositories.production_runs import ProductionRunRepository

    factory = concurrent_session_factory

    async def abort_transaction():
        async with factory() as session, session.begin():
            await ProductionRunRepository(session).create(command=command(), policy=policy())
            raise RuntimeError("caller abort")

    with pytest.raises(RuntimeError, match="caller abort"):
        await abort_transaction()
    async with factory() as session:
        assert await session.scalar(sa.select(sa.func.count()).select_from(ProductionRunModel)) == 0


async def test_run_read_is_scoped_to_user_and_project(concurrent_session_factory):
    from lib.db.repositories.production_runs import ProductionRunRepository

    factory = concurrent_session_factory
    run = await create_run(factory)
    async with factory() as session:
        repo = ProductionRunRepository(session)
        assert await repo.get(user_id="u2", project_name="film", run_id=run.run_id) is None
        assert await repo.get(user_id="u1", project_name="other", run_id=run.run_id) is None
        assert await repo.get(user_id="u1", project_name="film", run_id=run.run_id) == run


async def test_only_one_controller_claims_live_lease(concurrent_session_factory):
    factory = concurrent_session_factory
    await create_run(factory)
    results = await asyncio.gather(claim(factory, "a"), claim(factory, "b"))
    assert sum(result is not None for result in results) == 1


async def test_expired_controller_cannot_transition_after_takeover(concurrent_session_factory):
    from lib.db.models.production_run import ProductionRunModel
    from lib.db.repositories.production_runs import ProductionRunRepository, StaleProductionRunError
    from r2.automation.identity import policy_digest
    from r2.automation.transitions import advance
    from r2.contracts.automation import StageOutcome

    factory = concurrent_session_factory
    await create_run(factory)
    first = await claim(factory, "a")
    async with factory() as session, session.begin():
        await session.execute(
            sa.update(ProductionRunModel)
            .where(ProductionRunModel.run_id == first.run_id)
            .values(lease_until=datetime(2000, 1, 1, tzinfo=UTC))
        )
    second = await claim(factory, "b")
    assert second.fencing_epoch > first.fencing_epoch
    updated = advance(
        run=first,
        outcome=StageOutcome(
            stage=first.stage,
            generation=first.generation,
            input_digest=first.input_digest,
            policy_digest=policy_digest(first.policy),
            kind="WAIT",
        ),
    )
    with pytest.raises(StaleProductionRunError):
        async with factory() as session, session.begin():
            await ProductionRunRepository(session).transition(
                expected=first, updated=updated, fencing_epoch=first.fencing_epoch
            )


async def test_intent_replay_rejects_changed_dispatch_parameters(concurrent_session_factory):
    from lib.db.repositories.production_runs import ProductionRunConflict, ProductionRunRepository

    factory = concurrent_session_factory
    await create_run(factory)
    run = await claim(factory)
    intent = intent_for(run)
    async with factory() as session, session.begin():
        repo = ProductionRunRepository(session)
        assert await repo.stage_intent(run=run, intent=intent) == intent
    with pytest.raises(ProductionRunConflict, match="COMMAND_REPLAY_CONFLICT"):
        async with factory() as session, session.begin():
            await ProductionRunRepository(session).stage_intent(run=run, intent=intent_for(run, cost=59))


async def test_intent_scope_cannot_be_attached_to_another_user(concurrent_session_factory):
    from lib.db.repositories.production_runs import ProductionRunConflict, ProductionRunRepository

    factory = concurrent_session_factory
    await create_run(factory)
    run = await claim(factory)
    intent = intent_for(run)
    bad = intent.model_copy(update={"scope": intent.scope.model_copy(update={"user_id": "other"})})
    with pytest.raises(ProductionRunConflict, match="SCOPE_MISMATCH"):
        async with factory() as session, session.begin():
            await ProductionRunRepository(session).stage_intent(run=run, intent=bad)


async def test_receipt_link_is_idempotent_but_cannot_be_substituted(concurrent_session_factory):
    from lib.db.repositories.production_runs import ProductionRunConflict, ProductionRunRepository
    from r2.contracts.automation import OwnerReceipt

    factory = concurrent_session_factory
    await create_run(factory)
    run = await claim(factory)
    intent = intent_for(run)
    receipt = OwnerReceipt(owner="story", receipt_ref="receipt-1", digest="sha256:" + "d" * 64)
    async with factory() as session, session.begin():
        repo = ProductionRunRepository(session)
        await repo.stage_intent(run=run, intent=intent)
        await repo.attach_receipt(intent=intent, receipt=receipt, fencing_epoch=run.fencing_epoch)
        await repo.attach_receipt(intent=intent, receipt=receipt, fencing_epoch=run.fencing_epoch)
    with pytest.raises(ProductionRunConflict, match="COMMAND_REPLAY_CONFLICT"):
        async with factory() as session, session.begin():
            await ProductionRunRepository(session).attach_receipt(
                intent=intent,
                receipt=receipt.model_copy(update={"digest": "sha256:" + "e" * 64}),
                fencing_epoch=run.fencing_epoch,
            )


async def test_concurrent_run_caps_cannot_overreserve(concurrent_session_factory):
    from lib.db.repositories.production_runs import ProductionBudgetExceeded, ProductionRunRepository

    factory = concurrent_session_factory
    await create_run(factory)
    run = await claim(factory)
    intents = [intent_for(run, "first"), intent_for(run, "second")]
    async with factory() as session, session.begin():
        repo = ProductionRunRepository(session)
        for intent in intents:
            await repo.stage_intent(run=run, intent=intent)

    async def reserve(intent):
        try:
            async with factory() as session, session.begin():
                return await ProductionRunRepository(session).reserve_budget(run=run, intent=intent)
        except ProductionBudgetExceeded:
            return None

    results = await asyncio.gather(*(reserve(intent) for intent in intents))
    assert sum(result is not None for result in results) == 1


async def test_unknown_usage_does_not_release_run_allocation(concurrent_session_factory):
    from lib.db.repositories.production_runs import ProductionBudgetExceeded, ProductionRunRepository
    from r2.contracts.automation import UsageReceipt

    factory = concurrent_session_factory
    await create_run(factory)
    run = await claim(factory)
    first, second = intent_for(run, "first"), intent_for(run, "second")
    async with factory() as session, session.begin():
        repo = ProductionRunRepository(session)
        await repo.stage_intent(run=run, intent=first)
        await repo.stage_intent(run=run, intent=second)
        reservation = await repo.reserve_budget(run=run, intent=first)
        unknown = UsageReceipt(
            owner="story",
            receipt_ref="usage-1",
            digest="sha256:" + "d" * 64,
            reservation_id=reservation.reservation_id,
            currency="USD",
            cost_minor_units=0,
            model_calls=0,
            tasks=0,
            runtime_seconds=0,
            outcome="UNKNOWN",
        )
        await repo.settle_budget(reservation=reservation, usage=unknown)
    with pytest.raises(ProductionBudgetExceeded):
        async with factory() as session, session.begin():
            await ProductionRunRepository(session).reserve_budget(run=run, intent=second)


async def test_usage_replay_cannot_double_debit_run(concurrent_session_factory):
    from lib.db.repositories.production_runs import ProductionRunRepository
    from r2.contracts.automation import UsageReceipt

    factory = concurrent_session_factory
    await create_run(factory)
    run = await claim(factory)
    first, second = intent_for(run, "first"), intent_for(run, "second")
    async with factory() as session, session.begin():
        repo = ProductionRunRepository(session)
        await repo.stage_intent(run=run, intent=first)
        await repo.stage_intent(run=run, intent=second)
        reservation = await repo.reserve_budget(run=run, intent=first)
        usage = UsageReceipt(
            owner="story",
            receipt_ref="usage-1",
            digest="sha256:" + "d" * 64,
            reservation_id=reservation.reservation_id,
            currency="USD",
            cost_minor_units=30,
            model_calls=1,
            tasks=1,
            runtime_seconds=10,
            outcome="KNOWN",
        )
        await repo.settle_budget(reservation=reservation, usage=usage)
        await repo.settle_budget(reservation=reservation, usage=usage)
        result = await repo.reserve_budget(run=run, intent=second)
        assert result.cost_minor_units == 60


async def test_late_usage_preserves_cancelled_run_and_new_active_run(concurrent_session_factory):
    from lib.db.models.production_run import ProductionUsageModel
    from lib.db.repositories.production_runs import ProductionRunRepository
    from r2.contracts.automation import RunSnapshot, RunStatus, UsageReceipt

    factory = concurrent_session_factory
    await create_run(factory)
    run = await claim(factory)
    intent = intent_for(run)
    async with factory() as session, session.begin():
        repo = ProductionRunRepository(session)
        await repo.stage_intent(run=run, intent=intent)
        reservation = await repo.reserve_budget(run=run, intent=intent)
        cancelled = RunSnapshot.model_validate(
            {**run.model_dump(mode="python"), "version": run.version + 1, "status": "CANCELLED"}
        )
        await repo.transition(expected=run, updated=cancelled, fencing_epoch=run.fencing_epoch)
    new_run = await create_run(factory, command_id="start-2")
    usage = UsageReceipt(
        owner="story",
        receipt_ref="late-usage",
        digest="sha256:" + "e" * 64,
        reservation_id=reservation.reservation_id,
        currency="USD",
        cost_minor_units=150,
        model_calls=1,
        tasks=1,
        runtime_seconds=30,
        outcome="KNOWN",
    )
    async with factory() as session, session.begin():
        repo = ProductionRunRepository(session)
        await repo.settle_budget(reservation=reservation, usage=usage)
        old = await repo.get(user_id="u1", project_name="film", run_id=run.run_id)
        current = await repo.get(user_id="u1", project_name="film", run_id=new_run.run_id)
        assert old.status is RunStatus.CANCELLED
        assert old.reason == "AUTHORITATIVE_USAGE_EXCEEDED_CAP"
        assert current.status is RunStatus.PENDING
        assert await session.scalar(sa.select(sa.func.count()).select_from(ProductionUsageModel)) == 1


async def test_lease_expiring_during_row_lock_wait_cannot_stage_intent(concurrent_session_factory):
    from lib.db.models.production_run import ProductionRunModel
    from lib.db.repositories.production_runs import ProductionRunRepository, StaleProductionRunError

    factory = concurrent_session_factory
    await create_run(factory)
    run = await claim(factory)
    attempted = asyncio.Event()

    async def stage():
        async with factory() as session, session.begin():
            attempted.set()
            return await ProductionRunRepository(session).stage_intent(run=run, intent=intent_for(run))

    async with factory() as blocker, blocker.begin():
        await blocker.execute(
            sa.select(ProductionRunModel).where(ProductionRunModel.run_id == run.run_id).with_for_update()
        )
        task = asyncio.create_task(stage())
        await attempted.wait()
        # The blocked transaction has started its lease check before this expiry.
        await blocker.execute(sa.text("SELECT pg_sleep(0.2)"))
        await blocker.execute(
            sa.update(ProductionRunModel)
            .where(ProductionRunModel.run_id == run.run_id)
            .values(lease_until=sa.func.clock_timestamp())
        )
    with pytest.raises(StaleProductionRunError):
        await task
