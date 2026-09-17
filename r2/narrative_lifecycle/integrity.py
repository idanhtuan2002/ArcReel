"""``NarrativeLifecycleIntegrityChecker`` — rebuild for the M5C-2 decision-authority
heads (Task 21), plus the read-only evidence / compilation / handoff integrity sweep
this module completes (Task 30).

A current-selection guard never trusts a head pointer alone. This module recomputes
candidate head rows from the append-only typed decision chains into a
*separate* projection and compares that projection against the stored (mutable) head
before anything downstream is allowed to treat the stored head as authoritative. Every
``verify_*`` method raises a typed error — never silently repairs, never picks "the
latest" — the moment a rebuilt/recomputed projection disagrees with what is persisted,
or a persisted reference fails to resolve. Nothing in this module writes: repair, per the
spec's Global Constraint, requires an explicit offline procedure and evidence that M5C
implementation does not authorize running in production.

Pure rebuild rule, shared by every family: ``decision_generation`` is the generation of
the last decision in the append-order chain (zero, with a null pointer, for an empty
chain); ``effective_generation``/``effective_decision_id`` fold forward through the same
chain — an accepting action (``ACCEPT``/``RESOLVE``) or ``SUPERSEDE`` becomes the new
effective pointer at its own generation, and ``REJECT`` leaves the fold's running
effective pointer unchanged.

Task 30 extends the checker with everything spec section 12 requires beyond that
rebuild: evidence content-hash / fingerprint recomputation (draft candidates, revisions,
extraction attempts, compilation attempts), change-set-to-extraction-result and
compilation-result-to-compiled-delta binding, decision-chain walks that additionally
prove per-step predecessor consistency / scope consistency / historical authorization
binding (not just the final head, which Task 21 already covers), historical
conflict-resolution validity against immutable evidence, compilation recomputation via
the pure ``CanonDeltaCompiler`` compared against the persisted result, handoff-admission
binding, and referential sweeps proving no head or receipt names a decision, revision, or
change set that fails to resolve in its exact scope.
"""

from __future__ import annotations

from collections.abc import Sequence

from r2.contracts.narrative_lifecycle import (
    ChangeSetReviewCommand,
    ChangeSetReviewHead,
    CompilationAttempt,
    ConflictResolutionCommand,
    ConflictResolutionHead,
    DraftCandidate,
    ExtractionAttempt,
    NarrativeDecisionAuthorization,
    NarrativeDecisionCommand,
    NarrativeHandoffAdmission,
    NarrativeRevision,
    NarrativeWorkScope,
    RevisionAcceptanceCommand,
    RevisionAcceptanceHead,
)
from r2.narrative.hashing import compute_canon_delta_hash
from r2.narrative_lifecycle.authority_kernel import ACCEPTING_ACTION, _verify_authorization_binding
from r2.narrative_lifecycle.compiler import (
    CanonDeltaCompilation,
    CanonDeltaCompiler,
    CompilationOutputIdentity,
    CompilationSucceeded,
    CompilerPolicy,
    ExactCanonBase,
    ReviewedChangeSet,
)
from r2.narrative_lifecycle.errors import (
    NarrativeAuthorityIntegrityError,
    NarrativeDecisionNotFoundError,
    NarrativeEvidenceIntegrityError,
    NarrativeEvidenceNotFoundError,
)
from r2.narrative_lifecycle.hashing import (
    compute_canon_approval_binding_fingerprint,
    compute_compilation_input_fingerprint,
    compute_evidence_semantic_fingerprint,
    compute_extraction_input_fingerprint,
    compute_handoff_admission_identity_hash,
    compute_prose_content_hash,
)
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


def _verify_decision_chain(
    decisions: Sequence[_StoredDecision], *, user_id: str, project_name: str, subject: str
) -> tuple[str | None, int, str | None, int]:
    """Walks one subject's authoritative chain in append order and proves everything the
    fold-only rebuild above does not: no decision id repeats (acyclic), every decision's
    own command scope and its original authorization's scope agree with the exact
    ``(user_id, project_name)`` this chain is scoped to (scope-consistent), each
    decision's expected predecessors match the immediate persisted predecessor *at that
    exact point* in the chain -- not just the final head, which ``verify_*_head`` already
    proves -- and each decision's original authorization still binds its own stored
    actor/scope/family/action/decision-id/subject/command-fingerprint, historically, for
    every decision in the chain, not only the current one.

    Raises ``NarrativeAuthorityIntegrityError`` on the first disagreement. Returns the
    same ``(latest_decision_id, decision_generation, effective_decision_id,
    effective_generation)`` tuple ``_fold_latest``/``_fold_effective`` would, computed
    from the same validated walk.
    """
    seen: set[str] = set()
    latest_id: str | None = None
    effective_id: str | None = None
    for command, authorization, _generation in decisions:
        if command.decision_id in seen:
            raise NarrativeAuthorityIntegrityError(
                f"{subject}: decision {command.decision_id!r} appears more than once in the authoritative chain"
            )
        seen.add(command.decision_id)
        if command.work_scope.user_id != user_id or command.work_scope.project_name != project_name:
            raise NarrativeAuthorityIntegrityError(
                f"{subject}: decision {command.decision_id!r} command belongs to another (user_id, project_name) scope"
            )
        if authorization.user_id != user_id or authorization.project_name != project_name:
            raise NarrativeAuthorityIntegrityError(
                f"{subject}: decision {command.decision_id!r} authorization belongs to another "
                "(user_id, project_name) scope"
            )
        if command.expected_latest_decision_id != latest_id:
            raise NarrativeAuthorityIntegrityError(
                f"{subject}: decision {command.decision_id!r} names latest predecessor "
                f"{command.expected_latest_decision_id!r}, but the persisted chain's immediate predecessor "
                f"at this point is {latest_id!r}"
            )
        if command.expected_effective_decision_id != effective_id:
            raise NarrativeAuthorityIntegrityError(
                f"{subject}: decision {command.decision_id!r} names effective predecessor "
                f"{command.expected_effective_decision_id!r}, but the persisted chain's effective pointer "
                f"at this point is {effective_id!r}"
            )
        try:
            _verify_authorization_binding(command, authorization)
        except Exception as exc:
            raise NarrativeAuthorityIntegrityError(
                f"{subject}: decision {command.decision_id!r} original authorization no longer binds "
                f"its stored actor/scope/family/action/decision-id/subject/command-fingerprint: {exc}"
            ) from exc
        latest_id = command.decision_id
        if command.action == ACCEPTING_ACTION[command.decision_family] or command.action == "SUPERSEDE":
            effective_id = command.decision_id
    decision_generation = decisions[-1][2] if decisions else 0
    effective_generation = next(
        (generation for command, _, generation in reversed(decisions) if command.decision_id == effective_id),
        0,
    )
    return latest_id, decision_generation, effective_id, effective_generation


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

    # --- Task 30: decision-chain walks (predecessor consistency, scope consistency, ---
    # --- historical authorization binding), beyond the head-only rebuild above ---------

    async def verify_decision_identity_registration(
        self, decision_id: str, *, user_id: str, project_name: str
    ) -> NarrativeDecisionCommand:
        """The shared identity registry must name exactly one typed decision family with
        a real row in that family's table -- ``get_decision_by_id`` already raises
        ``NarrativeAuthorityIntegrityError`` the moment the registry names a family with
        no matching typed row; this is the checker's own documented surface for that
        same guarantee, for a caller that wants it as an explicit check rather than a
        side effect of some other read."""
        async with self._uow_factory() as uow:
            stored = await uow.repository.get_decision_by_id(decision_id, user_id=user_id, project_name=project_name)
        if stored is None:
            raise NarrativeDecisionNotFoundError(f"decision {decision_id!r} does not resolve in scope")
        return stored[0]

    async def verify_revision_decision_chain(self, work_scope: NarrativeWorkScope) -> RevisionAcceptanceHead:
        """Walks every ``REVISION_ACCEPTANCE`` decision for this exact subject and
        returns the rebuilt head, exactly as ``rebuild_revision_head`` would, but only
        after ``_verify_decision_chain`` has proven the whole chain acyclic, scope-
        consistent, per-step predecessor-consistent, and historically authorization-
        bound."""
        async with self._uow_factory() as uow:
            decisions = await uow.repository.list_revision_decisions(work_scope)
        latest_id, decision_generation, effective_id, effective_generation = _verify_decision_chain(
            decisions,
            user_id=work_scope.user_id,
            project_name=work_scope.project_name,
            subject=f"revision acceptance chain for {work_scope!r}",
        )
        return RevisionAcceptanceHead(
            work_scope=work_scope,
            latest_decision_id=latest_id,
            decision_generation=decision_generation,
            effective_decision_id=effective_id,
            effective_generation=effective_generation,
        )

    async def verify_change_set_review_decision_chain(
        self, *, revision_acceptance_decision_id: str, change_set_lineage_id: str, user_id: str, project_name: str
    ) -> ChangeSetReviewHead:
        """As ``verify_revision_decision_chain``, for one change-set-review lineage --
        plus the head-key check that its ``revision_acceptance_decision_id`` actually
        resolves to a ``REVISION_ACCEPTANCE`` decision in this exact scope."""
        async with self._uow_factory() as uow:
            repo = uow.repository
            revision_decision = await repo.get_decision_by_id(
                revision_acceptance_decision_id, user_id=user_id, project_name=project_name
            )
            if revision_decision is None or not isinstance(revision_decision[0], RevisionAcceptanceCommand):
                raise NarrativeAuthorityIntegrityError(
                    f"change-set review head key names revision acceptance {revision_acceptance_decision_id!r}, "
                    "which does not resolve to a revision-acceptance decision in this exact scope"
                )
            decisions = await repo.list_change_set_review_decisions(
                revision_acceptance_decision_id=revision_acceptance_decision_id,
                change_set_lineage_id=change_set_lineage_id,
            )
        latest_id, decision_generation, effective_id, effective_generation = _verify_decision_chain(
            decisions,
            user_id=user_id,
            project_name=project_name,
            subject=f"change-set review chain {(revision_acceptance_decision_id, change_set_lineage_id)!r}",
        )
        return ChangeSetReviewHead(
            revision_acceptance_decision_id=revision_acceptance_decision_id,
            change_set_lineage_id=change_set_lineage_id,
            latest_decision_id=latest_id,
            decision_generation=decision_generation,
            effective_decision_id=effective_id,
            effective_generation=effective_generation,
        )

    async def verify_conflict_resolution_decision_chain(
        self,
        *,
        revision_acceptance_decision_id: str,
        conflict_resolution_lineage_id: str,
        user_id: str,
        project_name: str,
    ) -> ConflictResolutionHead:
        """As ``verify_change_set_review_decision_chain``, for one conflict-resolution
        lineage."""
        async with self._uow_factory() as uow:
            repo = uow.repository
            revision_decision = await repo.get_decision_by_id(
                revision_acceptance_decision_id, user_id=user_id, project_name=project_name
            )
            if revision_decision is None or not isinstance(revision_decision[0], RevisionAcceptanceCommand):
                raise NarrativeAuthorityIntegrityError(
                    f"conflict-resolution head key names revision acceptance {revision_acceptance_decision_id!r}, "
                    "which does not resolve to a revision-acceptance decision in this exact scope"
                )
            decisions = await repo.list_conflict_resolution_decisions(
                revision_acceptance_decision_id=revision_acceptance_decision_id,
                conflict_resolution_lineage_id=conflict_resolution_lineage_id,
            )
        latest_id, decision_generation, effective_id, effective_generation = _verify_decision_chain(
            decisions,
            user_id=user_id,
            project_name=project_name,
            subject=(
                f"conflict resolution chain {(revision_acceptance_decision_id, conflict_resolution_lineage_id)!r}"
            ),
        )
        return ConflictResolutionHead(
            revision_acceptance_decision_id=revision_acceptance_decision_id,
            conflict_resolution_lineage_id=conflict_resolution_lineage_id,
            latest_decision_id=latest_id,
            decision_generation=decision_generation,
            effective_decision_id=effective_id,
            effective_generation=effective_generation,
        )

    async def verify_conflict_resolution_historical_validity(
        self, decision_id: str, *, user_id: str, project_name: str
    ) -> None:
        """Re-verifies, against what is persisted now, the immutable facts a
        conflict-resolution decision's write-time applicability check
        (``NarrativeAcceptanceService._verify_competitors``) already proved once at its
        append point: every named competing review decision still resolves, is a
        ``CHANGE_SET_REVIEW`` decision, selects the exact paired competing change set,
        and shares this resolution's exact scope and revision-acceptance basis -- plus
        that the named change set itself still resolves. None of these facts should ever
        change for an already-appended decision (the whole chain is append-only); this
        method's job is to catch it if one has.

        Deliberately distinct from ``NarrativeAcceptanceService.is_conflict_resolution_applicable``
        (*current* applicability), which additionally requires this resolution to be the
        effective conflict head and every named review to be *currently* effective --
        both of which legitimately change as later decisions are appended. This method
        never requires either: an old, no-longer-current resolution must still validate
        historically.
        """
        async with self._uow_factory() as uow:
            repo = uow.repository
            stored = await repo.get_decision_by_id(decision_id, user_id=user_id, project_name=project_name)
            if stored is None:
                raise NarrativeDecisionNotFoundError(f"conflict resolution {decision_id!r} does not resolve in scope")
            command = stored[0]
            if not isinstance(command, ConflictResolutionCommand):
                raise NarrativeAuthorityIntegrityError(
                    f"decision {decision_id!r} is not a conflict-resolution decision"
                )
            for change_set_id, review_decision_id in zip(
                command.competing_change_set_ids, command.competing_review_decision_ids, strict=True
            ):
                review_stored = await repo.get_decision_by_id(
                    review_decision_id, user_id=user_id, project_name=project_name
                )
                if review_stored is None:
                    raise NarrativeEvidenceIntegrityError(
                        f"conflict resolution {decision_id!r} names review decision {review_decision_id!r}, "
                        "which no longer resolves"
                    )
                review_command = review_stored[0]
                if (
                    not isinstance(review_command, ChangeSetReviewCommand)
                    or review_command.selected_change_set_id != change_set_id
                ):
                    raise NarrativeEvidenceIntegrityError(
                        f"conflict resolution {decision_id!r} names review decision {review_decision_id!r}, "
                        f"which no longer selects change set {change_set_id!r}"
                    )
                if (
                    review_command.work_scope != command.work_scope
                    or review_command.revision_acceptance_decision_id != command.revision_acceptance_decision_id
                ):
                    raise NarrativeEvidenceIntegrityError(
                        f"conflict resolution {decision_id!r} names review decision {review_decision_id!r}, "
                        "which no longer shares this resolution's exact scope and revision-acceptance basis"
                    )
                change_set = await repo.get_exact_change_set(
                    change_set_id=change_set_id, project_name=project_name, user_id=user_id
                )
                if change_set is None:
                    raise NarrativeEvidenceIntegrityError(
                        f"conflict resolution {decision_id!r} names change set {change_set_id!r}, "
                        "which no longer resolves"
                    )

    # --- Task 30: head-pointer referential integrity -----------------------------------

    async def verify_revision_head_references(self, work_scope: NarrativeWorkScope) -> None:
        """Neither the latest nor the effective pointer on a revision-acceptance head may
        name a decision that fails to resolve in this exact scope, or a revision that
        fails to resolve in this exact scope. ``selected_revision_id`` carries no
        database foreign key of its own (it is validated only once, at decision time), so
        this is a genuine post-write corruption this checker exists to catch."""
        async with self._uow_factory() as uow:
            repo = uow.repository
            head = await repo.get_revision_head(work_scope)
            if head is None:
                return
            for decision_id in {head.latest_decision_id, head.effective_decision_id}:
                if decision_id is None:
                    continue
                stored = await repo.get_decision_by_id(
                    decision_id, user_id=work_scope.user_id, project_name=work_scope.project_name
                )
                if stored is None:
                    raise NarrativeAuthorityIntegrityError(
                        f"revision acceptance head for {work_scope!r} points to decision {decision_id!r}, "
                        "which does not resolve in scope"
                    )
                command = stored[0]
                if not isinstance(command, RevisionAcceptanceCommand):
                    raise NarrativeAuthorityIntegrityError(
                        f"revision acceptance head for {work_scope!r} points to decision {decision_id!r}, "
                        "which is not a revision-acceptance decision"
                    )
                revision = await repo.get_exact_revision(
                    revision_id=command.selected_revision_id,
                    project_name=work_scope.project_name,
                    user_id=work_scope.user_id,
                )
                if revision is None:
                    raise NarrativeEvidenceIntegrityError(
                        f"revision acceptance decision {decision_id!r} selects revision "
                        f"{command.selected_revision_id!r}, which does not resolve in scope"
                    )

    async def verify_change_set_review_head_references(
        self, *, revision_acceptance_decision_id: str, change_set_lineage_id: str, user_id: str, project_name: str
    ) -> None:
        """As ``verify_revision_head_references``, for one change-set-review head:
        neither pointer may name a decision that fails to resolve, or a change set that
        fails to resolve. ``selected_change_set_id`` carries no database foreign key of
        its own, for the same reason."""
        async with self._uow_factory() as uow:
            repo = uow.repository
            head = await repo.get_change_set_review_head(
                revision_acceptance_decision_id=revision_acceptance_decision_id,
                change_set_lineage_id=change_set_lineage_id,
                user_id=user_id,
                project_name=project_name,
            )
            if head is None:
                return
            for decision_id in {head.latest_decision_id, head.effective_decision_id}:
                if decision_id is None:
                    continue
                stored = await repo.get_decision_by_id(decision_id, user_id=user_id, project_name=project_name)
                if stored is None:
                    raise NarrativeAuthorityIntegrityError(
                        f"change-set review head {(revision_acceptance_decision_id, change_set_lineage_id)!r} "
                        f"points to decision {decision_id!r}, which does not resolve in scope"
                    )
                command = stored[0]
                if not isinstance(command, ChangeSetReviewCommand):
                    raise NarrativeAuthorityIntegrityError(
                        f"change-set review head {(revision_acceptance_decision_id, change_set_lineage_id)!r} "
                        f"points to decision {decision_id!r}, which is not a change-set-review decision"
                    )
                change_set = await repo.get_exact_change_set(
                    change_set_id=command.selected_change_set_id, project_name=project_name, user_id=user_id
                )
                if change_set is None:
                    raise NarrativeEvidenceIntegrityError(
                        f"change-set review decision {decision_id!r} selects change set "
                        f"{command.selected_change_set_id!r}, which does not resolve in scope"
                    )

    async def verify_conflict_resolution_head_references(
        self,
        *,
        revision_acceptance_decision_id: str,
        conflict_resolution_lineage_id: str,
        user_id: str,
        project_name: str,
    ) -> None:
        """As ``verify_revision_head_references``, for one conflict-resolution head:
        neither pointer may name a decision that fails to resolve, or resolve to a
        decision that is not a conflict-resolution decision. The deeper check -- that the
        resolution's named competing reviews and change sets still resolve -- is
        ``verify_conflict_resolution_historical_validity``'s job, not duplicated here."""
        async with self._uow_factory() as uow:
            repo = uow.repository
            head = await repo.get_conflict_resolution_head(
                revision_acceptance_decision_id=revision_acceptance_decision_id,
                conflict_resolution_lineage_id=conflict_resolution_lineage_id,
                user_id=user_id,
                project_name=project_name,
            )
            if head is None:
                return
            for decision_id in {head.latest_decision_id, head.effective_decision_id}:
                if decision_id is None:
                    continue
                stored = await repo.get_decision_by_id(decision_id, user_id=user_id, project_name=project_name)
                if stored is None:
                    raise NarrativeAuthorityIntegrityError(
                        f"conflict resolution head "
                        f"{(revision_acceptance_decision_id, conflict_resolution_lineage_id)!r} points to decision "
                        f"{decision_id!r}, which does not resolve in scope"
                    )
                if not isinstance(stored[0], ConflictResolutionCommand):
                    raise NarrativeAuthorityIntegrityError(
                        f"conflict resolution head "
                        f"{(revision_acceptance_decision_id, conflict_resolution_lineage_id)!r} points to decision "
                        f"{decision_id!r}, which is not a conflict-resolution decision"
                    )

    # --- Task 30: evidence content-hash / fingerprint recomputation --------------------

    async def verify_draft_candidate_evidence(
        self, *, candidate_id: str, user_id: str, project_name: str
    ) -> DraftCandidate:
        """Recomputes a draft candidate's prose content hash and semantic fingerprint
        from its persisted exact tuple and compares -- never substitutes -- against what
        is stored."""
        async with self._uow_factory() as uow:
            candidate = await uow.repository.get_exact_draft_candidate(
                candidate_id=candidate_id, project_name=project_name, user_id=user_id
            )
        if candidate is None:
            raise NarrativeEvidenceNotFoundError(f"draft candidate {candidate_id!r} does not resolve in scope")
        if compute_prose_content_hash(candidate.normalized_content) != candidate.content_hash:
            raise NarrativeEvidenceIntegrityError(
                f"draft candidate {candidate_id!r} content_hash does not recompute from its normalized content"
            )
        if compute_evidence_semantic_fingerprint(candidate) != candidate.semantic_fingerprint:
            raise NarrativeEvidenceIntegrityError(
                f"draft candidate {candidate_id!r} semantic_fingerprint does not recompute from its exact tuple"
            )
        return candidate

    async def verify_revision_evidence(self, *, revision_id: str, user_id: str, project_name: str) -> NarrativeRevision:
        """As ``verify_draft_candidate_evidence``, for one narrative revision."""
        async with self._uow_factory() as uow:
            revision = await uow.repository.get_exact_revision(
                revision_id=revision_id, project_name=project_name, user_id=user_id
            )
        if revision is None:
            raise NarrativeEvidenceNotFoundError(f"narrative revision {revision_id!r} does not resolve in scope")
        if compute_prose_content_hash(revision.normalized_content) != revision.content_hash:
            raise NarrativeEvidenceIntegrityError(
                f"narrative revision {revision_id!r} content_hash does not recompute from its normalized content"
            )
        if compute_evidence_semantic_fingerprint(revision) != revision.semantic_fingerprint:
            raise NarrativeEvidenceIntegrityError(
                f"narrative revision {revision_id!r} semantic_fingerprint does not recompute from its exact tuple"
            )
        return revision

    async def verify_extraction_evidence(
        self, *, attempt_id: str, generation: int, user_id: str, project_name: str
    ) -> ExtractionAttempt:
        """Recomputes an admitted extraction attempt's input fingerprint from its exact
        revision content hash and extractor/policy identity, requires the attempt's
        named revision to resolve in scope, and -- for a ``SUCCEEDED`` result at this
        exact generation -- requires every named change set to resolve in scope and to
        belong to this exact attempt generation."""
        async with self._uow_factory() as uow:
            repo = uow.repository
            attempt = await repo.get_exact_extraction_attempt(
                attempt_id=attempt_id, project_name=project_name, user_id=user_id
            )
            if attempt is None:
                raise NarrativeEvidenceNotFoundError(f"extraction attempt {attempt_id!r} does not resolve in scope")
            revision = await repo.get_exact_revision(
                revision_id=attempt.revision_id, project_name=project_name, user_id=user_id
            )
            if revision is None:
                raise NarrativeEvidenceIntegrityError(
                    f"extraction attempt {attempt_id!r} names revision {attempt.revision_id!r}, "
                    "which does not resolve in scope"
                )
            recomputed_fingerprint = compute_extraction_input_fingerprint(
                revision_content_hash=revision.content_hash,
                extractor_kind=attempt.extractor_kind,
                extractor_version=attempt.extractor_version,
                policy_ref=attempt.policy_ref,
                policy_version=attempt.policy_version,
            )
            if recomputed_fingerprint != attempt.input_fingerprint:
                raise NarrativeEvidenceIntegrityError(
                    f"extraction attempt {attempt_id!r} input_fingerprint does not recompute from its exact inputs"
                )
            result = await repo.get_exact_extraction_result(
                attempt_id=attempt_id, generation=generation, project_name=project_name, user_id=user_id
            )
            if result is not None and result.outcome == "SUCCEEDED":
                for change_set_id in result.change_set_ids:
                    change_set = await repo.get_exact_change_set(
                        change_set_id=change_set_id, project_name=project_name, user_id=user_id
                    )
                    if change_set is None:
                        raise NarrativeEvidenceIntegrityError(
                            f"extraction result {result.result_id!r} names change set {change_set_id!r}, "
                            "which does not resolve in scope"
                        )
                    if (change_set.extraction_attempt_id, change_set.extraction_generation) != (
                        attempt_id,
                        generation,
                    ):
                        raise NarrativeEvidenceIntegrityError(
                            f"change set {change_set_id!r} does not belong to extraction attempt {attempt_id!r} "
                            f"generation {generation}"
                        )
        return attempt

    # --- Task 30: compilation result / compiled-delta cardinality and recomputation ----

    async def verify_compilation_result_evidence(
        self, *, attempt_id: str, generation: int, user_id: str, project_name: str
    ) -> CompilationAttempt:
        """Recomputes a compilation attempt's input fingerprint and, for the result
        recorded (if any) at this exact generation, requires the compiled-delta-row
        cardinality rule to hold against what is persisted: a ``SUCCEEDED`` result owns
        exactly one compiled-delta row, bound to this exact attempt/generation and to the
        result's own payload hash (itself re-verified against the M5A hash recomputed
        from the embedded delta); every other outcome owns none."""
        async with self._uow_factory() as uow:
            repo = uow.repository
            attempt = await repo.get_exact_compilation_attempt(
                attempt_id=attempt_id, project_name=project_name, user_id=user_id
            )
            if attempt is None:
                raise NarrativeEvidenceNotFoundError(f"compilation attempt {attempt_id!r} does not resolve in scope")
            recomputed_fingerprint = compute_compilation_input_fingerprint(attempt)
            if recomputed_fingerprint != attempt.input_fingerprint:
                raise NarrativeEvidenceIntegrityError(
                    f"compilation attempt {attempt_id!r} input_fingerprint does not recompute from its exact inputs"
                )
            result = await repo.get_exact_compilation_result(
                attempt_id=attempt_id, generation=generation, project_name=project_name, user_id=user_id
            )
            if result is None:
                return attempt
            evidence = await repo.get_exact_compiled_canon_delta(
                compilation_result_id=result.result_id, project_name=project_name, user_id=user_id
            )
            if result.outcome == "SUCCEEDED":
                if evidence is None:
                    raise NarrativeEvidenceIntegrityError(
                        f"compilation result {result.result_id!r} is SUCCEEDED but owns no compiled-delta row"
                    )
                if evidence.compilation_attempt_id != attempt_id or evidence.generation != generation:
                    raise NarrativeEvidenceIntegrityError(
                        f"the compiled-delta row for result {result.result_id!r} belongs to another attempt "
                        "or generation"
                    )
                if evidence.canon_delta_payload_hash != result.canon_delta_payload_hash:
                    raise NarrativeEvidenceIntegrityError(
                        f"the compiled-delta row for result {result.result_id!r} disagrees with the result's "
                        "own payload hash"
                    )
                if compute_canon_delta_hash(evidence.canon_delta) != evidence.canon_delta_payload_hash:
                    raise NarrativeEvidenceIntegrityError(
                        f"the compiled delta for result {result.result_id!r} does not recompute to its own payload hash"
                    )
            elif evidence is not None:
                raise NarrativeEvidenceIntegrityError(
                    f"compilation result {result.result_id!r} is {result.outcome} but owns a compiled-delta row"
                )
        return attempt

    async def verify_compilation_recompute(
        self,
        *,
        attempt_id: str,
        generation: int,
        user_id: str,
        project_name: str,
        exact_canon_base: ExactCanonBase,
        compiler_policy: CompilerPolicy,
    ) -> CanonDeltaCompilation:
        """Recompiles one attempt's exact persisted inputs through the pure
        ``CanonDeltaCompiler`` and compares -- never substitutes -- the recomputed
        outcome against the persisted ``CompilationResult``. The compiler holds no I/O of
        its own, so ``exact_canon_base`` (Canon branch/base/content-schema) and
        ``compiler_policy`` (the exact creative policy the attempt names) must come from
        the caller, exactly as the real compilation workflow supplies them; this method
        invents neither. A ``NO_CANON_MUTATION`` persisted result that recomputes
        successfully is thereby proven to have been a complete, valid, outcome-only
        selection at compile time -- not merely re-asserted from the stored row."""
        async with self._uow_factory() as uow:
            repo = uow.repository
            attempt = await repo.get_exact_compilation_attempt(
                attempt_id=attempt_id, project_name=project_name, user_id=user_id
            )
            if attempt is None:
                raise NarrativeEvidenceNotFoundError(f"compilation attempt {attempt_id!r} does not resolve in scope")
            result = await repo.get_exact_compilation_result(
                attempt_id=attempt_id, generation=generation, project_name=project_name, user_id=user_id
            )
            if result is None:
                raise NarrativeEvidenceNotFoundError(
                    f"no compilation result is recorded for attempt {attempt_id!r} generation {generation}"
                )
            revision = await repo.get_exact_revision(
                revision_id=attempt.revision_id, project_name=project_name, user_id=user_id
            )
            if revision is None:
                raise NarrativeEvidenceIntegrityError(
                    f"compilation attempt {attempt_id!r} names revision {attempt.revision_id!r}, "
                    "which does not resolve in scope"
                )
            reviewed_change_sets: list[ReviewedChangeSet] = []
            for selected in attempt.selected_change_sets:
                change_set = await repo.get_exact_change_set(
                    change_set_id=selected.change_set_id, project_name=project_name, user_id=user_id
                )
                if change_set is None:
                    raise NarrativeEvidenceIntegrityError(
                        f"compilation attempt {attempt_id!r} selects change set {selected.change_set_id!r}, "
                        "which does not resolve in scope"
                    )
                reviewed_change_sets.append(
                    ReviewedChangeSet(change_set=change_set, review_decision_id=selected.review_decision_id)
                )
            conflict_resolutions: list[ConflictResolutionCommand] = []
            for decision_id in attempt.conflict_resolution_decision_ids:
                stored = await repo.get_decision_by_id(decision_id, user_id=user_id, project_name=project_name)
                if stored is None or not isinstance(stored[0], ConflictResolutionCommand):
                    raise NarrativeEvidenceIntegrityError(
                        f"compilation attempt {attempt_id!r} names conflict resolution {decision_id!r}, "
                        "which does not resolve to a conflict-resolution decision in scope"
                    )
                conflict_resolutions.append(stored[0])
            output_identity = CompilationOutputIdentity.from_attempt(
                attempt, expected_payload_hash=result.canon_delta_payload_hash
            )
            recomputed = CanonDeltaCompiler().compile(
                output_identity,
                revision,
                reviewed_change_sets,
                conflict_resolutions,
                exact_canon_base,
                compiler_policy,
            )
        if recomputed.outcome != result.outcome:
            raise NarrativeEvidenceIntegrityError(
                f"compilation result {result.result_id!r} recomputes to outcome {recomputed.outcome!r}, "
                f"not the persisted {result.outcome!r}"
            )
        if (
            isinstance(recomputed, CompilationSucceeded)
            and recomputed.canon_delta.payload_hash != result.canon_delta_payload_hash
        ):
            raise NarrativeEvidenceIntegrityError(
                f"compilation result {result.result_id!r} recomputes to a different payload hash than persisted"
            )
        return recomputed

    # --- Task 30: handoff-admission binding ---------------------------------------------

    async def verify_handoff_admission_evidence(
        self, *, admission_id: str, user_id: str, project_name: str
    ) -> NarrativeHandoffAdmission:
        """Requires a handoff admission to bind the exact successful compilation result
        it names, the exact persisted compiled-delta hash/id, and the exact lossless M5A
        approval payload -- by recomputing the approval-binding fingerprint and the
        admission's own canonical identity hash and comparing both against what is
        stored."""
        async with self._uow_factory() as uow:
            repo = uow.repository
            admission = await repo.get_exact_handoff_admission(
                admission_id=admission_id, project_name=project_name, user_id=user_id
            )
            if admission is None:
                raise NarrativeEvidenceNotFoundError(f"handoff admission {admission_id!r} does not resolve in scope")
            result = await repo.get_exact_compilation_result(
                attempt_id=admission.compilation_attempt_id,
                generation=admission.generation,
                project_name=project_name,
                user_id=user_id,
            )
            if result is None or result.result_id != admission.compilation_result_id:
                raise NarrativeEvidenceIntegrityError(
                    f"handoff admission {admission_id!r} names compilation result "
                    f"{admission.compilation_result_id!r}, which is not the result recorded for its exact "
                    "attempt generation"
                )
            if result.outcome != "SUCCEEDED":
                raise NarrativeEvidenceIntegrityError(
                    f"handoff admission {admission_id!r} admits a {result.outcome} compilation result"
                )
            evidence = await repo.get_exact_compiled_canon_delta(
                compilation_result_id=admission.compilation_result_id, project_name=project_name, user_id=user_id
            )
            if evidence is None or evidence.canon_delta_payload_hash != admission.canon_delta_payload_hash:
                raise NarrativeEvidenceIntegrityError(
                    f"handoff admission {admission_id!r} does not bind its exact persisted compiled-delta payload hash"
                )
            if evidence.canon_delta.canon_delta_id != admission.canon_delta_id:
                raise NarrativeEvidenceIntegrityError(
                    f"handoff admission {admission_id!r} does not bind its exact persisted canon delta id"
                )
        recomputed_approval_fingerprint = compute_canon_approval_binding_fingerprint(admission.canon_commit_approval)
        if recomputed_approval_fingerprint != admission.canon_commit_approval_fingerprint:
            raise NarrativeEvidenceIntegrityError(
                f"handoff admission {admission_id!r} canon_commit_approval_fingerprint does not recompute "
                "from its embedded approval"
            )
        recomputed_identity_hash = compute_handoff_admission_identity_hash(admission)
        if recomputed_identity_hash != admission.canonical_identity_hash:
            raise NarrativeEvidenceIntegrityError(
                f"handoff admission {admission_id!r} canonical_identity_hash does not recompute from its exact tuple"
            )
        return admission
