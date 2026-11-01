"""One leased step of a production run: intent first, reserve, dispatch or replay, inspect, settle, advance.

No database lock is held while an owner runs. Every write re-enters the repository's lease/fencing checks, so a
command, a newer controller or a lost lease turns a late write into ``StaleProductionRunError``.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.automation_grants import AutomationGrantRepository
from lib.db.repositories.production_runs import (
    ProductionBudgetExceeded,
    ProductionRunRepository,
    StaleProductionRunError,
)
from r2.automation.identity import derive_step_identity, policy_digest
from r2.automation.transitions import advance
from r2.contracts.automation import (
    AutomationOperation,
    BudgetReservation,
    DispatchIntent,
    OwnerReceipt,
    RunScope,
    RunSnapshot,
    RunStage,
    RunStatus,
    StageOutcome,
    UsageReceipt,
)
from server.production_run.owner_support import OwnerBlocked
from server.production_run.ports import InputWitness, OwnerAdapter, StepPlan

_ADVANCING = {RunStatus.RUNNING, RunStatus.WAITING_TASK}
_BLOCK_STATUS = {
    "EXTERNAL_INPUT_CHANGED": RunStatus.BLOCKED_INPUT_CHANGED,
    "OUTCOME_UNKNOWN": RunStatus.BLOCKED_UNKNOWN,
    "RESOURCE_UNAVAILABLE": RunStatus.BLOCKED_RESOURCE,
}


class ProductionController:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        adapters: Mapping[RunStage, OwnerAdapter],
        witness: InputWitness,
        poll_seconds: int = 5,
    ) -> None:
        self._sessions = sessions
        self._adapters = dict(adapters)
        self._witness = witness
        self._poll_seconds = poll_seconds

    async def tick(self, *, run_id: str, owner_id: str) -> RunSnapshot:
        async with self._sessions() as session, session.begin():
            run = await ProductionRunRepository(session).leased(run_id=run_id, owner_id=owner_id)
        if run.status not in _ADVANCING:
            raise StaleProductionRunError("STALE_PRODUCTION_RUN")
        if await self._witness.digest(user_id=run.user_id, project_name=run.project_name) != run.input_digest:
            return await self._block(run, RunStatus.BLOCKED_INPUT_CHANGED, "EXTERNAL_INPUT_CHANGED")
        if not await self._grant_current(run):
            return await self._block(run, RunStatus.BLOCKED_CONFIGURATION, "AUTOMATION_GRANT_NOT_CURRENT")
        adapter = self._adapters.get(run.stage)
        if adapter is None:
            return await self._block(run, RunStatus.BLOCKED_CONFIGURATION, "STAGE_CAPABILITY_INCOMPLETE")

        try:
            return await self._step(run, adapter)
        except OwnerBlocked as blocked:
            return await self._block(
                run, _BLOCK_STATUS.get(blocked.reason, RunStatus.BLOCKED_CONFIGURATION), blocked.reason
            )
        except PermissionError:
            return await self._block(run, RunStatus.BLOCKED_CONFIGURATION, "AUTOMATION_GRANT_NOT_CURRENT")

    async def _step(self, run: RunSnapshot, adapter: OwnerAdapter) -> RunSnapshot:
        async with self._sessions() as session, session.begin():
            step = await ProductionRunRepository(session).current_step(run=run)
        if step is None:
            intent, receipt = (
                self._intent(run, adapter.owner, StepPlan.model_validate(await adapter.plan(run=run))),
                None,
            )
        else:
            intent, receipt = step
        if intent.owner != adapter.owner:
            return await self._block(run, RunStatus.BLOCKED_CONFIGURATION, "STAGE_OWNER_MISMATCH")
        try:
            async with self._sessions() as session, session.begin():
                repository = ProductionRunRepository(session)
                await repository.stage_intent(run=run, intent=intent)
                reservation = await repository.reserve_budget(run=run, intent=intent)
        except ProductionBudgetExceeded:
            return await self._block(run, RunStatus.BLOCKED_BUDGET, "BUDGET_EXHAUSTED")

        if receipt is None:
            receipt = OwnerReceipt.model_validate(await adapter.dispatch(intent))
            async with self._sessions() as session, session.begin():
                await ProductionRunRepository(session).attach_receipt(
                    intent=intent, receipt=receipt, fencing_epoch=run.fencing_epoch
                )
        outcome = StageOutcome.model_validate(await adapter.inspect(intent=intent, receipt=receipt))
        if outcome.kind != "WAIT":
            outcome = await self._settle(adapter, receipt, reservation, outcome)
            async with self._sessions() as session, session.begin():
                current = await ProductionRunRepository(session).get(
                    user_id=run.user_id, project_name=run.project_name, run_id=run.run_id
                )
            if current != run:
                # Authoritative usage above the frozen caps has already blocked the run.
                raise StaleProductionRunError("STALE_PRODUCTION_RUN")
        updated = advance(run=run, outcome=outcome)
        delay = self._poll_seconds if updated.status is RunStatus.WAITING_TASK else 0
        async with self._sessions() as session, session.begin():
            return await ProductionRunRepository(session).transition(
                expected=run, updated=updated, fencing_epoch=run.fencing_epoch, due_in_seconds=delay
            )

    @staticmethod
    def _intent(run: RunSnapshot, owner: str, plan: StepPlan) -> DispatchIntent:
        repairs = {(r.stage, r.unit_key): r.count for r in run.repair_counts}
        return DispatchIntent(
            scope=RunScope(user_id=run.user_id, project_name=run.project_name, run_id=run.run_id),
            identity=derive_step_identity(
                run_id=run.run_id,
                stage=run.stage,
                unit_key=plan.unit_key,
                generation=run.generation,
                input_digest=run.input_digest,
                policy_digest=policy_digest(run.policy),
                repair_index=repairs.get((run.stage, plan.unit_key), 0),
            ),
            owner=owner,
            input_refs=plan.input_refs,
            estimated_cost_minor_units=plan.estimated_cost_minor_units,
            estimated_model_calls=plan.estimated_model_calls,
            estimated_tasks=plan.estimated_tasks,
            estimated_runtime_seconds=plan.estimated_runtime_seconds,
        )

    async def _settle(
        self,
        adapter: OwnerAdapter,
        receipt: OwnerReceipt,
        reservation: BudgetReservation,
        outcome: StageOutcome,
    ) -> StageOutcome:
        """Settle only from the owner's usage receipt; a finished command without one cannot advance."""
        usage = await adapter.usage(receipt=receipt, reservation=reservation)
        if usage is None:
            return self._blocked_outcome(outcome, "USAGE_UNKNOWN")
        usage = UsageReceipt.model_validate(usage)
        if usage.owner != receipt.owner:
            return self._blocked_outcome(outcome, "USAGE_UNKNOWN")
        async with self._sessions() as session, session.begin():
            await ProductionRunRepository(session).settle_budget(reservation=reservation, usage=usage)
        if usage.outcome == "UNKNOWN":
            return self._blocked_outcome(outcome, "OUTCOME_UNKNOWN")
        return outcome

    @staticmethod
    def _blocked_outcome(outcome: StageOutcome, reason: str) -> StageOutcome:
        return StageOutcome.model_validate(
            {**outcome.model_dump(mode="python"), "kind": "BLOCK", "reason": reason, "repair_stage": None}
        )

    async def _grant_current(self, run: RunSnapshot) -> bool:
        """Cheap pre-dispatch check; owners re-require the full locked authority at their final write."""
        scope = RunScope(user_id=run.user_id, project_name=run.project_name, run_id=run.run_id)
        try:
            async with self._sessions() as session, session.begin():
                grant = await AutomationGrantRepository(session).head(scope)
        except PermissionError:
            return False
        return (
            grant is not None
            and grant.state == "ACTIVE"
            and grant.issued_at <= datetime.now(UTC) < grant.expires_at
            and (grant.policy_digest, grant.input_digest) == (policy_digest(run.policy), run.input_digest)
            and AutomationOperation(run.stage.value) in grant.operations
        )

    async def _block(self, run: RunSnapshot, status: RunStatus, reason: str) -> RunSnapshot:
        updated = RunSnapshot.model_validate(
            {
                **run.model_dump(mode="python"),
                "version": run.version + 1,
                "status": status,
                "reason": reason,
                "pending_review": None,
            }
        )
        async with self._sessions() as session, session.begin():
            return await ProductionRunRepository(session).transition(
                expected=run, updated=updated, fencing_epoch=run.fencing_epoch
            )


__all__ = ["ProductionController"]
