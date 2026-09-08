"""Persistence-neutral Canon protocols.

The R2 narrative core depends only on these Protocols; the Host binds concrete
SQLAlchemy adapters. ``CanonWriteRepositoryPort`` is authoritative-write capable
and only ``CanonTransactionService`` (via ``CanonAuthorityUnitOfWork``) is allowed
to type against it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from r2.contracts import AcceptedCanonDeltaSnapshot, CanonBranchSnapshot, CanonVersionSnapshot

from .canon_state import ResolvedCanonView


class CanonReadRepositoryPort(Protocol):
    async def get_branch(self, *, branch_id: str, project_name: str, user_id: str) -> CanonBranchSnapshot | None: ...

    async def get_version(
        self, *, canon_version_id: str, project_name: str, user_id: str
    ) -> CanonVersionSnapshot | None: ...

    async def get_accepted_delta(
        self, *, canon_delta_id: str, project_name: str, user_id: str
    ) -> AcceptedCanonDeltaSnapshot | None: ...

    async def get_accepted_delta_by_approval_ref(
        self, *, approval_ref: str, project_name: str, user_id: str
    ) -> AcceptedCanonDeltaSnapshot | None: ...

    async def list_scope_branches(self, *, project_name: str, user_id: str) -> tuple[CanonBranchSnapshot, ...]: ...

    async def list_branch_versions(
        self, *, branch_id: str, project_name: str, user_id: str
    ) -> tuple[CanonVersionSnapshot, ...]: ...


class CanonProjectionRepositoryPort(CanonReadRepositoryPort, Protocol):
    async def load_projection(
        self, *, canon_version_id: str, project_name: str, user_id: str
    ) -> ResolvedCanonView | None: ...

    async def upsert_projection(
        self, *, view: ResolvedCanonView, built_at: datetime, project_name: str, user_id: str
    ) -> None: ...


class CanonWriteRepositoryPort(CanonProjectionRepositoryPort, Protocol):
    async def lock_branch(self, *, branch_id: str, project_name: str, user_id: str) -> CanonBranchSnapshot: ...

    async def insert_branch(self, branch: CanonBranchSnapshot) -> None: ...

    async def insert_delta(self, accepted: AcceptedCanonDeltaSnapshot) -> None: ...

    async def insert_version(self, version: CanonVersionSnapshot) -> None: ...

    async def advance_head(
        self,
        *,
        branch_id: str,
        expected_head_id: str | None,
        version_id: str,
        project_name: str,
        user_id: str,
    ) -> None: ...

    async def flush(self) -> None: ...


class CanonProjectionUnitOfWork(Protocol):
    @property
    def repository(self) -> CanonProjectionRepositoryPort: ...

    async def __aenter__(self) -> CanonProjectionUnitOfWork: ...

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None: ...

    async def commit(self) -> None: ...


class CanonAuthorityUnitOfWork(Protocol):
    @property
    def repository(self) -> CanonWriteRepositoryPort: ...

    async def __aenter__(self) -> CanonAuthorityUnitOfWork: ...

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None: ...

    async def commit(self) -> None: ...


class CanonProjectionUnitOfWorkFactory(Protocol):
    def __call__(self) -> CanonProjectionUnitOfWork: ...


class CanonAuthorityUnitOfWorkFactory(Protocol):
    def __call__(self) -> CanonAuthorityUnitOfWork: ...
