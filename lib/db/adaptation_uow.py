"""M6 adaptation unit-of-work adapter.

One call owns one fresh ``AsyncSession`` transaction through this UoW. It starts a
serialized write (SQLite ``BEGIN IMMEDIATE``; PostgreSQL ``session.begin()`` plus
whatever row locks the caller takes) and exposes the adaptation repository. It never
commits or rolls back outside this lifecycle. Mirrors
``lib.db.narrative_lifecycle_uow.SqlAlchemyNarrativeLifecycleUnitOfWork`` exactly.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.repositories.adaptation import AdaptationRepository

SessionFactory = Callable[[], AsyncSession]


class SqlAlchemyAdaptationUnitOfWork:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self.repository: AdaptationRepository

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("adaptation unit of work is not active")
        return self._session

    async def __aenter__(self) -> SqlAlchemyAdaptationUnitOfWork:
        self._session = self._session_factory()
        if self._session.get_bind().dialect.name == "sqlite":
            await self._session.execute(text("BEGIN IMMEDIATE"))
        else:
            await self._session.begin()
        self.repository = AdaptationRepository(self._session)
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        session = self._session
        if session is None:
            return
        if session.in_transaction():
            await session.rollback()
        await session.close()
        self._session = None

    async def commit(self) -> None:
        await self.session.commit()


def adaptation_uow_factory(session_factory: SessionFactory) -> Callable[[], SqlAlchemyAdaptationUnitOfWork]:
    def _make() -> SqlAlchemyAdaptationUnitOfWork:
        return SqlAlchemyAdaptationUnitOfWork(session_factory)

    return _make
