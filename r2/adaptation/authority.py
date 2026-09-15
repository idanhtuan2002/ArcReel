"""``AdaptationAuthorityService`` — the sole append-only decision-authority surface for
M6 adaptation branches (plan Task 7). Only ``decide_map`` (the ``MAP_APPROVAL`` family)
is implemented here; ``decide_waiver`` and ``admit_screenplay_for_direction`` are added
by Tasks 11 and 12 respectively, extending this same class and the same generic
``AdaptationHead``/``AdaptationDecision`` machinery — no new head or decision shape.

**Applicability scope note (Task 7).** ``MapApprovalCommand.relied_report_refs``
references ``PROFILE_WAIVER``/evaluation-report decisions that do not exist until
Task 11 persists them; this service cannot verify any given ref actually resolves.
The one check it can make now, and does: a map that itself declares
``profile_analysis_refs`` (evidence it was analyzed) cannot be approved while relying
on zero reports — a coarse completeness proxy, not exact per-ref coverage, which
Task 11 replaces once report decisions exist to check against.
"""

from __future__ import annotations

from datetime import UTC, datetime

from r2.adaptation.authority_kernel import require_head_matches_fold
from r2.adaptation.errors import (
    AdaptationAuthorityDeniedError,
    AdaptationIdentityConflictError,
    AdaptationNotFoundError,
    AdaptationPolicyDigestMismatchError,
    AdaptationProfileMismatchError,
    AdaptationStaleDependencyError,
    AdaptationStaleHeadError,
)
from r2.adaptation.hashing import compute_command_identity_hash, compute_decision_identity_hash
from r2.adaptation.ports import AdaptationRepositoryPort, AdaptationShowrunnerAuthorityPort, AdaptationUnitOfWorkFactory
from r2.contracts.adaptation import (
    AdaptationAuthorityFamily,
    AdaptationDecisionAuthorization,
    AdaptationDecisionReceipt,
    DecisionRef,
    MapApprovalCommand,
    MapApprovalDecision,
)
from r2.contracts.enums import CreativeApprovalStatus


def _verify_authorization_binding(
    command: MapApprovalCommand, authorization: object, authenticated_principal: str
) -> None:
    if not isinstance(authorization, AdaptationDecisionAuthorization):
        raise AdaptationAuthorityDeniedError("the authority port returned an authorization of an unexpected shape")
    if authorization.action != command.action or authorization.authenticated_principal != authenticated_principal:
        raise AdaptationAuthorityDeniedError(
            "the authority port's authorization is not bound to this exact command and principal"
        )


async def _verify_map_applicability(repo: AdaptationRepositoryPort, command: MapApprovalCommand) -> None:
    branch = await repo.get_latest_branch_version(
        branch_id=command.branch_id, project_name=command.project_name, user_id=command.user_id
    )
    if branch is None:
        raise AdaptationNotFoundError(f"adaptation branch {command.branch_id!r} does not resolve in this scope")

    map_ref = command.map_ref
    map_ = await repo.get_exact_map(
        adaptation_map_id=map_ref.artifact_id,
        version=map_ref.version,
        project_name=command.project_name,
        user_id=command.user_id,
    )
    if map_ is None:
        raise AdaptationNotFoundError(f"adaptation map {map_ref.artifact_id!r} v{map_ref.version} does not resolve")
    if map_.content_hash != map_ref.content_hash:
        raise AdaptationStaleDependencyError(
            f"map approval command declares content hash {map_ref.content_hash!r} for map "
            f"{map_ref.artifact_id!r} v{map_ref.version}, but the stored hash is {map_.content_hash!r}"
        )
    if map_.adaptation_branch_ref.artifact_id != command.branch_id:
        raise AdaptationStaleDependencyError(
            f"map {map_ref.artifact_id!r} v{map_ref.version} belongs to branch "
            f"{map_.adaptation_branch_ref.artifact_id!r}, not the approved branch {command.branch_id!r}"
        )
    if map_.profile_analysis_refs and not command.relied_report_refs:
        raise AdaptationStaleDependencyError(
            f"map {map_ref.artifact_id!r} v{map_ref.version} carries profile analysis evidence, but the "
            "approval command relies on zero reports"
        )

    if command.profile_ref.profile_id != branch.profile_ref.profile_id:
        raise AdaptationProfileMismatchError(
            f"map approval command names profile {command.profile_ref.profile_id!r}, which disagrees with "
            f"branch {command.branch_id!r}'s bound profile {branch.profile_ref.profile_id!r}"
        )
    if command.profile_ref != branch.profile_ref:
        raise AdaptationPolicyDigestMismatchError(
            f"map approval command's profile ref {command.profile_ref!r} disagrees with branch "
            f"{command.branch_id!r}'s exact bound profile ref {branch.profile_ref!r}"
        )
    if any(entry.approval_status != CreativeApprovalStatus.APPROVED for entry in map_.entries):
        raise AdaptationStaleDependencyError(
            f"map {map_ref.artifact_id!r} v{map_ref.version} has at least one entry that is not yet "
            "APPROVED; whole-map approval requires complete entry evidence"
        )


class AdaptationAuthorityService:
    def __init__(self, uow_factory: AdaptationUnitOfWorkFactory, authority: AdaptationShowrunnerAuthorityPort) -> None:
        self._uow_factory = uow_factory
        self._authority = authority

    async def decide_map(
        self, command: MapApprovalCommand, *, authenticated_principal: str
    ) -> AdaptationDecisionReceipt:
        command_identity_hash = compute_command_identity_hash(command)
        async with self._uow_factory() as uow:
            repo = uow.repository

            stored = await repo.get_decision_by_id(
                user_id=command.user_id, project_name=command.project_name, decision_id=command.decision_id
            )
            if stored is not None:
                receipt = await self._resolve_exact_retry(repo, command, stored, authenticated_principal)
                await uow.commit()
                return receipt

            head = await repo.prepare_or_lock_head(
                user_id=command.user_id,
                project_name=command.project_name,
                family=AdaptationAuthorityFamily.MAP_APPROVAL,
                head_key=command.branch_id,
            )

            stored = await repo.get_decision_by_id(
                user_id=command.user_id, project_name=command.project_name, decision_id=command.decision_id
            )
            if stored is not None:
                receipt = await self._resolve_exact_retry(repo, command, stored, authenticated_principal)
                await uow.commit()
                return receipt

            if head is not None:
                decisions = await repo.list_decisions_for_locked_head(
                    user_id=command.user_id,
                    project_name=command.project_name,
                    family=AdaptationAuthorityFamily.MAP_APPROVAL,
                    head_key=command.branch_id,
                )
                require_head_matches_fold(decisions, head)

            actual_predecessor = head.latest_decision_id if head is not None else None
            if command.expected_predecessor_id != actual_predecessor:
                raise AdaptationStaleHeadError(
                    f"decision {command.decision_id!r} expected predecessor {command.expected_predecessor_id!r}, "
                    f"but branch {command.branch_id!r}'s current predecessor is {actual_predecessor!r}"
                )

            await _verify_map_applicability(repo, command)

            authorization = await self._authority.authorize(
                authenticated_principal=authenticated_principal,
                action=command.action,
                command_identity_hash=command_identity_hash,
            )
            _verify_authorization_binding(command, authorization, authenticated_principal)

            new_generation = (head.generation if head is not None else 0) + 1
            decision_digest = compute_decision_identity_hash(command, authorization)
            decision = MapApprovalDecision(
                command=command,
                authorization=authorization,
                sequence=new_generation,
                decision_digest=decision_digest,
                created_at=datetime.now(UTC),
            )
            await repo.append_decision_and_advance_head(
                decision, expected_generation=head.generation if head is not None else 0
            )
            await uow.commit()

            return AdaptationDecisionReceipt(
                decision_ref=DecisionRef(decision_id=command.decision_id, decision_digest=decision_digest),
                family=AdaptationAuthorityFamily.MAP_APPROVAL,
                head_key=command.branch_id,
                outcome="RECORDED",
                current_at_return=True,
            )

    async def _resolve_exact_retry(
        self,
        repo: AdaptationRepositoryPort,
        command: MapApprovalCommand,
        stored: object,
        authenticated_principal: str,
    ) -> AdaptationDecisionReceipt:
        if not isinstance(stored, MapApprovalDecision) or stored.command != command:
            raise AdaptationIdentityConflictError(
                f"decision {command.decision_id!r} was already recorded with a different command"
            )
        authorization = await self._authority.authorize(
            authenticated_principal=authenticated_principal,
            action=command.action,
            command_identity_hash=compute_command_identity_hash(command),
        )
        _verify_authorization_binding(command, authorization, authenticated_principal)

        head = await repo.prepare_or_lock_head(
            user_id=command.user_id,
            project_name=command.project_name,
            family=AdaptationAuthorityFamily.MAP_APPROVAL,
            head_key=command.branch_id,
        )
        current_at_return = head is not None and head.effective_decision_id == stored.command.decision_id
        return AdaptationDecisionReceipt(
            decision_ref=DecisionRef(decision_id=stored.command.decision_id, decision_digest=stored.decision_digest),
            family=AdaptationAuthorityFamily.MAP_APPROVAL,
            head_key=command.branch_id,
            outcome="EXACT_RETRY",
            current_at_return=current_at_return,
        )


__all__ = ["AdaptationAuthorityService"]
