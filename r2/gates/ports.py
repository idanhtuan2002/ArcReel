"""Structural ports for the P1 Gate A/D/C-receipt persistence boundary.

Pure ``Protocol`` seams importing only Gate contracts, never a concrete
repository, session, or ORM row.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from r2.contracts.gates import FinalCutReceipt, GreenlightDecision, PublishApprovalDecision


@runtime_checkable
class GreenlightRepositoryPort(Protocol):
    async def append(self, decision: GreenlightDecision) -> None: ...

    async def list_for_project(self, *, user_id: str, project_name: str) -> list[GreenlightDecision]: ...


@runtime_checkable
class PublishApprovalRepositoryPort(Protocol):
    async def append(self, decision: PublishApprovalDecision) -> None: ...

    async def list_for_project(self, *, user_id: str, project_name: str) -> list[PublishApprovalDecision]: ...


@runtime_checkable
class FinalCutReceiptRepositoryPort(Protocol):
    async def append(self, receipt: FinalCutReceipt) -> None: ...

    async def list_for_artifact(
        self, *, user_id: str, project_name: str, artifact_key: str
    ) -> list[FinalCutReceipt]: ...


__all__ = [
    "FinalCutReceiptRepositoryPort",
    "GreenlightRepositoryPort",
    "PublishApprovalRepositoryPort",
]
