"""Claim the budget hold immediately before the first paid side effect.

The guard runs exactly one ordering: claim the reservation, and only if that
commits, invoke ``submit()``. It never releases after ``submit()`` has started; a
failure that is proven to happen before ``submit()`` simply propagates with the
reservation left as the repository transaction left it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Protocol

from lib.budget_reservation import BudgetReservationSnapshot


class SupportsClaimForSubmission(Protocol):
    async def claim_for_submission(
        self,
        *,
        reservation_ref: str,
        execution_decision_ref: str,
        now: datetime,
    ) -> BudgetReservationSnapshot: ...


async def submit_with_budget_guard[T](
    *,
    reservation_service: SupportsClaimForSubmission,
    reservation_ref: str,
    execution_decision_ref: str,
    submit: Callable[[], Awaitable[T]],
    now: datetime,
) -> T:
    await reservation_service.claim_for_submission(
        reservation_ref=reservation_ref,
        execution_decision_ref=execution_decision_ref,
        now=now,
    )
    return await submit()
