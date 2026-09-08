"""Projection-only unit-of-work lifecycle for durable Canon reads and rebuilds."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from .canon_resolver import CanonResolver
from .canon_state import ResolvedCanonView
from .ports import CanonProjectionUnitOfWorkFactory


def _utc_now() -> datetime:
    return datetime.now(UTC)


class CanonResolutionService:
    def __init__(
        self,
        projection_uow_factory: CanonProjectionUnitOfWorkFactory,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._projection_uow_factory = projection_uow_factory
        self._clock = clock

    async def resolve(
        self, *, branch_id: str, version_id: str | None, project_name: str, user_id: str
    ) -> ResolvedCanonView:
        async with self._projection_uow_factory() as uow:
            result = await CanonResolver(uow.repository, clock=self._clock).resolve(
                branch_id=branch_id,
                version_id=version_id,
                project_name=project_name,
                user_id=user_id,
            )
            await uow.commit()
            return result
