"""Shared fixtures for the M5C-2 acceptance/conflict/evidence/integrity integration
suites. Test doubles live in ``_fakes.py``, not here.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.narrative_lifecycle_uow import narrative_lifecycle_uow_factory
from r2.narrative_lifecycle.acceptance import NarrativeAcceptanceService
from tests.integration.r2.narrative_lifecycle._fakes import FakeShowrunnerAuthorityPort

type Factory = async_sessionmaker[AsyncSession]


@pytest.fixture
def fake_showrunner() -> FakeShowrunnerAuthorityPort:
    return FakeShowrunnerAuthorityPort()


@pytest.fixture
def acceptance_service(
    session_factory: Factory, fake_showrunner: FakeShowrunnerAuthorityPort
) -> NarrativeAcceptanceService:
    return NarrativeAcceptanceService(narrative_lifecycle_uow_factory(session_factory), fake_showrunner)
