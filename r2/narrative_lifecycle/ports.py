"""Structural ports for the M5C Narrative-lifecycle evidence layer.

These are pure ``Protocol`` seams — they import only the evidence contracts, never a
repository, session, ORM row, clock, or provider. The concrete adapters live under
``lib.db``; the workflow service depends only on the protocols here.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from r2.contracts.narrative_lifecycle import (
    DraftCandidate,
    ExtractionAttempt,
    ExtractionResult,
    NarrativeChangeSet,
    NarrativeRevision,
)


@runtime_checkable
class NarrativeLifecycleEvidenceRepositoryPort(Protocol):
    """Scoped, transaction-bound evidence adapter: exact reads and append-only writes.

    No method mutates a head or advances acceptance. The adapter never commits, rolls
    back, or constructs a session — the unit of work owns that lifecycle.
    """

    async def get_exact_draft_candidate(
        self, *, candidate_id: str, project_name: str, user_id: str
    ) -> DraftCandidate | None: ...

    async def get_exact_revision(
        self, *, revision_id: str, project_name: str, user_id: str
    ) -> NarrativeRevision | None: ...

    async def get_exact_extraction_attempt(
        self, *, attempt_id: str, project_name: str, user_id: str
    ) -> ExtractionAttempt | None: ...

    async def get_exact_extraction_result(
        self, *, attempt_id: str, generation: int, project_name: str, user_id: str
    ) -> ExtractionResult | None: ...

    async def get_exact_change_set(
        self, *, change_set_id: str, project_name: str, user_id: str
    ) -> NarrativeChangeSet | None: ...

    async def insert_draft_candidate(self, candidate: DraftCandidate) -> None: ...

    async def insert_revision(self, revision: NarrativeRevision) -> None: ...

    async def insert_extraction_attempt(self, attempt: ExtractionAttempt) -> None: ...

    async def insert_successful_extraction(
        self, result: ExtractionResult, change_sets: tuple[NarrativeChangeSet, ...]
    ) -> None: ...

    async def insert_non_successful_extraction(self, result: ExtractionResult) -> None: ...

    async def flush(self) -> None: ...


@runtime_checkable
class NarrativeLifecycleUnitOfWork(Protocol):
    """One fresh authority transaction. Owns commit / rollback; exposes one repository."""

    @property
    def repository(self) -> NarrativeLifecycleEvidenceRepositoryPort: ...

    async def __aenter__(self) -> NarrativeLifecycleUnitOfWork: ...

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None: ...

    async def commit(self) -> None: ...


NarrativeLifecycleUnitOfWorkFactory = Callable[[], NarrativeLifecycleUnitOfWork]
