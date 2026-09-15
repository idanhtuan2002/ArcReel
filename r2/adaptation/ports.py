"""Structural ports for the M6 adaptation proposal-evidence layer (plan Task 6).

Pure ``Protocol`` seams — import only adaptation contracts, never a concrete
repository, session, ORM row, clock or provider. The concrete adapter
(``lib.db.repositories.adaptation.AdaptationRepository``) implements this shape;
``AdaptationEvidenceService`` depends only on the protocols here.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from r2.contracts.adaptation import AdaptationBranchV2, AdaptationMapV2, ScreenplayArtifactV2


@runtime_checkable
class AdaptationEvidenceRepositoryPort(Protocol):
    """Scoped, transaction-bound evidence adapter: exact reads and append-only writes.

    No method mutates an authority head. The adapter never commits, rolls back, or
    constructs a session — the unit of work owns that lifecycle.
    """

    async def get_exact_branch(
        self, *, branch_id: str, version: int, project_name: str, user_id: str
    ) -> AdaptationBranchV2 | None: ...

    async def get_latest_branch_version(
        self, *, branch_id: str, project_name: str, user_id: str
    ) -> AdaptationBranchV2 | None: ...

    async def insert_branch(self, branch: AdaptationBranchV2, *, user_id: str, project_name: str) -> None: ...

    async def get_exact_map(
        self, *, adaptation_map_id: str, version: int, project_name: str, user_id: str
    ) -> AdaptationMapV2 | None: ...

    async def insert_map(self, map_: AdaptationMapV2, *, user_id: str, project_name: str) -> None: ...

    async def get_exact_screenplay(
        self, *, screenplay_id: str, version: int, project_name: str, user_id: str
    ) -> ScreenplayArtifactV2 | None: ...

    async def insert_screenplay(self, screenplay: ScreenplayArtifactV2, *, user_id: str, project_name: str) -> None: ...


@runtime_checkable
class AdaptationUnitOfWork(Protocol):
    repository: AdaptationEvidenceRepositoryPort

    async def __aenter__(self) -> AdaptationUnitOfWork: ...

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None: ...

    async def commit(self) -> None: ...


AdaptationUnitOfWorkFactory = Callable[[], AdaptationUnitOfWork]

__all__ = [
    "AdaptationEvidenceRepositoryPort",
    "AdaptationUnitOfWork",
    "AdaptationUnitOfWorkFactory",
]
