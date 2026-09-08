"""Restart safety for the C04 reservation state M4 consumes.

The reservation is driven against a real file-backed SQLite session through the
paid-submission guard; the engine is disposed and a fresh one opened on the same
database file, and the reservation / amount / currency are re-asserted across the
reopen. No in-memory fake stands in for the Host boundary M4 calls.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from lib.budget_reservation import BudgetReservationState
from lib.db.base import Base
from lib.db.models import register_models as register_db_models
from lib.db.repositories.budget_reservation_repo import BudgetReservationRepository
from r2.contracts import GenerationLifecycleStatus
from r2.production_intelligence.host_integration import M4HostIntegration
from server.services.budget_reservation_service import BudgetReservationService

_NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
_CONTENT_FP = "c" * 64


@asynccontextmanager
async def _reopenable_engine(db_path: Path) -> AsyncGenerator[AsyncEngine]:
    """A file-backed SQLite engine (NullPool: independent connections) that can be
    disposed and re-opened on the same file to simulate a process restart."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=pool.NullPool)
    register_db_models()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


async def _seed_scope_and_reservation(
    db_path: Path,
    *,
    reservation_ref: str,
    execution_decision_ref: str,
    amount: Decimal,
) -> None:
    async with _reopenable_engine(db_path) as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        service = BudgetReservationService(factory)
        await service.create_scope(
            budget_scope_ref="scope-1",
            currency="USD",
            authorized_limit=Decimal("100.00"),
            now=_NOW,
        )
        await service.reserve_for_execution(
            budget_scope_ref="scope-1",
            reservation_ref=reservation_ref,
            execution_decision_ref=execution_decision_ref,
            amount=amount,
            currency="USD",
            expires_at=None,
            provenance={"attempt_ref": "att-1"},
            now=_NOW,
        )


async def test_c04_reservation_survives_an_engine_close_and_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "reservations.db"
    await _seed_scope_and_reservation(
        db_path, reservation_ref="rsv-1", execution_decision_ref="ED:SH05", amount=Decimal("2.50")
    )

    # Same database file, brand new engine + service: claim, then close.
    async with _reopenable_engine(db_path) as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        await BudgetReservationService(factory).claim_for_submission(
            reservation_ref="rsv-1", execution_decision_ref="ED:SH05", now=_NOW
        )

    # Reopen once more and re-assert the persisted reservation / amount / currency.
    async with _reopenable_engine(db_path) as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            snapshot = await BudgetReservationRepository(session).get_reservation("rsv-1")

    assert snapshot is not None
    assert snapshot.state is BudgetReservationState.CLAIMED
    assert snapshot.reserved_amount == Decimal("2.50")
    assert snapshot.currency == "USD"
    assert snapshot.execution_decision_ref == "ED:SH05"


async def test_m4_paid_submission_claims_the_real_reservation_and_it_persists(tmp_path: Path, hostkit) -> None:
    db_path = tmp_path / "reservations.db"
    decision = hostkit.make_decision(provider="cloud", reservation="rsv-1")
    await _seed_scope_and_reservation(
        db_path, reservation_ref="rsv-1", execution_decision_ref=decision.id, amount=Decimal("3.00")
    )

    async with _reopenable_engine(db_path) as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        integration = M4HostIntegration(
            submitter=hostkit.Submitter(),
            reservation_service=BudgetReservationService(factory),
            clock=lambda: _NOW,
        )
        candidate = await integration.execute_admitted(
            decision=decision,
            request=hostkit.make_request(provider="cloud"),
            attempt_ref="ATT-1",
            content_fingerprint=_CONTENT_FP,
        )
    assert candidate.lifecycle_state is GenerationLifecycleStatus.GENERATED

    # Reopen: the guard claimed the real reservation and the claim is durable.
    async with _reopenable_engine(db_path) as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            snapshot = await BudgetReservationRepository(session).get_reservation("rsv-1")

    assert snapshot is not None
    assert snapshot.state is BudgetReservationState.CLAIMED
    assert snapshot.execution_decision_ref == decision.id
    assert snapshot.claimed_at is not None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
