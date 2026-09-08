"""Persistence-neutral NarrativePlan protocols.

``NarrativePlanWritePort`` is authoritative-write capable; only ``NarrativePlanService``
(via ``NarrativePlanUnitOfWork``) types against it. The exact Canon read protocol is
read-only: it exposes no list-latest, search, or write surface.
"""

from __future__ import annotations

from typing import Protocol

from r2.contracts import NarrativePlanHeadSnapshot, NarrativePlanVersionSnapshot
from r2.narrative.canon_state import ResolvedCanonView


class NarrativePlanReadPort(Protocol):
    async def get_plan_head(
        self, *, plan_id: str, project_name: str, user_id: str
    ) -> NarrativePlanHeadSnapshot | None: ...

    async def get_version(
        self, *, plan_id: str, version: int, project_name: str, user_id: str
    ) -> NarrativePlanVersionSnapshot | None: ...

    async def get_version_by_revision(
        self, *, plan_revision_id: str, project_name: str, user_id: str
    ) -> NarrativePlanVersionSnapshot | None: ...

    async def get_version_by_approval(
        self, *, approval_ref: str, project_name: str, user_id: str
    ) -> NarrativePlanVersionSnapshot | None: ...

    async def list_plan_versions(
        self, *, plan_id: str, project_name: str, user_id: str
    ) -> tuple[NarrativePlanVersionSnapshot, ...]: ...


class NarrativePlanWritePort(NarrativePlanReadPort, Protocol):
    async def lock_plan(self, *, plan_id: str, project_name: str, user_id: str) -> NarrativePlanHeadSnapshot | None: ...

    async def insert_plan(self, head: NarrativePlanHeadSnapshot) -> None: ...

    async def insert_version(self, version: NarrativePlanVersionSnapshot) -> None: ...

    async def advance_head(
        self,
        *,
        plan_id: str,
        expected_version: int | None,
        new_version: int,
        project_name: str,
        user_id: str,
    ) -> None: ...

    async def flush(self) -> None: ...


class NarrativePlanUnitOfWork(Protocol):
    @property
    def repository(self) -> NarrativePlanWritePort: ...

    async def __aenter__(self) -> NarrativePlanUnitOfWork: ...

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None: ...

    async def commit(self) -> None: ...


class NarrativePlanUnitOfWorkFactory(Protocol):
    def __call__(self) -> NarrativePlanUnitOfWork: ...


class CanonVersionReader(Protocol):
    """Exact, read-only Canon access for plan-basis validation."""

    async def get_exact(
        self, *, branch_id: str, canon_version_id: str, project_name: str, user_id: str
    ) -> ResolvedCanonView | None: ...
