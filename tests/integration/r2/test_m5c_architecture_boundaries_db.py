"""Companion to ``tests/unit/r2/test_m5c_architecture_boundaries.py`` for the one Task 21
(M5C-2 checkpoint freeze) architecture-fitness sensor that needs a real database
connection: the spec §7.2 isolation precondition. Everything else in that fitness suite
is a pure structural sensor and stays in the unit-tier file.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.narrative_lifecycle_uow import SqlAlchemyNarrativeLifecycleUnitOfWork

type Factory = async_sessionmaker[AsyncSession]


async def test_authority_kernel_transactions_run_at_read_committed_on_postgres(
    concurrent_session_factory: Factory,
) -> None:
    """Spec §7.2's step-2/step-5 double ``get_decision_by_id`` lookup is correct only
    under a fresh per-statement snapshot — i.e. exactly ``READ COMMITTED``, not a
    stronger isolation level that would instead force a serialization failure."""
    async with concurrent_session_factory() as probe:
        if probe.bind.dialect.name == "sqlite":
            pytest.skip("isolation level is a PostgreSQL-only precondition (spec §7.2)")

    async with SqlAlchemyNarrativeLifecycleUnitOfWork(concurrent_session_factory) as uow:
        level = (await uow.session.execute(text("SHOW TRANSACTION ISOLATION LEVEL"))).scalar_one()
    assert level == "read committed"
