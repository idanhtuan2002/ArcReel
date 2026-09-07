"""R2-facing port for Host budget authorization.

The adapter delegates every call straight to the Host budget service. It owns no
database session, no tables, no balances, no locks, and performs no Usage writes,
caching, retries, or fallback.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from lib.budget_reservation import BudgetReservationSnapshot


class HostBudgetAuthority(Protocol):
    """Structural view of the Host service this adapter delegates to.

    Declared locally so ``r2.production`` never imports ``server`` or ``lib.db``.
    """

    async def reserve_for_execution(
        self,
        *,
        budget_scope_ref: str,
        reservation_ref: str,
        execution_decision_ref: str,
        amount: Decimal,
        currency: str,
        expires_at: datetime | None,
        provenance: Mapping[str, object],
        now: datetime,
    ) -> BudgetReservationSnapshot: ...

    async def release_pre_submit(
        self,
        *,
        reservation_ref: str,
        execution_decision_ref: str,
        now: datetime,
    ) -> BudgetReservationSnapshot: ...


class BudgetAuthorizationPort(Protocol):
    async def reserve(
        self,
        *,
        budget_scope_ref: str,
        reservation_ref: str,
        execution_decision_ref: str,
        amount: Decimal,
        currency: str,
        expires_at: datetime | None,
        provenance: Mapping[str, object],
    ) -> BudgetReservationSnapshot: ...

    async def release_pre_submit(
        self,
        *,
        reservation_ref: str,
        execution_decision_ref: str,
    ) -> BudgetReservationSnapshot: ...


class ArcReelBudgetAuthorizationAdapter:
    def __init__(
        self,
        service: HostBudgetAuthority,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._service = service
        self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(UTC))

    async def reserve(
        self,
        *,
        budget_scope_ref: str,
        reservation_ref: str,
        execution_decision_ref: str,
        amount: Decimal,
        currency: str,
        expires_at: datetime | None,
        provenance: Mapping[str, object],
    ) -> BudgetReservationSnapshot:
        return await self._service.reserve_for_execution(
            budget_scope_ref=budget_scope_ref,
            reservation_ref=reservation_ref,
            execution_decision_ref=execution_decision_ref,
            amount=amount,
            currency=currency,
            expires_at=expires_at,
            provenance=provenance,
            now=self._clock(),
        )

    async def release_pre_submit(
        self,
        *,
        reservation_ref: str,
        execution_decision_ref: str,
    ) -> BudgetReservationSnapshot:
        return await self._service.release_pre_submit(
            reservation_ref=reservation_ref,
            execution_decision_ref=execution_decision_ref,
            now=self._clock(),
        )
