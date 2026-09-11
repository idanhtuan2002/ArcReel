"""``NarrativeAcceptanceService`` — the authenticated public facade for the M5C-2
Narrative decision authority (spec §6, §8.1).

Exposes exactly: ``decide_revision``, ``review_change_set``, ``resolve_change_set_conflict``
(this task); ``admit_canon_handoff`` (Task 28); and the read-only ``get_current_*`` /
``verify_exact_current_selection`` observations. No generic ``save_decision``,
``set_head``, ``approve``, ``latest``, or raw repository method is public. The public
decision surface never accepts a caller-supplied ``NarrativeDecisionAuthorization`` —
every command takes only ``command`` and ``authenticated_principal``; the injected
``NarrativeShowrunnerAuthorityPort`` decides who may act, and the ``AuthorityKernel``
(Task 17) calls it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from r2.contracts.narrative_lifecycle import (
    ChangeSetReviewCommand,
    ChangeSetReviewHead,
    ConflictResolutionCommand,
    ConflictResolutionHead,
    ConflictResolutionLineage,
    NarrativeChangeSet,
    NarrativeDecisionCommand,
    NarrativeDecisionReceipt,
    NarrativeWorkScope,
    RevisionAcceptanceCommand,
    RevisionAcceptanceHead,
)
from r2.narrative_lifecycle.authority_kernel import AuthorityKernel, head_lock_sort_key
from r2.narrative_lifecycle.coverage import minimal_conflict_subject
from r2.narrative_lifecycle.errors import NarrativeConflictLineageConflict, NarrativeDecisionApplicabilityError
from r2.narrative_lifecycle.hashing import compute_conflict_subject_fingerprint
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

    async def resolve_change_set_conflict(
        self, command: ConflictResolutionCommand, *, authenticated_principal: str
    ) -> NarrativeDecisionReceipt:
        """The only conflict-lineage creation interface (§6.7). A genesis command
        (``expected_latest_decision_id is None``) atomically derives the canonical
        conflict subject from the exact currently-effective competing change-set
        reviews, creates the lineage + its zero-generation head, and appends the first
        decision; a non-genesis command acts on an already-existing lineage/head."""
        prepare_genesis = self._prepare_conflict_genesis if command.expected_latest_decision_id is None else None
        return await self._kernel.run(
            command,
            authenticated_principal=authenticated_principal,
            verify_applicability=self._verify_conflict_applicability,
            prepare_genesis=prepare_genesis,
        )

    async def _verify_conflict_applicability(
        self, repo: NarrativeLifecycleRepositoryPort, command: NarrativeDecisionCommand
    ) -> None:
        assert isinstance(command, ConflictResolutionCommand)
        # Read-only here: the kernel already holds this decision's own conflict-
        # resolution head (rank 2) by this point (step 4), so taking a fresh lock on
        # rank-1 change-set-review heads now would lock out of the §7.3 canonical
        # order and risk a deadlock against a genesis on the same heads. Genesis
        # (below) runs before any head is locked, so it can safely lock in order.
        await self._verify_competitors(repo, command, lock=False)

    async def _prepare_conflict_genesis(
        self, repo: NarrativeLifecycleRepositoryPort, command: NarrativeDecisionCommand
    ) -> None:
        assert isinstance(command, ConflictResolutionCommand)
        scope = command.work_scope
        revision_head = await repo.lock_or_insert_revision_head(scope)
        if revision_head.effective_decision_id != command.revision_acceptance_decision_id:
            raise NarrativeDecisionApplicabilityError(
                f"revision acceptance {command.revision_acceptance_decision_id!r} is not the current effective revision"
            )
        change_sets = await self._verify_competitors(repo, command, lock=True)
        subject = minimal_conflict_subject(change_sets)
        fingerprint = compute_conflict_subject_fingerprint(subject)
        proposed = ConflictResolutionLineage(
            conflict_resolution_lineage_id=command.conflict_resolution_lineage_id,
            revision_acceptance_decision_id=command.revision_acceptance_decision_id,
            conflict_subject=subject,
            conflict_subject_fingerprint=fingerprint,
            created_at=datetime.now(UTC),
            created_by=command.actor_id,
        )
        winner = await repo.insert_conflict_lineage(proposed, user_id=scope.user_id, project_name=scope.project_name)
        if winner.conflict_resolution_lineage_id != command.conflict_resolution_lineage_id:
            raise NarrativeConflictLineageConflict(
                f"this conflict subject already belongs to lineage {winner.conflict_resolution_lineage_id!r}"
            )

    async def _verify_competitors(
        self, repo: NarrativeLifecycleRepositoryPort, command: ConflictResolutionCommand, *, lock: bool
    ) -> list[NarrativeChangeSet]:
        """Resolve and verify every named competitor: its review decision must resolve,
        must select exactly the named change set, and must still be the current
        effective selection for its own lineage. Returns the exact evidence rows so a
        genesis caller can derive the conflict subject from the same verified read.

        ``lock=True`` (genesis only) additionally holds each competing change-set-review
        head for the rest of this transaction, in the §7.3 canonical order — sorted by
        ``head_lock_sort_key``, never by the caller's own listing order — so two genesis
        commands naming the same lineages in opposite order cannot deadlock.
        """
        scope = command.work_scope
        resolved: list[tuple[str, str, str]] = []  # (change_set_id, review_decision_id, change_set_lineage_id)
        for change_set_id, review_decision_id in zip(
            command.competing_change_set_ids, command.competing_review_decision_ids, strict=True
        ):
            stored = await repo.get_decision_by_id(
                review_decision_id, user_id=scope.user_id, project_name=scope.project_name
            )
            if stored is None:
                raise NarrativeDecisionApplicabilityError(f"review decision {review_decision_id!r} does not resolve")
            review_command, _, _ = stored
            if (
                not isinstance(review_command, ChangeSetReviewCommand)
                or review_command.selected_change_set_id != change_set_id
            ):
                raise NarrativeDecisionApplicabilityError(
                    f"review decision {review_decision_id!r} does not select change set {change_set_id!r}"
                )
            resolved.append((change_set_id, review_decision_id, review_command.change_set_lineage_id))

        order = resolved
        if lock:
            order = sorted(
                resolved,
                key=lambda item: head_lock_sort_key(
                    "CHANGE_SET_REVIEW",
                    user_id=scope.user_id,
                    project_name=scope.project_name,
                    logical_key=(command.revision_acceptance_decision_id, item[2]),
                ),
            )
        for _change_set_id, review_decision_id, lineage_id in order:
            get_head = repo.lock_existing_change_set_review_head if lock else repo.get_change_set_review_head
            review_head = await get_head(
                revision_acceptance_decision_id=command.revision_acceptance_decision_id,
                change_set_lineage_id=lineage_id,
                user_id=scope.user_id,
                project_name=scope.project_name,
            )
            if review_head is None or review_head.effective_decision_id != review_decision_id:
                raise NarrativeDecisionApplicabilityError(
                    f"review decision {review_decision_id!r} is not the current effective selection for its lineage"
                )

        change_sets: list[NarrativeChangeSet] = []
        for change_set_id, _review_decision_id, _ in resolved:  # preserve the caller's own order for the subject
            change_set = await repo.get_exact_change_set(
                change_set_id=change_set_id, project_name=scope.project_name, user_id=scope.user_id
            )
            if change_set is None:
                raise NarrativeDecisionApplicabilityError(f"change set {change_set_id!r} does not resolve")
            change_sets.append(change_set)
        return change_sets

    async def is_conflict_resolution_applicable(self, decision_id: str, *, user_id: str, project_name: str) -> bool:
        """§6.7: a resolution is applicable only while it is the effective resolution
        for its own head *and* every review decision it named remains effective for
        its own lineage. Returns ``False`` — never raises — the moment either
        condition fails, including for an absent or non-conflict-resolution id."""
        async with self._uow_factory() as uow:
            repo = uow.repository
            stored = await repo.get_decision_by_id(decision_id, user_id=user_id, project_name=project_name)
            if stored is None:
                return False
            command, _, _ = stored
            if not isinstance(command, ConflictResolutionCommand):
                return False
            head = await repo.get_conflict_resolution_head(
                revision_acceptance_decision_id=command.revision_acceptance_decision_id,
                conflict_resolution_lineage_id=command.conflict_resolution_lineage_id,
                user_id=user_id,
                project_name=project_name,
            )
            if head is None or head.effective_decision_id != decision_id:
                return False
            for review_decision_id in command.competing_review_decision_ids:
                review_stored = await repo.get_decision_by_id(
                    review_decision_id, user_id=user_id, project_name=project_name
                )
                if review_stored is None:
                    return False
                review_command, _, _ = review_stored
                if not isinstance(review_command, ChangeSetReviewCommand):
                    return False
                review_head = await repo.get_change_set_review_head(
                    revision_acceptance_decision_id=command.revision_acceptance_decision_id,
                    change_set_lineage_id=review_command.change_set_lineage_id,
                    user_id=user_id,
                    project_name=project_name,
                )
                if review_head is None or review_head.effective_decision_id != review_decision_id:
                    return False
            return True

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
