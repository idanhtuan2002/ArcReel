"""Canon unit-of-work adapters.

One service call owns one fresh ``AsyncSession`` transaction through exactly one
of these. The authority UoW starts a serialized write (SQLite ``BEGIN IMMEDIATE``;
PostgreSQL serialization comes from ``lock_branch``) and exposes the full
authority repository. The projection UoW uses an ordinary transaction and a
capability-limited repository with no authoritative writes.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.repositories.canon_repo import CanonProjectionRepository, CanonRepository
from r2.narrative.ports import (
    CanonAuthorityUnitOfWork,
    CanonAuthorityUnitOfWorkFactory,
    CanonProjectionUnitOfWork,
    CanonProjectionUnitOfWorkFactory,
)

SessionFactory = Callable[[], AsyncSession]


class _CanonUnitOfWorkBase:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("Canon unit of work is not active")
        return self._session

    async def commit(self) -> None:
        await self.session.commit()

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        session = self._session
        if session is None:
            return
        if session.in_transaction():
            await session.rollback()
        await session.close()
        self._session = None


class SqlAlchemyCanonProjectionUnitOfWork(_CanonUnitOfWorkBase):
    def __init__(self, session_factory: SessionFactory) -> None:
        super().__init__(session_factory)
        self.repository: CanonProjectionRepository

    async def __aenter__(self) -> SqlAlchemyCanonProjectionUnitOfWork:
        self._session = self._session_factory()
        await self._session.begin()
        self.repository = CanonProjectionRepository(self._session)
        return self


class SqlAlchemyCanonAuthorityUnitOfWork(_CanonUnitOfWorkBase):
    def __init__(self, session_factory: SessionFactory) -> None:
        super().__init__(session_factory)
        self.repository: CanonRepository

    async def __aenter__(self) -> SqlAlchemyCanonAuthorityUnitOfWork:
        self._session = self._session_factory()
        if self._session.get_bind().dialect.name == "sqlite":
            await self._session.execute(text("BEGIN IMMEDIATE"))
        else:
            await self._session.begin()
        self.repository = CanonRepository(self._session)
        return self


def canon_projection_uow_factory(session_factory: SessionFactory) -> CanonProjectionUnitOfWorkFactory:
    def _make() -> CanonProjectionUnitOfWork:
        return SqlAlchemyCanonProjectionUnitOfWork(session_factory)

    return _make


def canon_authority_uow_factory(session_factory: SessionFactory) -> CanonAuthorityUnitOfWorkFactory:
    def _make() -> CanonAuthorityUnitOfWork:
        return SqlAlchemyCanonAuthorityUnitOfWork(session_factory)

    return _make
