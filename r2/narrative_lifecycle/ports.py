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
    NarrativeHandoffAdmission,
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

    # --- M5C-4 atomic M5A handoff admission ---
    #
    # The admission receipt is append-only and advances no head, but it is only ever
    # written under the same locked heads a decision would take, so it belongs to the
    # authority adapter rather than the evidence one.

    async def get_exact_handoff_admission(
        self, *, admission_id: str, project_name: str, user_id: str
    ) -> NarrativeHandoffAdmission | None: ...

    async def get_handoff_admission_by_id(self, *, admission_id: str) -> NarrativeHandoffAdmission | None: ...

    async def insert_handoff_admission(self, admission: NarrativeHandoffAdmission) -> None: ...


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

    The three methods answer three different questions and carry three different
    preconditions:

    - ``authorize_initial_decision`` mints the one original, persisted authorization for a
      typed decision command, so it is bound to a ``NarrativeDecisionFamily`` — spec
      section 6.1 fixes those at exactly three.
    - ``authenticate_exact_retry`` re-authenticates the **original** actor of an
      already-stored decision so that actor may request replay. Its precondition is that
      ``decision_id`` names an existing decision, so an adapter may resolve it against
      stored authority records.
    - ``authenticate_scoped_showrunner`` asks the capability question alone, about a
      subject that need not exist yet.

    An M5A handoff admission is served by the last one only. It is not a typed decision
    family, advances no head, and its receipt persists no
    ``NarrativeDecisionAuthorization``, so there is nothing for
    ``authorize_initial_decision`` to mint; and on a fresh ``admission_id`` there is no
    original actor and no replay, so ``authenticate_exact_retry``'s precondition does not
    hold. ``admission_id`` also lives in its own table under its own primary key and is
    deliberately kept out of ``decision_id``'s id space here, so an adapter that resolves
    decision ids can never authenticate an admission against an unrelated decision's actor.
    """

    async def authorize_initial_decision(
        self, authenticated_principal: str, canonical_command: NarrativeDecisionCommand
    ) -> NarrativeDecisionAuthorization: ...

    async def authenticate_exact_retry(
        self, authenticated_principal: str, decision_id: str, exact_scope: NarrativeWorkScope
    ) -> NarrativeDecisionRetryAuthentication: ...

    async def authenticate_scoped_showrunner(
        self, authenticated_principal: str, subject_id: str, exact_scope: NarrativeWorkScope
    ) -> NarrativeDecisionRetryAuthentication:
        """Prove this principal currently holds the project-scoped ``HUMAN_SHOWRUNNER``
        grant in this exact scope, and resolve their ``actor_id``.

        ``subject_id`` names what the capability is being exercised on — an
        ``admission_id``, say. It **need not name an existing record** and is never
        resolved against stored authority records; it is echoed back in the returned
        ``decision_id`` field purely so the caller can verify the response is bound to the
        request it made. Mints nothing durable and grants no decision authority; every
        production adapter denies by default, exactly like the other two methods.
        """
        ...
