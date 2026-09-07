"""Host orchestration for C04 budget authorization.

Delegates every durable mutation to ``BudgetReservationRepository`` and reads
actual-cost evidence from the existing ``UsageRepository``. This service owns no
budget storage, no cost ledger, and no queue state.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.budget_reservation import (
    BudgetReservationIntegrityError,
    BudgetReservationSnapshot,
)
from lib.db.repositories.budget_reservation_repo import BudgetReservationRepository
from lib.db.repositories.usage_repo import UsageRepository

_API_CALL_PREFIX = "api_call:"


@dataclass(frozen=True)
class HostCostEvidence:
    cost_record_ref: str
    cost_amount: Decimal
    currency: str
    task_id: str | None


def _parse_api_call_ref(cost_record_ref: str) -> int:
    if not cost_record_ref.startswith(_API_CALL_PREFIX):
        raise BudgetReservationIntegrityError(f"unsupported cost record reference: {cost_record_ref}")
    raw = cost_record_ref[len(_API_CALL_PREFIX) :]
    try:
        call_id = int(raw)
    except ValueError as exc:
        raise BudgetReservationIntegrityError(f"malformed cost record reference: {cost_record_ref}") from exc
    if call_id <= 0:
        raise BudgetReservationIntegrityError(f"malformed cost record reference: {cost_record_ref}")
    return call_id


def _decimal_cost(value: object, *, cost_record_ref: str) -> Decimal:
    if value is None:
        raise BudgetReservationIntegrityError(f"cost record {cost_record_ref} has no persisted cost amount")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise BudgetReservationIntegrityError(f"cost record {cost_record_ref} has a non-numeric cost amount") from exc
    if not amount.is_finite() or amount < 0:
        raise BudgetReservationIntegrityError(f"cost record {cost_record_ref} has an invalid cost amount")
    return amount


class BudgetReservationService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def reserve_for_execution(
        self,
        *,
        budget_scope_ref: str,
        reservation_ref: str,
        execution_decision_ref: str,
        amount: Decimal,
        expires_at: datetime | None,
        provenance: Mapping[str, object],
        now: datetime,
    ) -> BudgetReservationSnapshot:
        async with self._session_factory() as session:
            result = await BudgetReservationRepository(session).reserve(
                budget_scope_ref=budget_scope_ref,
                reservation_ref=reservation_ref,
                execution_decision_ref=execution_decision_ref,
                requested_amount=amount,
                expires_at=expires_at,
                provenance_json=dict(provenance),
                now=now,
            )
        return result.reservation

    async def claim_for_submission(
        self,
        *,
        reservation_ref: str,
        execution_decision_ref: str,
        now: datetime,
    ) -> BudgetReservationSnapshot:
        async with self._session_factory() as session:
            return await BudgetReservationRepository(session).claim_or_revalidate(
                reservation_ref=reservation_ref,
                execution_decision_ref=execution_decision_ref,
                now=now,
            )

    async def release_pre_submit(
        self,
        *,
        reservation_ref: str,
        execution_decision_ref: str,
        now: datetime,
    ) -> BudgetReservationSnapshot:
        async with self._session_factory() as session:
            return await BudgetReservationRepository(session).release(
                reservation_ref=reservation_ref,
                execution_decision_ref=execution_decision_ref,
                now=now,
            )

    async def reconcile(
        self,
        *,
        reservation_ref: str,
        execution_decision_ref: str,
        cost_record_ref: str,
        now: datetime,
    ) -> BudgetReservationSnapshot:
        evidence = await self._load_cost_evidence(cost_record_ref)
        async with self._session_factory() as session:
            return await BudgetReservationRepository(session).reconcile(
                reservation_ref=reservation_ref,
                execution_decision_ref=execution_decision_ref,
                cost_record_ref=evidence.cost_record_ref,
                actual_cost=evidence.cost_amount,
                evidence_currency=evidence.currency,
                now=now,
            )

    async def _load_cost_evidence(self, cost_record_ref: str) -> HostCostEvidence:
        call_id = _parse_api_call_ref(cost_record_ref)
        async with self._session_factory() as session:
            page = await UsageRepository(session).get_calls(call_id=call_id, page=1, page_size=1)
        items = page["items"]
        if not items:
            raise BudgetReservationIntegrityError(f"no authoritative Host cost record for {cost_record_ref}")
        row = items[0]
        currency = row["currency"]
        if not isinstance(currency, str) or not currency:
            raise BudgetReservationIntegrityError(f"cost record {cost_record_ref} has no currency")
        return HostCostEvidence(
            cost_record_ref=cost_record_ref,
            cost_amount=_decimal_cost(row["cost_amount"], cost_record_ref=cost_record_ref),
            currency=currency,
            task_id=None,
        )
