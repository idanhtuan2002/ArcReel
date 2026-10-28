"""Disposition custody repository: PostgreSQL-only authority."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.quality_dispositions import DispositionKey, QualityDispositionRepository
from r2.quality.errors import RequiredEvidenceMissingError

type Factory = async_sessionmaker[AsyncSession]


async def test_sqlite_is_never_disposition_authority(file_session_factory: Factory) -> None:
    async with file_session_factory() as session, session.begin():
        repository = QualityDispositionRepository(session)
        with pytest.raises(RequiredEvidenceMissingError):
            await repository.lock_command(DispositionKey("owner", "project", "actor", "decide-1"))
        with pytest.raises(RequiredEvidenceMissingError):
            await repository.database_now()
