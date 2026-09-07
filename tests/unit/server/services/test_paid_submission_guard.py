"""Unit tests for the paid-submission budget guard ordering."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from lib.budget_reservation import (
    BudgetReservationIntegrityError,
    BudgetReservationSnapshot,
    BudgetReservationState,
    InvalidBudgetTransitionError,
)
from server.services.paid_submission_guard import submit_with_budget_guard

NOW = datetime(2026, 9, 7, 9, 0, tzinfo=UTC)

_CLAIMED = BudgetReservationSnapshot(
    reservation_ref="reservation-1",
    budget_scope_ref="scope-1",
    execution_decision_ref="decision-1",
    reserved_amount=Decimal("4"),
    currency="USD",
    state=BudgetReservationState.CLAIMED,
    created_at=NOW,
    expires_at=None,
    claimed_at=NOW,
    released_at=None,
    reconciled_at=None,
    cost_record_ref=None,
    version=1,
)


class _FakeClaimer:
    def __init__(self, *, claim_error: Exception | None = None) -> None:
        self.claim_count = 0
        self.release_count = 0
        self._claim_error = claim_error

    async def claim_for_submission(
        self, *, reservation_ref: str, execution_decision_ref: str, now: datetime
    ) -> BudgetReservationSnapshot:
        del reservation_ref, execution_decision_ref, now
        self.claim_count += 1
        if self._claim_error is not None:
            raise self._claim_error
        return _CLAIMED

    async def release_pre_submit(
        self, *, reservation_ref: str, execution_decision_ref: str, now: datetime
    ) -> BudgetReservationSnapshot:
        del reservation_ref, execution_decision_ref, now
        self.release_count += 1
        return _CLAIMED


class _Submitter:
    def __init__(self, *, raises: Exception | None = None) -> None:
        self.submission_count = 0
        self._raises = raises

    async def __call__(self) -> str:
        self.submission_count += 1
        if self._raises is not None:
            raise self._raises
        return "submitted"


async def test_claims_once_then_submits_once() -> None:
    claimer = _FakeClaimer()
    submitter = _Submitter()

    result = await submit_with_budget_guard(
        reservation_service=claimer,
        reservation_ref="reservation-1",
        execution_decision_ref="decision-1",
        submit=submitter,
        now=NOW,
    )

    assert result == "submitted"
    assert claimer.claim_count == 1
    assert submitter.submission_count == 1
    assert claimer.release_count == 0


async def test_expired_reservation_never_submits() -> None:
    claimer = _FakeClaimer(claim_error=InvalidBudgetTransitionError("expired"))
    submitter = _Submitter()

    with pytest.raises(InvalidBudgetTransitionError):
        await submit_with_budget_guard(
            reservation_service=claimer,
            reservation_ref="reservation-1",
            execution_decision_ref="decision-1",
            submit=submitter,
            now=NOW,
        )

    assert submitter.submission_count == 0
    assert claimer.release_count == 0


async def test_wrong_execution_ref_never_submits() -> None:
    claimer = _FakeClaimer(claim_error=BudgetReservationIntegrityError("execution decision"))
    submitter = _Submitter()

    with pytest.raises(BudgetReservationIntegrityError):
        await submit_with_budget_guard(
            reservation_service=claimer,
            reservation_ref="reservation-1",
            execution_decision_ref="decision-x",
            submit=submitter,
            now=NOW,
        )

    assert submitter.submission_count == 0


async def test_claim_db_failure_never_submits() -> None:
    claimer = _FakeClaimer(claim_error=RuntimeError("db down"))
    submitter = _Submitter()

    with pytest.raises(RuntimeError):
        await submit_with_budget_guard(
            reservation_service=claimer,
            reservation_ref="reservation-1",
            execution_decision_ref="decision-1",
            submit=submitter,
            now=NOW,
        )

    assert submitter.submission_count == 0
    assert claimer.release_count == 0


async def test_submit_timeout_after_claim_does_not_release() -> None:
    claimer = _FakeClaimer()
    submitter = _Submitter(raises=TimeoutError("provider timeout"))

    with pytest.raises(TimeoutError):
        await submit_with_budget_guard(
            reservation_service=claimer,
            reservation_ref="reservation-1",
            execution_decision_ref="decision-1",
            submit=submitter,
            now=NOW,
        )

    assert claimer.claim_count == 1
    assert submitter.submission_count == 1
    assert claimer.release_count == 0
