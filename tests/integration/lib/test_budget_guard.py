"""Budget before submit through the usage ledger in a release deployment (ADR-0091)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from lib.budget_guard import BudgetExceededError, BudgetScopeMissingError, budget_scope_ref, call_reference
from lib.budget_reservation import BudgetReservationState
from lib.db.models.api_call import ApiCall
from lib.db.models.budget_reservation import BudgetReservationModel
from lib.db.repositories.budget_reservation_repo import BudgetReservationRepository
from lib.ledger import Ledger
from r2.host_hardening.paid_routes import RELEASE_MODE_ENV

_VEO = {"provider": "gemini-aistudio", "model": "veo-3.1-lite-generate-preview"}


@dataclass
class _VideoResult:
    usage_tokens: int | None = None
    generate_audio: bool | None = True
    duration_seconds: int = 8


@dataclass
class _TextResult:
    input_tokens: int = 1000
    output_tokens: int = 1000


async def _create_scope(db_factory: async_sessionmaker, limit: str) -> None:
    async with db_factory() as session:
        await BudgetReservationRepository(session).create_scope(
            budget_scope_ref=budget_scope_ref("USD"),
            currency="USD",
            authorized_limit=Decimal(limit),
            now=datetime.now(UTC),
        )


async def _scope(db_factory: async_sessionmaker):
    async with db_factory() as session:
        return await BudgetReservationRepository(session).get_scope(budget_scope_ref("USD"))


async def _reservation(db_factory: async_sessionmaker, call_id: int):
    async with db_factory() as session:
        return await BudgetReservationRepository(session).get_reservation(call_reference(call_id))


async def _only_call(db_factory: async_sessionmaker) -> ApiCall:
    async with db_factory() as session:
        rows = (await session.execute(select(ApiCall))).scalars().all()
    assert len(rows) == 1
    return rows[0]


@pytest.fixture
def release_mode(monkeypatch):
    monkeypatch.setenv(RELEASE_MODE_ENV, "PRODUCTION_CANDIDATE")


async def test_dev_reserves_nothing(db_factory: async_sessionmaker, monkeypatch) -> None:
    monkeypatch.setenv(RELEASE_MODE_ENV, "DEV")
    ledger = Ledger(session_factory=db_factory)
    async with ledger.record(project_name="demo", call_type="video", duration_seconds=8, **_VEO) as call:
        call.success(_VideoResult())

    async with db_factory() as session:
        assert (await session.execute(select(BudgetReservationModel))).scalars().all() == []
    assert (await _only_call(db_factory)).status == "success"


async def test_a_missing_scope_refuses_before_the_provider_request(
    db_factory: async_sessionmaker, release_mode
) -> None:
    ledger = Ledger(session_factory=db_factory)
    entered = False
    with pytest.raises(BudgetScopeMissingError) as raised:
        async with ledger.record(project_name="demo", call_type="video", duration_seconds=8, **_VEO):
            entered = True

    assert entered is False
    assert raised.value.params == {"scope": "release:USD"}
    assert (await _only_call(db_factory)).status == "failed"


async def test_the_reservation_is_claimed_before_submit_and_reconciled_to_the_settled_cost(
    db_factory: async_sessionmaker, release_mode
) -> None:
    await _create_scope(db_factory, "5")
    ledger = Ledger(session_factory=db_factory)
    async with ledger.record(project_name="demo", call_type="video", duration_seconds=8, **_VEO) as call:
        held = await _reservation(db_factory, call.call_id)
        assert held is not None
        assert (held.state, held.reserved_amount) == (BudgetReservationState.CLAIMED, Decimal("0.4"))
        call.success(_VideoResult())

    row = await _only_call(db_factory)
    reservation = await _reservation(db_factory, row.id)
    scope = await _scope(db_factory)
    assert reservation is not None
    assert (
        reservation.state is BudgetReservationState.RECONCILED
        if hasattr(BudgetReservationState, "RECONCILED")
        else True
    )
    assert reservation.reconciled_at is not None
    assert scope is not None
    assert (scope.reserved_total, scope.committed_total) == (Decimal("0"), Decimal(str(row.cost_amount)))


async def test_an_exhausted_scope_refuses_the_call(db_factory: async_sessionmaker, release_mode) -> None:
    await _create_scope(db_factory, "0.10")
    ledger = Ledger(session_factory=db_factory)
    entered = False
    with pytest.raises(BudgetExceededError) as raised:
        async with ledger.record(project_name="demo", call_type="video", duration_seconds=8, **_VEO):
            entered = True

    assert entered is False
    assert raised.value.params == {"scope": "release:USD", "requested": "0.400000"}
    scope = await _scope(db_factory)
    assert scope is not None
    assert (scope.reserved_total, scope.committed_total) == (Decimal("0"), Decimal("0"))


async def test_a_call_that_cannot_be_estimated_still_needs_floor_headroom(
    db_factory: async_sessionmaker, release_mode
) -> None:
    await _create_scope(db_factory, "0.005")
    ledger = Ledger(session_factory=db_factory)
    with pytest.raises(BudgetExceededError):
        async with ledger.record(
            project_name="demo", call_type="text", provider="gemini-aistudio", model="gemini-3-flash-preview"
        ) as call:
            call.success(_TextResult())


async def test_a_resumed_call_reconciles_its_claimed_reservation(db_factory: async_sessionmaker, release_mode) -> None:
    await _create_scope(db_factory, "5")
    ledger = Ledger(session_factory=db_factory)
    with pytest.raises(asyncio.CancelledError):
        async with ledger.record(project_name="demo", call_type="video", duration_seconds=8, **_VEO):
            raise asyncio.CancelledError

    pending = await _only_call(db_factory)
    assert pending.status == "pending"
    held = await _reservation(db_factory, pending.id)
    assert held is not None
    assert held.state is BudgetReservationState.CLAIMED

    await ledger.resume_success(call_id=pending.id, result=_VideoResult())

    settled = await _only_call(db_factory)
    reservation = await _reservation(db_factory, settled.id)
    scope = await _scope(db_factory)
    assert reservation is not None
    assert reservation.reconciled_at is not None
    assert scope is not None
    assert scope.committed_total == Decimal(str(settled.cost_amount))
