"""Pure chain-fold and online-currentness primitives shared by every M6 adaptation
authority family (plan Task 7).

``fold_adaptation_head`` is the one pure helper both callers below build on: it takes
no repository, session, or clock, and re-derives a family's complete ``AdaptationHead``
projection from nothing but its own ordered decision chain — the same computation
whether run by a standalone auditor over decisions read outside any transaction, or by
``require_head_matches_fold`` below, run inside a live locked transaction immediately
after ``prepare_or_lock_head`` returns a stored head, before that head is trusted for
anything (a predecessor check, an effective-selection read). Mirrors
``r2.narrative_lifecycle.authority_kernel``'s transaction/retry/OCC shape as a pattern,
not a shared type: M6 is one generic family-agnostic head/decision pair instead of
M5C's three separately-typed ones, so there is no per-family repository method to call
through — every family goes through the same four ``AdaptationAuthorityRepositoryPort``
methods.
"""

from __future__ import annotations

from collections.abc import Sequence

from r2.adaptation.errors import AdaptationAuthorityIntegrityError
from r2.adaptation.ports import AdaptationAuthorityRepositoryPort
from r2.contracts.adaptation import (
    AdaptationAuthorityFamily,
    AdaptationDecision,
    AdaptationDecisionAction,
    AdaptationHead,
    ArtifactVersionRef,
    MapApprovalDecision,
    ProfileWaiverDecision,
    ScreenplayAdmissionDecision,
)

# The family's "select a new effective candidate" action, mirroring M5C's own
# ``ACCEPTING_ACTION`` map. REJECT and DENY_WAIVER do not retroactively clear a
# prior accepted selection. REVOKE is different: it explicitly removes current
# screenplay-use authority.
_ACCEPTING_ACTION: dict[AdaptationAuthorityFamily, AdaptationDecisionAction] = {
    AdaptationAuthorityFamily.MAP_APPROVAL: AdaptationDecisionAction.APPROVE,
    AdaptationAuthorityFamily.PROFILE_WAIVER: AdaptationDecisionAction.WAIVE,
    AdaptationAuthorityFamily.SCREENPLAY_ADMISSION: AdaptationDecisionAction.ADMIT,
}


_REJECTING_ACTION: dict[AdaptationAuthorityFamily, AdaptationDecisionAction] = {
    AdaptationAuthorityFamily.MAP_APPROVAL: AdaptationDecisionAction.REJECT,
    AdaptationAuthorityFamily.PROFILE_WAIVER: AdaptationDecisionAction.DENY_WAIVER,
    AdaptationAuthorityFamily.SCREENPLAY_ADMISSION: AdaptationDecisionAction.REVOKE,
}


def _family_of(decision: AdaptationDecision) -> AdaptationAuthorityFamily:
    if isinstance(decision, MapApprovalDecision):
        return AdaptationAuthorityFamily.MAP_APPROVAL
    if isinstance(decision, ProfileWaiverDecision):
        return AdaptationAuthorityFamily.PROFILE_WAIVER
    assert isinstance(decision, ScreenplayAdmissionDecision)
    return AdaptationAuthorityFamily.SCREENPLAY_ADMISSION


def _head_key_of(decision: AdaptationDecision) -> str:
    if isinstance(decision, MapApprovalDecision):
        return decision.command.branch_id
    if isinstance(decision, ProfileWaiverDecision):
        ref = decision.command.artifact_ref
        return f"{ref.artifact_id}:{ref.version}"
    assert isinstance(decision, ScreenplayAdmissionDecision)
    return decision.command.admitted_screenplay.screenplay_id


def _selected_artifact_ref_of(decision: AdaptationDecision) -> ArtifactVersionRef:
    if isinstance(decision, MapApprovalDecision):
        return decision.command.map_ref
    if isinstance(decision, ProfileWaiverDecision):
        return decision.command.artifact_ref
    assert isinstance(decision, ScreenplayAdmissionDecision)
    admitted = decision.command.admitted_screenplay
    return ArtifactVersionRef(
        artifact_id=admitted.screenplay_id, version=admitted.version, content_hash=admitted.content_hash
    )


def fold_adaptation_head(decisions: Sequence[AdaptationDecision]) -> AdaptationHead:
    """Re-derive one family's complete ``AdaptationHead`` from its ordered decision
    chain alone. Raises ``ValueError`` for an empty chain (``AdaptationHead.generation``
    can never be less than 1, so "no decisions yet" has no valid instance to return —
    callers represent that case as ``None`` instead, never by calling this with an
    empty sequence) and ``AdaptationAuthorityIntegrityError`` for any chain that is not
    a single family/head_key's own strictly sequential 1..N run.
    """
    if not decisions:
        raise ValueError("fold_adaptation_head requires at least one decision; an empty chain has no head")

    ordered = sorted(decisions, key=lambda decision: decision.sequence)
    for position, decision in enumerate(ordered, start=1):
        if decision.sequence != position:
            raise AdaptationAuthorityIntegrityError(
                f"decision chain is not sequential: expected sequence {position}, got {decision.sequence}"
            )

    first = ordered[0]
    family = _family_of(first)
    rejecting_action = _REJECTING_ACTION[family]
    head_key = _head_key_of(first)

    user_id = first.command.user_id
    project_name = first.command.project_name
    accepting_action = _ACCEPTING_ACTION[family]

    effective_decision_id: str | None = None
    selected_artifact_ref: ArtifactVersionRef | None = None
    for decision in ordered:
        command = decision.command
        if command.user_id != user_id or command.project_name != project_name:
            raise AdaptationAuthorityIntegrityError("decision chain mixes commands from different scopes")
        if _head_key_of(decision) != head_key:
            raise AdaptationAuthorityIntegrityError("decision chain mixes commands from different head keys")
        if command.action == accepting_action:
            effective_decision_id = command.decision_id
            selected_artifact_ref = _selected_artifact_ref_of(decision)
        elif command.action == rejecting_action:
            if family == AdaptationAuthorityFamily.SCREENPLAY_ADMISSION:
                effective_decision_id = None
                selected_artifact_ref = None
        else:
            raise AdaptationAuthorityIntegrityError(f"unexpected {family.value} action {command.action!r} in chain")

    return AdaptationHead(
        user_id=user_id,
        project_name=project_name,
        family=family,
        head_key=head_key,
        latest_decision_id=ordered[-1].command.decision_id,
        effective_decision_id=effective_decision_id,
        selected_artifact_ref=selected_artifact_ref,
        generation=len(ordered),
    )


async def verify_locked_adaptation_selection(
    repository: AdaptationAuthorityRepositoryPort,
    *,
    locked_head: AdaptationHead,
    expected_decision_id: str,
    expected_artifact_ref: ArtifactVersionRef,
) -> None:
    """The online currentness guard a *consumer* of an already-effective selection runs
    while holding that family's head lock (first real caller: Task 12's screenplay
    admission, verifying its named map approval is still effective). Folds the complete
    stored chain for ``locked_head``'s own ``(family, head_key)`` and requires it to
    reproduce ``locked_head`` exactly (catching a stored/rebuilt projection mismatch
    from any cause), then requires the reproduced effective selection to be exactly
    ``expected_decision_id``/``expected_artifact_ref``. Raises
    ``AdaptationAuthorityIntegrityError`` on either failure; grants nothing itself and
    repairs nothing.
    """
    decisions = await repository.list_decisions_for_locked_head(
        user_id=locked_head.user_id,
        project_name=locked_head.project_name,
        family=locked_head.family,
        head_key=locked_head.head_key,
    )
    require_head_matches_fold(decisions, locked_head)
    if (
        locked_head.effective_decision_id != expected_decision_id
        or locked_head.selected_artifact_ref != expected_artifact_ref
    ):
        raise AdaptationAuthorityIntegrityError(
            f"the current effective selection for {locked_head.family.value}/{locked_head.head_key!r} is "
            f"{locked_head.effective_decision_id!r}, not the expected {expected_decision_id!r}"
        )


def require_head_matches_fold(decisions: Sequence[AdaptationDecision], locked_head: AdaptationHead) -> None:
    """The self-consistency half of the online guard, factored out so
    ``AdaptationAuthorityService`` can run it alone (Task 7): a fresh head with no
    effective decision yet (only ``REJECT``s recorded) has no external selection for
    ``verify_locked_adaptation_selection`` to compare against, but its generation and
    predecessor chain still need the same corruption check."""
    rebuilt = fold_adaptation_head(decisions)
    if (
        rebuilt.generation != locked_head.generation
        or rebuilt.latest_decision_id != locked_head.latest_decision_id
        or rebuilt.effective_decision_id != locked_head.effective_decision_id
        or rebuilt.selected_artifact_ref != locked_head.selected_artifact_ref
    ):
        raise AdaptationAuthorityIntegrityError(
            f"stored head for {locked_head.family.value}/{locked_head.head_key!r} disagrees with its rebuilt "
            "decision-chain projection"
        )


__all__ = ["fold_adaptation_head", "require_head_matches_fold", "verify_locked_adaptation_selection"]
