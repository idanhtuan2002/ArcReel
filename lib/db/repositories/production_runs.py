"""Transaction-owned run persistence and fenced orchestration allocations."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import cast
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.production_run import (
    ProductionBudgetModel,
    ProductionPolicyModel,
    ProductionRunModel,
    ProductionStepModel,
    ProductionUsageModel,
)
from r2.automation.identity import derive_step_identity, digest_value, policy_digest
from r2.contracts.automation import (
    BudgetReservation,
    DispatchIntent,
    OwnerReceipt,
    RunCommand,
    RunPolicy,
    RunScope,
    RunSnapshot,
    RunStatus,
    UsageReceipt,
)
from r2.contracts.common import ensure_json_value

_TERMINAL = {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.FAILED_QUALITY, RunStatus.CANCELLED}
_CLAIMABLE = (RunStatus.PENDING.value, RunStatus.RUNNING.value, RunStatus.WAITING_TASK.value)


class ProductionRunConflict(RuntimeError):
    """A command or scope does not match its durable identity."""


class StaleProductionRunError(ProductionRunConflict):
    """An input version, lease or generation moved before the write."""


class ProductionBudgetExceeded(ProductionRunConflict):
    """The frozen run cap cannot accommodate a new allocation."""


def _wire_digest(domain: str, value: object) -> str:
    return digest_value(domain, ensure_json_value(value))


def _snapshot(row: ProductionRunModel) -> RunSnapshot:
    snapshot = RunSnapshot.model_validate_json(row.snapshot_json)
    if (
        (snapshot.user_id, snapshot.project_name, snapshot.run_id) != (row.user_id, row.project_name, row.run_id)
        or (snapshot.version, snapshot.generation, snapshot.fencing_epoch)
        != (row.version, row.generation, row.fencing_epoch)
        or (snapshot.status.value, snapshot.stage.value, snapshot.input_digest)
        != (row.status, row.stage, row.input_digest)
        or policy_digest(snapshot.policy) != row.policy_digest
    ):
        raise ProductionRunConflict("RUN_STATE_INTEGRITY_FAILED")
    return snapshot


def _write(row: ProductionRunModel, snapshot: RunSnapshot) -> None:
    snapshot = RunSnapshot.model_validate(snapshot)
    row.snapshot_json = snapshot.model_dump_json()
    row.status, row.stage = snapshot.status.value, snapshot.stage.value
    row.version, row.generation, row.fencing_epoch = snapshot.version, snapshot.generation, snapshot.fencing_epoch
    row.input_digest, row.policy_digest = snapshot.input_digest, policy_digest(snapshot.policy)


class ProductionRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _now(self) -> datetime:
        if self.session.get_bind().dialect.name != "postgresql":
            raise ProductionRunConflict("POSTGRESQL_REQUIRED")
        if not self.session.in_transaction():
            raise ProductionRunConflict("TRANSACTION_REQUIRED")
        return cast(datetime, await self.session.scalar(select(func.clock_timestamp())))

    async def _project_lock(self, user_id: str, project_name: str) -> None:
        key = digest_value("r2.production-project-lock.v1", {"user_id": user_id, "project_name": project_name})
        await self.session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})

    async def _locked(self, scope: RunScope) -> ProductionRunModel:
        row = (
            await self.session.execute(
                select(ProductionRunModel)
                .where(
                    ProductionRunModel.user_id == scope.user_id,
                    ProductionRunModel.project_name == scope.project_name,
                    ProductionRunModel.run_id == scope.run_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise ProductionRunConflict("RUN_NOT_FOUND")
        return row

    async def _live(self, run: RunSnapshot, epoch: int) -> ProductionRunModel:
        row = await self._locked(RunScope(user_id=run.user_id, project_name=run.project_name, run_id=run.run_id))
        now = await self._now()
        current = _snapshot(row)
        if (
            current != run
            or row.fencing_epoch != epoch
            or row.lease_owner is None
            or row.lease_until is None
            or row.lease_until <= now
            or current.status in _TERMINAL
        ):
            raise StaleProductionRunError("STALE_PRODUCTION_RUN")
        return row

    async def create(self, *, command: RunCommand, policy: RunPolicy) -> RunSnapshot:
        command, policy = RunCommand.model_validate(command), RunPolicy.model_validate(policy)
        now = await self._now()
        if command.action != "START":
            raise ProductionRunConflict("POLICY_MISMATCH")
        await self._project_lock(command.user_id, command.project_name)
        request_digest = _wire_digest("r2.production-start-command.v1", command.model_dump(mode="json"))
        # An identical Start returns its run even after a later mode change moved the run's policy.
        prior = await self.start_replay(command=command)
        if prior is not None:
            return prior
        if command.policy_digest != policy_digest(policy) or command.mode != policy.mode:
            raise ProductionRunConflict("POLICY_MISMATCH")
        active = await self.session.scalar(
            select(ProductionRunModel.run_id)
            .where(
                ProductionRunModel.user_id == command.user_id,
                ProductionRunModel.project_name == command.project_name,
                ProductionRunModel.status.not_in([s.value for s in _TERMINAL]),
            )
            .limit(1)
        )
        if active is not None:
            raise ProductionRunConflict("PROJECT_RUN_ACTIVE")
        run_id = str(
            uuid5(
                NAMESPACE_URL,
                _wire_digest(
                    "r2.production-run-identity.v1",
                    {
                        "user_id": command.user_id,
                        "project_name": command.project_name,
                        "command_id": command.command_id,
                    },
                ),
            )
        )
        snapshot = RunSnapshot(
            user_id=command.user_id,
            project_name=command.project_name,
            run_id=run_id,
            policy=policy,
            input_digest=command.expected_input_digest,
            targets=command.targets,
            created_at=now,
        )
        self.session.add(
            ProductionPolicyModel(
                user_id=command.user_id,
                project_name=command.project_name,
                run_id=run_id,
                policy_digest=policy_digest(policy),
                policy_json=policy.model_dump_json(),
                created_at=now,
            )
        )
        await self.session.flush()
        self.session.add(
            ProductionRunModel(
                run_id=run_id,
                user_id=command.user_id,
                project_name=command.project_name,
                policy_digest=policy_digest(policy),
                input_digest=snapshot.input_digest,
                start_command_id=command.command_id,
                start_command_digest=request_digest,
                start_command_json=command.model_dump_json(),
                snapshot_json=snapshot.model_dump_json(),
                status=snapshot.status.value,
                stage=snapshot.stage.value,
                version=1,
                generation=1,
                fencing_epoch=0,
                lease_owner=None,
                lease_until=None,
                due_at=now,
                created_at=now,
            )
        )
        await self.session.flush()
        return snapshot

    async def start_replay(self, *, command: RunCommand) -> RunSnapshot | None:
        """The run an identical Start already created; a changed command under the same ID conflicts."""
        command = RunCommand.model_validate(command)
        prior = (
            await self.session.execute(
                select(ProductionRunModel).where(
                    ProductionRunModel.user_id == command.user_id,
                    ProductionRunModel.project_name == command.project_name,
                    ProductionRunModel.start_command_id == command.command_id,
                )
            )
        ).scalar_one_or_none()
        if prior is None:
            return None
        if prior.start_command_digest != _wire_digest(
            "r2.production-start-command.v1", command.model_dump(mode="json")
        ):
            raise ProductionRunConflict("COMMAND_REPLAY_CONFLICT")
        return _snapshot(prior)

    async def get(self, *, user_id: str, project_name: str, run_id: str) -> RunSnapshot | None:
        row = (
            await self.session.execute(
                select(ProductionRunModel).where(
                    ProductionRunModel.user_id == user_id,
                    ProductionRunModel.project_name == project_name,
                    ProductionRunModel.run_id == run_id,
                )
            )
        ).scalar_one_or_none()
        return _snapshot(row) if row is not None else None

    async def list_for_project(self, *, user_id: str, project_name: str) -> list[RunSnapshot]:
        rows = (
            await self.session.execute(
                select(ProductionRunModel)
                .where(ProductionRunModel.user_id == user_id, ProductionRunModel.project_name == project_name)
                .order_by(ProductionRunModel.created_at.desc(), ProductionRunModel.run_id)
            )
        ).scalars()
        return [_snapshot(row) for row in rows]

    async def locked(self, scope: RunScope) -> RunSnapshot:
        """The current run under its row lock, for commands applied in the caller's transaction."""
        await self._now()
        return _snapshot(await self._locked(RunScope.model_validate(scope)))

    async def leased(self, *, run_id: str, owner_id: str) -> RunSnapshot:
        """The run only while ``owner_id`` holds its unexpired controller lease."""
        now = await self._now()
        row = (
            await self.session.execute(
                select(ProductionRunModel).where(ProductionRunModel.run_id == run_id).with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise ProductionRunConflict("RUN_NOT_FOUND")
        if row.lease_owner != owner_id or row.lease_until is None or row.lease_until <= now:
            raise StaleProductionRunError("STALE_PRODUCTION_RUN")
        snapshot = _snapshot(row)
        if snapshot.status in _TERMINAL:
            raise StaleProductionRunError("STALE_PRODUCTION_RUN")
        return snapshot

    async def current_step(self, *, run: RunSnapshot) -> tuple[DispatchIntent, OwnerReceipt | None] | None:
        """The staged command of the run's current stage, generation, input and policy, if any."""
        run = RunSnapshot.model_validate(run)
        rows = list(
            (
                await self.session.execute(
                    select(ProductionStepModel)
                    .where(
                        ProductionStepModel.user_id == run.user_id,
                        ProductionStepModel.project_name == run.project_name,
                        ProductionStepModel.run_id == run.run_id,
                        ProductionStepModel.stage == run.stage.value,
                        ProductionStepModel.generation == run.generation,
                        ProductionStepModel.input_digest == run.input_digest,
                        ProductionStepModel.policy_digest == policy_digest(run.policy),
                    )
                    .execution_options(populate_existing=True)
                )
            ).scalars()
        )
        if not rows:
            return None
        if len(rows) > 1:
            raise ProductionRunConflict("AMBIGUOUS_CURRENT_STEP")
        [row] = rows
        intent = DispatchIntent.model_validate_json(row.intent_json)
        if row.intent_digest != _wire_digest("r2.production-intent.v1", intent.model_dump(mode="json")):
            raise ProductionRunConflict("RUN_STATE_INTEGRITY_FAILED")
        receipt = OwnerReceipt.model_validate_json(row.receipt_json) if row.receipt_json is not None else None
        return intent, receipt

    async def apply_command(
        self, *, expected: RunSnapshot, updated: RunSnapshot, policy: RunPolicy | None = None
    ) -> RunSnapshot:
        """Write a user command result; it fences any controller lease and makes the run due now."""
        expected, updated = RunSnapshot.model_validate(expected), RunSnapshot.model_validate(updated)
        row = await self._locked(
            RunScope(user_id=expected.user_id, project_name=expected.project_name, run_id=expected.run_id)
        )
        now = await self._now()
        if _snapshot(row) != expected:
            raise StaleProductionRunError("STALE_PRODUCTION_RUN")
        if (
            (updated.user_id, updated.project_name, updated.run_id, updated.created_at)
            != (expected.user_id, expected.project_name, expected.run_id, expected.created_at)
            or updated.version != expected.version + 1
            or updated.fencing_epoch != expected.fencing_epoch + 1
            or updated.generation < expected.generation
            or expected.status in _TERMINAL
            or (updated.policy != expected.policy and (policy is None or updated.policy != policy))
        ):
            raise ProductionRunConflict("INVALID_RUN_COMMAND")
        if updated.policy != expected.policy:
            digest = policy_digest(updated.policy)
            stored = await self.session.get(
                ProductionPolicyModel, (updated.user_id, updated.project_name, updated.run_id, digest)
            )
            if stored is None:
                self.session.add(
                    ProductionPolicyModel(
                        user_id=updated.user_id,
                        project_name=updated.project_name,
                        run_id=updated.run_id,
                        policy_digest=digest,
                        policy_json=updated.policy.model_dump_json(),
                        created_at=now,
                    )
                )
                await self.session.flush()
            elif RunPolicy.model_validate_json(stored.policy_json) != updated.policy:
                raise ProductionRunConflict("RUN_STATE_INTEGRITY_FAILED")
        _write(row, updated)
        row.lease_owner, row.lease_until, row.due_at = None, None, now
        await self.session.flush()
        return updated

    async def claim_due(self, *, owner_id: str, lease_seconds: int) -> RunSnapshot | None:
        now = await self._now()
        if not owner_id or not owner_id.strip() == owner_id or not 1 <= lease_seconds <= 300:
            raise ValueError("invalid controller lease")
        row = (
            await self.session.execute(
                select(ProductionRunModel)
                .where(
                    ProductionRunModel.status.in_(_CLAIMABLE),
                    ProductionRunModel.due_at <= now,
                    or_(ProductionRunModel.lease_until.is_(None), ProductionRunModel.lease_until <= now),
                )
                .order_by(ProductionRunModel.due_at, ProductionRunModel.run_id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        current = _snapshot(row)
        updated = RunSnapshot.model_validate(
            {
                **current.model_dump(mode="python"),
                "version": current.version + 1,
                "fencing_epoch": current.fencing_epoch + 1,
                "status": RunStatus.RUNNING if current.status is RunStatus.PENDING else current.status,
            }
        )
        row.lease_owner, row.lease_until = owner_id, now + timedelta(seconds=lease_seconds)
        _write(row, updated)
        await self.session.flush()
        return updated

    async def transition(
        self, *, expected: RunSnapshot, updated: RunSnapshot, fencing_epoch: int, due_in_seconds: int = 0
    ) -> RunSnapshot:
        expected, updated = RunSnapshot.model_validate(expected), RunSnapshot.model_validate(updated)
        row = await self._live(expected, fencing_epoch)
        if (
            (updated.user_id, updated.project_name, updated.run_id)
            != (expected.user_id, expected.project_name, expected.run_id)
            or updated.version != expected.version + 1
            or updated.fencing_epoch != fencing_epoch
            or updated.policy != expected.policy
            or updated.input_digest != expected.input_digest
            or updated.generation < expected.generation
        ):
            raise ProductionRunConflict("INVALID_RUN_TRANSITION")
        if not 0 <= due_in_seconds <= 3600:
            raise ValueError("invalid controller poll delay")
        _write(row, updated)
        row.lease_owner, row.lease_until = None, None
        row.due_at = await self._now() + timedelta(seconds=due_in_seconds)
        await self.session.flush()
        return updated

    async def stage_intent(self, *, run: RunSnapshot, intent: DispatchIntent) -> DispatchIntent:
        intent = DispatchIntent.model_validate(intent)
        if intent.scope != RunScope(user_id=run.user_id, project_name=run.project_name, run_id=run.run_id):
            raise ProductionRunConflict("SCOPE_MISMATCH")
        await self._live(run, run.fencing_epoch)
        identity = intent.identity
        rebuilt = derive_step_identity(**identity.model_dump(exclude={"command_id", "task_id"}))
        if rebuilt != identity or (identity.generation, identity.policy_digest, identity.stage) != (
            run.generation,
            policy_digest(run.policy),
            run.stage,
        ):
            raise ProductionRunConflict("INVALID_STEP_IDENTITY")
        digest = _wire_digest("r2.production-intent.v1", intent.model_dump(mode="json"))
        prior = await self.session.get(ProductionStepModel, identity.command_id)
        if prior is not None:
            if prior.intent_digest != digest or DispatchIntent.model_validate_json(prior.intent_json) != intent:
                raise ProductionRunConflict("COMMAND_REPLAY_CONFLICT")
            return intent
        self.session.add(
            ProductionStepModel(
                command_id=identity.command_id,
                user_id=run.user_id,
                project_name=run.project_name,
                run_id=run.run_id,
                stage=identity.stage.value,
                unit_key=identity.unit_key,
                generation=identity.generation,
                repair_index=identity.repair_index,
                input_digest=identity.input_digest,
                policy_digest=identity.policy_digest,
                intent_digest=digest,
                intent_json=intent.model_dump_json(),
                receipt_json=None,
            )
        )
        await self.session.flush()
        return intent

    async def attach_receipt(self, *, intent: DispatchIntent, receipt: OwnerReceipt, fencing_epoch: int) -> None:
        intent, receipt = DispatchIntent.model_validate(intent), OwnerReceipt.model_validate(receipt)
        run = await self._locked(intent.scope)
        now = await self._now()
        current = _snapshot(run)
        if (
            current.fencing_epoch != fencing_epoch
            or run.lease_owner is None
            or run.lease_until is None
            or run.lease_until <= now
            or intent.identity.generation != current.generation
            or intent.identity.policy_digest != policy_digest(current.policy)
            or current.status in _TERMINAL
        ):
            raise StaleProductionRunError("STALE_PRODUCTION_RUN")
        row = await self.session.get(ProductionStepModel, intent.identity.command_id)
        if row is None or DispatchIntent.model_validate_json(row.intent_json) != intent:
            raise ProductionRunConflict("INTENT_NOT_FOUND")
        if receipt.owner != intent.owner:
            raise ProductionRunConflict("SCOPE_MISMATCH")
        if row.receipt_json is not None:
            if OwnerReceipt.model_validate_json(row.receipt_json) != receipt:
                raise ProductionRunConflict("COMMAND_REPLAY_CONFLICT")
            return
        row.receipt_json = receipt.model_dump_json()
        await self.session.flush()

    async def _totals(self, scope: RunScope) -> tuple[int, int, int, int]:
        values = (
            await self.session.execute(
                select(
                    func.coalesce(func.sum(ProductionBudgetModel.held_cost), 0),
                    func.coalesce(func.sum(ProductionBudgetModel.held_calls), 0),
                    func.coalesce(func.sum(ProductionBudgetModel.held_tasks), 0),
                    func.coalesce(func.sum(ProductionBudgetModel.held_runtime), 0),
                ).where(
                    ProductionBudgetModel.user_id == scope.user_id,
                    ProductionBudgetModel.project_name == scope.project_name,
                    ProductionBudgetModel.run_id == scope.run_id,
                )
            )
        ).one()
        return int(values[0]), int(values[1]), int(values[2]), int(values[3])

    async def reserve_budget(self, *, run: RunSnapshot, intent: DispatchIntent) -> BudgetReservation:
        await self._live(run, run.fencing_epoch)
        intent = DispatchIntent.model_validate(intent)
        row = await self.session.get(ProductionStepModel, intent.identity.command_id)
        if (
            row is None
            or DispatchIntent.model_validate_json(row.intent_json) != intent
            or intent.scope
            != RunScope(
                user_id=run.user_id,
                project_name=run.project_name,
                run_id=run.run_id,
            )
        ):
            raise ProductionRunConflict("INTENT_NOT_FOUND")
        reservation_id = "allocation-" + intent.identity.task_id
        prior = await self.session.get(ProductionBudgetModel, reservation_id)
        if prior is not None:
            stored = BudgetReservation.model_validate_json(prior.reservation_json)
            return stored.model_copy(update={"state": prior.state})
        totals = await self._totals(intent.scope)
        request = (
            intent.estimated_cost_minor_units,
            intent.estimated_model_calls,
            intent.estimated_tasks,
            intent.estimated_runtime_seconds,
        )
        caps = (
            run.policy.max_cost_minor_units,
            run.policy.max_model_calls,
            run.policy.max_tasks,
            run.policy.max_runtime_seconds,
        )
        if any(used + allocated > cap for used, allocated, cap in zip(totals, request, caps, strict=True)):
            raise ProductionBudgetExceeded("RUN_BUDGET_EXCEEDED")
        reservation = BudgetReservation(
            scope=intent.scope,
            reservation_id=reservation_id,
            command_id=intent.identity.command_id,
            policy_digest=intent.identity.policy_digest,
            currency=run.policy.currency,
            cost_minor_units=request[0],
            model_calls=request[1],
            tasks=request[2],
            runtime_seconds=request[3],
            state="RESERVED",
        )
        self.session.add(
            ProductionBudgetModel(
                reservation_id=reservation_id,
                user_id=run.user_id,
                project_name=run.project_name,
                run_id=run.run_id,
                command_id=reservation.command_id,
                reservation_json=reservation.model_dump_json(),
                state="RESERVED",
                held_cost=request[0],
                held_calls=request[1],
                held_tasks=request[2],
                held_runtime=request[3],
                settled_usage_digest=None,
            )
        )
        await self.session.flush()
        return reservation

    async def settle_budget(self, *, reservation: BudgetReservation, usage: UsageReceipt) -> None:
        reservation, usage = BudgetReservation.model_validate(reservation), UsageReceipt.model_validate(usage)
        await self._now()
        run_row = await self._locked(reservation.scope)
        row = await self.session.get(ProductionBudgetModel, reservation.reservation_id)
        if row is None:
            raise ProductionRunConflict("ALLOCATION_NOT_FOUND")
        original = BudgetReservation.model_validate_json(row.reservation_json)
        if reservation.model_dump(exclude={"state"}) != original.model_dump(exclude={"state"}) or (
            usage.reservation_id != reservation.reservation_id or usage.currency != reservation.currency
        ):
            raise ProductionRunConflict("SCOPE_MISMATCH")
        digest = _wire_digest("r2.production-usage-reference.v1", usage.model_dump(mode="json"))
        key = (reservation.scope.user_id, reservation.scope.project_name, usage.owner, usage.receipt_ref)
        prior = await self.session.get(ProductionUsageModel, key)
        if prior is not None:
            if prior.usage_digest != digest or prior.reservation_id != row.reservation_id:
                raise ProductionRunConflict("COMMAND_REPLAY_CONFLICT")
            return
        if row.state == "SETTLED":
            raise ProductionRunConflict("ALLOCATION_ALREADY_SETTLED")
        self.session.add(
            ProductionUsageModel(
                user_id=key[0],
                project_name=key[1],
                owner=key[2],
                receipt_ref=key[3],
                run_id=reservation.scope.run_id,
                reservation_id=reservation.reservation_id,
                usage_digest=digest,
                usage_json=usage.model_dump_json(),
            )
        )
        if usage.outcome == "UNKNOWN":
            row.state = "UNKNOWN"
        else:
            row.state, row.settled_usage_digest = "SETTLED", digest
            row.held_cost, row.held_calls = usage.cost_minor_units, usage.model_calls
            row.held_tasks, row.held_runtime = usage.tasks, usage.runtime_seconds
        await self.session.flush()
        snapshot = _snapshot(run_row)
        caps = (
            snapshot.policy.max_cost_minor_units,
            snapshot.policy.max_model_calls,
            snapshot.policy.max_tasks,
            snapshot.policy.max_runtime_seconds,
        )
        totals = await self._totals(reservation.scope)
        if any(used > cap for used, cap in zip(totals, caps, strict=True)):
            status = snapshot.status if snapshot.status in _TERMINAL else RunStatus.BLOCKED_BUDGET
            if status is RunStatus.SUCCEEDED:
                status = RunStatus.FAILED
            blocked = RunSnapshot.model_validate(
                {
                    **snapshot.model_dump(mode="python"),
                    "version": snapshot.version + 1,
                    "status": status,
                    "pending_review": None,
                    "reason": "AUTHORITATIVE_USAGE_EXCEEDED_CAP",
                }
            )
            _write(run_row, blocked)
            run_row.lease_owner, run_row.lease_until = None, None
            await self.session.flush()
