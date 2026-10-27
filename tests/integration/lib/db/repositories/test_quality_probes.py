"""Probe custody repository: PostgreSQL-only authority and scoped reads."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.quality_probes import QualityProbeRepository
from r2.quality.errors import RequiredEvidenceMissingError
from r2.quality.ports import ProbeRequest
from tests.unit.r2.quality.test_probes import probe_request_data, recipe_config

type Factory = async_sessionmaker[AsyncSession]


def probe() -> ProbeRequest:
    return ProbeRequest.model_validate(probe_request_data(recipe_config("DECODE")))


async def test_sqlite_is_never_probe_authority(file_session_factory: Factory) -> None:
    async with file_session_factory() as session, session.begin():
        with pytest.raises(RequiredEvidenceMissingError):
            await QualityProbeRepository(session).lock_command(probe())


async def test_unknown_or_foreign_command_reads_as_absent(session_factory: Factory) -> None:
    async with session_factory() as session:
        repository = QualityProbeRepository(session)
        assert await repository.invocation(probe()) is None
        foreign = probe().model_copy(update={"execution_ref": "foreign-execution"})
        assert await repository.replay(foreign) is None
