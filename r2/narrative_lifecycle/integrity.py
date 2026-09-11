"""``NarrativeLifecycleIntegrityChecker`` — rebuild-only, for now (Task 20; Task 30
completes it with the read-side wiring for extraction currentness).

A current-selection guard never trusts a head pointer alone (spec §6.5). This module
recomputes candidate head rows from the append-only typed decision chains into a
*separate* projection and compares that projection against the stored (mutable) head
before anything downstream is allowed to treat the stored head as authoritative. Every
``verify_*`` method raises ``NarrativeAuthorityIntegrityError`` — never silently repairs,
never picks "the latest" — the moment the rebuilt and stored projections disagree.

Pure rebuild rule, shared by every family: ``decision_generation`` is the generation of
the last decision in the append-order chain (zero, with a null pointer, for an empty
chain); ``effective_generation``/``effective_decision_id`` fold forward through the same
chain — an accepting action (``ACCEPT``/``RESOLVE``) or ``SUPERSEDE`` becomes the new
effective pointer at its own generation, and ``REJECT`` leaves the fold's running
effective pointer unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence

from r2.contracts.narrative_lifecycle import (
    ChangeSetReviewHead,
    ConflictResolutionHead,
    NarrativeDecisionAuthorization,
    NarrativeDecisionCommand,
    NarrativeWorkScope,
    RevisionAcceptanceHead,
)
from r2.narrative_lifecycle.authority_kernel import ACCEPTING_ACTION
from r2.narrative_lifecycle.errors import NarrativeAuthorityIntegrityError
from r2.narrative_lifecycle.ports import NarrativeLifecycleUnitOfWorkFactory

_StoredDecision = tuple[NarrativeDecisionCommand, NarrativeDecisionAuthorization, int]
_AnyHead = RevisionAcceptanceHead | ChangeSetReviewHead | ConflictResolutionHead


def _fold_latest(decisions: Sequence[_StoredDecision]) -> tuple[str | None, int]:
    if not decisions:
        return None, 0
    latest_command, _, latest_generation = decisions[-1]
    return latest_command.decision_id, latest_generation


def _fold_effective(decisions: Sequence[_StoredDecision]) -> tuple[str | None, int]:
    effective_decision_id: str | None = None
    effective_generation = 0
    for command, _, generation in decisions:
        if command.action == ACCEPTING_ACTION[command.decision_family] or command.action == "SUPERSEDE":
            effective_decision_id = command.decision_id
            effective_generation = generation
    return effective_decision_id, effective_generation


class NarrativeLifecycleIntegrityChecker:
    def __init__(self, uow_factory: NarrativeLifecycleUnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def rebuild_revision_head(self, work_scope: NarrativeWorkScope) -> RevisionAcceptanceHead:
        async with self._uow_factory() as uow:
            decisions = await uow.repository.list_revision_decisions(work_scope)
        latest_decision_id, decision_generation = _fold_latest(decisions)
        effective_decision_id, effective_generation = _fold_effective(decisions)
        return RevisionAcceptanceHead(
            work_scope=work_scope,
            latest_decision_id=latest_decision_id,
            decision_generation=decision_generation,
            effective_decision_id=effective_decision_id,
            effective_generation=effective_generation,
        )

    async def rebuild_change_set_review_head(
        self, *, revision_acceptance_decision_id: str, change_set_lineage_id: str
    ) -> ChangeSetReviewHead:
        async with self._uow_factory() as uow:
            decisions = await uow.repository.list_change_set_review_decisions(
                revision_acceptance_decision_id=revision_acceptance_decision_id,
                change_set_lineage_id=change_set_lineage_id,
            )
        latest_decision_id, decision_generation = _fold_latest(decisions)
        effective_decision_id, effective_generation = _fold_effective(decisions)
        return ChangeSetReviewHead(
            revision_acceptance_decision_id=revision_acceptance_decision_id,
            change_set_lineage_id=change_set_lineage_id,
            latest_decision_id=latest_decision_id,
            decision_generation=decision_generation,
            effective_decision_id=effective_decision_id,
            effective_generation=effective_generation,
        )

    async def rebuild_conflict_resolution_head(
        self, *, revision_acceptance_decision_id: str, conflict_resolution_lineage_id: str
    ) -> ConflictResolutionHead:
        async with self._uow_factory() as uow:
            decisions = await uow.repository.list_conflict_resolution_decisions(
                revision_acceptance_decision_id=revision_acceptance_decision_id,
                conflict_resolution_lineage_id=conflict_resolution_lineage_id,
            )
        latest_decision_id, decision_generation = _fold_latest(decisions)
        effective_decision_id, effective_generation = _fold_effective(decisions)
        return ConflictResolutionHead(
            revision_acceptance_decision_id=revision_acceptance_decision_id,
            conflict_resolution_lineage_id=conflict_resolution_lineage_id,
            latest_decision_id=latest_decision_id,
            decision_generation=decision_generation,
            effective_decision_id=effective_decision_id,
            effective_generation=effective_generation,
        )

    async def verify_revision_head(self, work_scope: NarrativeWorkScope) -> RevisionAcceptanceHead:
        """Rebuild from the authoritative decision chain, compare against the stored
        (mutable) head, and return the verified head. Raises
        ``NarrativeAuthorityIntegrityError`` on any disagreement — including a stored
        head that is entirely absent while decisions already exist."""
        rebuilt = await self.rebuild_revision_head(work_scope)
        async with self._uow_factory() as uow:
            stored = await uow.repository.get_revision_head(work_scope)
        self._compare(rebuilt, stored, subject=f"revision acceptance head for {work_scope!r}")
        return rebuilt

    async def verify_change_set_review_head(
        self, *, revision_acceptance_decision_id: str, change_set_lineage_id: str, user_id: str, project_name: str
    ) -> ChangeSetReviewHead:
        rebuilt = await self.rebuild_change_set_review_head(
            revision_acceptance_decision_id=revision_acceptance_decision_id, change_set_lineage_id=change_set_lineage_id
        )
        async with self._uow_factory() as uow:
            stored = await uow.repository.get_change_set_review_head(
                revision_acceptance_decision_id=revision_acceptance_decision_id,
                change_set_lineage_id=change_set_lineage_id,
                user_id=user_id,
                project_name=project_name,
            )
        self._compare(
            rebuilt,
            stored,
            subject=f"change-set review head {(revision_acceptance_decision_id, change_set_lineage_id)!r}",
        )
        return rebuilt

    async def verify_conflict_resolution_head(
        self,
        *,
        revision_acceptance_decision_id: str,
        conflict_resolution_lineage_id: str,
        user_id: str,
        project_name: str,
    ) -> ConflictResolutionHead:
        rebuilt = await self.rebuild_conflict_resolution_head(
            revision_acceptance_decision_id=revision_acceptance_decision_id,
            conflict_resolution_lineage_id=conflict_resolution_lineage_id,
        )
        async with self._uow_factory() as uow:
            stored = await uow.repository.get_conflict_resolution_head(
                revision_acceptance_decision_id=revision_acceptance_decision_id,
                conflict_resolution_lineage_id=conflict_resolution_lineage_id,
                user_id=user_id,
                project_name=project_name,
            )
        self._compare(
            rebuilt,
            stored,
            subject=f"conflict resolution head {(revision_acceptance_decision_id, conflict_resolution_lineage_id)!r}",
        )
        return rebuilt

    @staticmethod
    def _compare(rebuilt: _AnyHead, stored: _AnyHead | None, *, subject: str) -> None:
        if stored is None:
            if rebuilt.latest_decision_id is None:
                return  # no decision has ever been appended -- absence, not disagreement
            raise NarrativeAuthorityIntegrityError(
                f"{subject}: decisions exist in the authoritative chain but no head row was ever created"
            )
        if rebuilt != stored:
            raise NarrativeAuthorityIntegrityError(
                f"{subject} disagrees with its authoritative decision chain: rebuilt {rebuilt!r}, stored {stored!r}"
            )
