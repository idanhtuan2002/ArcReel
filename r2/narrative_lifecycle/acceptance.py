"""``NarrativeAcceptanceService`` — the authenticated public facade for the M5C-2
Narrative decision authority (spec §6, §8.1).

Exposes exactly: ``decide_revision``, ``review_change_set`` (this task);
``resolve_change_set_conflict`` (Task 19); ``admit_canon_handoff`` (Task 28); and the
read-only ``get_current_*`` / ``verify_exact_current_selection`` observations. No
generic ``save_decision``, ``set_head``, ``approve``, ``latest``, or raw repository
method is public. The public decision surface never accepts a caller-supplied
``NarrativeDecisionAuthorization`` — every command takes only ``command`` and
``authenticated_principal``; the injected ``NarrativeShowrunnerAuthorityPort`` decides
who may act, and the ``AuthorityKernel`` (Task 17) calls it.
"""

from __future__ import annotations

from r2.contracts.narrative_lifecycle import (
    ChangeSetReviewCommand,
    ChangeSetReviewHead,
    ConflictResolutionCommand,
    ConflictResolutionHead,
    NarrativeDecisionCommand,
    NarrativeDecisionReceipt,
    NarrativeWorkScope,
    RevisionAcceptanceCommand,
    RevisionAcceptanceHead,
)
from r2.narrative_lifecycle.authority_kernel import AuthorityKernel
from r2.narrative_lifecycle.ports import (
    NarrativeLifecycleRepositoryPort,
    NarrativeLifecycleUnitOfWorkFactory,
    NarrativeShowrunnerAuthorityPort,
)

_AnyHead = RevisionAcceptanceHead | ChangeSetReviewHead | ConflictResolutionHead


class NarrativeAcceptanceService:
    """One authority adapter per service instance; constructed without one, it raises
    rather than defaulting to a permissive stub (Task 21 asserts this)."""

    def __init__(
        self,
        uow_factory: NarrativeLifecycleUnitOfWorkFactory,
        authority: NarrativeShowrunnerAuthorityPort | None,
    ) -> None:
        if authority is None:
            raise ValueError(
                "NarrativeAcceptanceService requires a NarrativeShowrunnerAuthorityPort; "
                "it never defaults to a permissive stub"
            )
        self._uow_factory = uow_factory
        self._kernel = AuthorityKernel(uow_factory, authority)

    async def decide_revision(
        self, command: RevisionAcceptanceCommand, *, authenticated_principal: str
    ) -> NarrativeDecisionReceipt:
        return await self._kernel.run(command, authenticated_principal=authenticated_principal)

    async def review_change_set(
        self, command: ChangeSetReviewCommand, *, authenticated_principal: str
    ) -> NarrativeDecisionReceipt:
        return await self._kernel.run(command, authenticated_principal=authenticated_principal)

    async def get_current_revision_selection(self, exact_scope: NarrativeWorkScope) -> RevisionAcceptanceHead | None:
        async with self._uow_factory() as uow:
            return await uow.repository.get_revision_head(exact_scope)

    async def get_current_change_set_selection(
        self, exact_revision_decision: str, exact_lineage: str, *, user_id: str, project_name: str
    ) -> ChangeSetReviewHead | None:
        async with self._uow_factory() as uow:
            return await uow.repository.get_change_set_review_head(
                revision_acceptance_decision_id=exact_revision_decision,
                change_set_lineage_id=exact_lineage,
                user_id=user_id,
                project_name=project_name,
            )

    async def get_current_conflict_resolution(
        self, exact_revision_decision: str, exact_resolution_lineage: str, *, user_id: str, project_name: str
    ) -> ConflictResolutionHead | None:
        async with self._uow_factory() as uow:
            return await uow.repository.get_conflict_resolution_head(
                revision_acceptance_decision_id=exact_revision_decision,
                conflict_resolution_lineage_id=exact_resolution_lineage,
                user_id=user_id,
                project_name=project_name,
            )

    async def verify_exact_current_selection(self, decision_id: str, *, user_id: str, project_name: str) -> bool:
        """True iff ``decision_id`` is currently the effective decision for whichever
        head/family it belongs to. Returns ``False`` — never raises — for an absent,
        rejected, or superseded decision."""
        async with self._uow_factory() as uow:
            repo = uow.repository
            stored = await repo.get_decision_by_id(decision_id, user_id=user_id, project_name=project_name)
            if stored is None:
                return False
            command, _, _ = stored
            head = await self._current_head_for(repo, command)
            return head is not None and head.effective_decision_id == decision_id

    async def _current_head_for(
        self, repo: NarrativeLifecycleRepositoryPort, command: NarrativeDecisionCommand
    ) -> _AnyHead | None:
        scope = command.work_scope
        if isinstance(command, RevisionAcceptanceCommand):
            return await repo.get_revision_head(scope)
        if isinstance(command, ChangeSetReviewCommand):
            return await repo.get_change_set_review_head(
                revision_acceptance_decision_id=command.revision_acceptance_decision_id,
                change_set_lineage_id=command.change_set_lineage_id,
                user_id=scope.user_id,
                project_name=scope.project_name,
            )
        assert isinstance(command, ConflictResolutionCommand)
        return await repo.get_conflict_resolution_head(
            revision_acceptance_decision_id=command.revision_acceptance_decision_id,
            conflict_resolution_lineage_id=command.conflict_resolution_lineage_id,
            user_id=scope.user_id,
            project_name=scope.project_name,
        )
