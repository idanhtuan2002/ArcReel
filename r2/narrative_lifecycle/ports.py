"""Structural ports for the M5C Narrative-lifecycle evidence layer.

These are pure ``Protocol`` seams — they import only the evidence contracts, never a
repository, session, ORM row, clock, or provider. The concrete adapters live under
``lib.db``; the workflow service depends only on the protocols here.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol, runtime_checkable

from r2.contracts.narrative_lifecycle import (
    ChangeSetReviewHead,
    CompilationAttempt,
    CompilationResult,
    CompiledCanonDeltaEvidence,
    ConflictResolutionHead,
    ConflictResolutionLineage,
    DraftCandidate,
    ExtractionAttempt,
    ExtractionResult,
    NarrativeChangeSet,
    NarrativeDecisionAuthorization,
    NarrativeDecisionCommand,
    NarrativeDecisionRetryAuthentication,
    NarrativeRevision,
    NarrativeWorkScope,
    RevisionAcceptanceHead,
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

    async def get_extraction_attempt_by_id(self, *, attempt_id: str) -> ExtractionAttempt | None: ...

    async def get_exact_extraction_result(
        self, *, attempt_id: str, generation: int, project_name: str, user_id: str
    ) -> ExtractionResult | None: ...

    async def get_exact_change_set(
        self, *, change_set_id: str, project_name: str, user_id: str
    ) -> NarrativeChangeSet | None: ...

    async def get_exact_compilation_attempt(
        self, *, attempt_id: str, project_name: str, user_id: str
    ) -> CompilationAttempt | None: ...

    async def get_compilation_attempt_by_id(self, *, attempt_id: str) -> CompilationAttempt | None: ...

    async def get_exact_compilation_result(
        self, *, attempt_id: str, generation: int, project_name: str, user_id: str
    ) -> CompilationResult | None: ...

    async def get_exact_compiled_canon_delta(
        self, *, compilation_result_id: str, project_name: str, user_id: str
    ) -> CompiledCanonDeltaEvidence | None: ...

    async def insert_draft_candidate(self, candidate: DraftCandidate) -> None: ...

    async def insert_revision(self, revision: NarrativeRevision) -> None: ...

    async def insert_extraction_attempt(self, attempt: ExtractionAttempt) -> None: ...

    async def insert_successful_extraction(
        self, result: ExtractionResult, change_sets: tuple[NarrativeChangeSet, ...]
    ) -> None: ...

    async def insert_non_successful_extraction(self, result: ExtractionResult) -> None: ...

    async def insert_compilation_attempt(self, attempt: CompilationAttempt) -> None: ...

    async def insert_successful_compilation(
        self, result: CompilationResult, evidence: CompiledCanonDeltaEvidence
    ) -> None: ...

    async def insert_non_successful_compilation(self, result: CompilationResult) -> None: ...

    async def flush(self) -> None: ...


@runtime_checkable
class NarrativeAuthorityRepositoryPort(Protocol):
    """Scoped, transaction-bound decision-authority adapter: the shared identity
    registry, the three typed decision tables, the conflict-resolution
    lineage table, and the three logical heads. Never commits, rolls back, or
    constructs a session — the unit of work owns that lifecycle.
    """

    async def get_decision_by_id(
        self, decision_id: str, *, user_id: str, project_name: str
    ) -> tuple[NarrativeDecisionCommand, NarrativeDecisionAuthorization, int] | None: ...

    async def list_revision_decisions(
        self, work_scope: NarrativeWorkScope
    ) -> list[tuple[NarrativeDecisionCommand, NarrativeDecisionAuthorization, int]]: ...

    async def list_change_set_review_decisions(
        self, *, revision_acceptance_decision_id: str, change_set_lineage_id: str
    ) -> list[tuple[NarrativeDecisionCommand, NarrativeDecisionAuthorization, int]]: ...

    async def list_conflict_resolution_decisions(
        self, *, revision_acceptance_decision_id: str, conflict_resolution_lineage_id: str
    ) -> list[tuple[NarrativeDecisionCommand, NarrativeDecisionAuthorization, int]]: ...

    async def insert_identity_and_decision(
        self,
        command: NarrativeDecisionCommand,
        authorization: NarrativeDecisionAuthorization,
        *,
        canonical_identity_hash: str,
        decision_generation: int,
        stored_at: datetime,
    ) -> None: ...

    async def get_revision_head(self, work_scope: NarrativeWorkScope) -> RevisionAcceptanceHead | None: ...

    async def lock_existing_revision_head(self, work_scope: NarrativeWorkScope) -> RevisionAcceptanceHead | None: ...

    async def get_change_set_review_head(
        self, *, revision_acceptance_decision_id: str, change_set_lineage_id: str, user_id: str, project_name: str
    ) -> ChangeSetReviewHead | None: ...

    async def lock_existing_change_set_review_head(
        self, *, revision_acceptance_decision_id: str, change_set_lineage_id: str, user_id: str, project_name: str
    ) -> ChangeSetReviewHead | None: ...

    async def get_conflict_resolution_head(
        self,
        *,
        revision_acceptance_decision_id: str,
        conflict_resolution_lineage_id: str,
        user_id: str,
        project_name: str,
    ) -> ConflictResolutionHead | None: ...

    async def lock_existing_conflict_resolution_head(
        self,
        *,
        revision_acceptance_decision_id: str,
        conflict_resolution_lineage_id: str,
        user_id: str,
        project_name: str,
    ) -> ConflictResolutionHead | None: ...

    async def lock_or_insert_revision_head(self, work_scope: NarrativeWorkScope) -> RevisionAcceptanceHead: ...

    async def lock_or_insert_change_set_review_head(
        self, *, revision_acceptance_decision_id: str, change_set_lineage_id: str, user_id: str, project_name: str
    ) -> ChangeSetReviewHead: ...

    async def lock_or_insert_conflict_resolution_head(
        self,
        *,
        revision_acceptance_decision_id: str,
        conflict_resolution_lineage_id: str,
        user_id: str,
        project_name: str,
    ) -> ConflictResolutionHead: ...

    async def advance_revision_head(
        self,
        work_scope: NarrativeWorkScope,
        *,
        expected_latest_decision_id: str | None,
        expected_effective_decision_id: str | None,
        new_latest_decision_id: str,
        new_decision_generation: int,
        new_effective_decision_id: str | None,
        new_effective_generation: int,
    ) -> None: ...

    async def advance_change_set_review_head(
        self,
        *,
        revision_acceptance_decision_id: str,
        change_set_lineage_id: str,
        expected_latest_decision_id: str | None,
        expected_effective_decision_id: str | None,
        new_latest_decision_id: str,
        new_decision_generation: int,
        new_effective_decision_id: str | None,
        new_effective_generation: int,
    ) -> None: ...

    async def advance_conflict_resolution_head(
        self,
        *,
        revision_acceptance_decision_id: str,
        conflict_resolution_lineage_id: str,
        expected_latest_decision_id: str | None,
        expected_effective_decision_id: str | None,
        new_latest_decision_id: str,
        new_decision_generation: int,
        new_effective_decision_id: str | None,
        new_effective_generation: int,
    ) -> None: ...

    async def insert_conflict_lineage(
        self, lineage: ConflictResolutionLineage, *, user_id: str, project_name: str
    ) -> ConflictResolutionLineage: ...


@runtime_checkable
class NarrativeLifecycleRepositoryPort(
    NarrativeLifecycleEvidenceRepositoryPort, NarrativeAuthorityRepositoryPort, Protocol
):
    """The full transaction-bound adapter surface the authority kernel needs: evidence
    reads (to resolve a command's referenced revision/change-set evidence) plus every
    decision-authority method above. ``NarrativeLifecycleRepository`` (``lib.db``)
    satisfies this structurally; this module never imports it."""


@runtime_checkable
class NarrativeLifecycleUnitOfWork(Protocol):
    """One fresh authority transaction. Owns commit / rollback; exposes one repository."""

    @property
    def repository(self) -> NarrativeLifecycleRepositoryPort: ...

    async def __aenter__(self) -> NarrativeLifecycleUnitOfWork: ...

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None: ...

    async def commit(self) -> None: ...


NarrativeLifecycleUnitOfWorkFactory = Callable[[], NarrativeLifecycleUnitOfWork]


@runtime_checkable
class NarrativeShowrunnerAuthorityPort(Protocol):
    """The sole source of Human Showrunner decision authority. Its only source of
    truth is an explicit project-scoped ``HUMAN_SHOWRUNNER`` grant issued by the frozen
    Governance/Showrunner approval authority: this port may read and verify that grant,
    but it creates, amends, revokes, or infers none of it. Every production adapter must
    deny by default until that authority source exists.
    """

    async def authorize_initial_decision(
        self, authenticated_principal: str, canonical_command: NarrativeDecisionCommand
    ) -> NarrativeDecisionAuthorization: ...

    async def authenticate_exact_retry(
        self, authenticated_principal: str, decision_id: str, exact_scope: NarrativeWorkScope
    ) -> NarrativeDecisionRetryAuthentication: ...
