"""``AdaptationAuthorityService`` — the sole append-only decision-authority surface for
M6 adaptation branches (plan Tasks 7, 11 and 12). ``decide_map`` (``MAP_APPROVAL``),
``decide_waiver`` (``PROFILE_WAIVER``) and ``admit_screenplay_for_direction``
(``SCREENPLAY_ADMISSION``) are all implemented here, extending the same generic
``AdaptationHead``/``AdaptationDecision`` machinery — no new head or decision shape.

**Applicability scope note (Task 7, narrowed by Task 11).** ``decide_waiver`` proves a
waiver command actually applies before it is recorded: its named
``ProfileEvaluationReport`` (``ProfileWaiverCommand.report_ref``) must resolve, must
have evaluated exactly ``command.artifact_ref``'s current content under exactly
``command.profile_ref``, and every named finding must exist in that report with a
matching ``rule_version`` and a waivable disposition (never ``INTEGRITY_BLOCK``). This
is what ``MapApprovalCommand.relied_report_refs`` still cannot get from this service —
whole-map per-ref report coverage remains the Task 7 coarse completeness proxy (a map
declaring ``profile_analysis_refs`` cannot rely on zero reports) until a later task
needs it.

**Admission note (Task 12).** ``admit_screenplay_for_direction`` never trusts
``ScreenplayAdmissionCommand.admitted_screenplay`` as free-form input: it re-derives
the exact legal N+1 snapshot from the stored proposal N (every field equal to N except
``approval_status`` -> ``APPROVED`` and ``locked_for_direction`` -> ``True``) and
requires byte-for-byte equality before anything is written — a content edit between
evaluation and admission is rejected here, not merely by a stale content-hash check.
It also re-resolves the named map approval and every waiver under their own locked
heads (``verify_locked_adaptation_selection``), so a superseded approval or waiver
cannot be replayed to sneak an admission through.
"""

from __future__ import annotations

from datetime import UTC, datetime

from r2.adaptation.authority_kernel import require_head_matches_fold, verify_locked_adaptation_selection
from r2.adaptation.errors import (
    AdaptationAuthorityDeniedError,
    AdaptationBlockingFindingUnresolvedError,
    AdaptationIdentityConflictError,
    AdaptationNotFoundError,
    AdaptationPolicyDigestMismatchError,
    AdaptationProfileMismatchError,
    AdaptationStaleDependencyError,
    AdaptationStaleHeadError,
    AdaptationWaiverNotApplicableError,
)
from r2.adaptation.hashing import compute_adaptation_hash, compute_command_identity_hash, compute_decision_identity_hash
from r2.adaptation.ports import AdaptationRepositoryPort, AdaptationShowrunnerAuthorityPort, AdaptationUnitOfWorkFactory
from r2.contracts.adaptation import (
    AdaptationAuthorityFamily,
    AdaptationDecisionAction,
    AdaptationDecisionAuthorization,
    AdaptationDecisionReceipt,
    ArtifactVersionRef,
    DecisionRef,
    FindingDisposition,
    MapApprovalCommand,
    MapApprovalDecision,
    ProfileWaiverCommand,
    ProfileWaiverDecision,
    ScreenplayAdmissionCommand,
    ScreenplayAdmissionDecision,
    ScreenplayArtifactV2,
)
from r2.contracts.enums import CreativeApprovalStatus


def _verify_authorization_binding(
    command: MapApprovalCommand | ProfileWaiverCommand | ScreenplayAdmissionCommand,
    authorization: object,
    authenticated_principal: str,
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


async def _verify_waiver_applicability(repo: AdaptationRepositoryPort, command: ProfileWaiverCommand) -> None:
    report = await repo.get_exact_report(
        report_digest=command.report_ref.decision_id, project_name=command.project_name, user_id=command.user_id
    )
    if report is None:
        raise AdaptationNotFoundError(f"evaluation report {command.report_ref.decision_id!r} does not resolve")
    if report.report_digest != command.report_ref.decision_digest:
        raise AdaptationWaiverNotApplicableError(
            f"waiver command names report digest {command.report_ref.decision_digest!r}, but the resolved "
            f"report's own digest is {report.report_digest!r}"
        )
    if report.artifact_hash != command.artifact_ref.content_hash:
        raise AdaptationWaiverNotApplicableError(
            f"report {command.report_ref.decision_id!r} evaluated artifact content {report.artifact_hash!r}, "
            f"which disagrees with the waiver command's exact artifact content {command.artifact_ref.content_hash!r} "
            "-- a semantic change invalidates any prior waiver of this report"
        )
    if report.profile_ref != command.profile_ref:
        raise AdaptationWaiverNotApplicableError(
            f"report {command.report_ref.decision_id!r} was evaluated against profile {report.profile_ref!r}, "
            f"which disagrees with the waiver command's exact profile {command.profile_ref!r}"
        )

    findings_by_id = {finding.finding_id: finding for finding in report.findings}
    for finding_id, rule_version in zip(command.finding_ids, command.rule_versions, strict=True):
        finding = findings_by_id.get(finding_id)
        if finding is None:
            raise AdaptationWaiverNotApplicableError(
                f"report {command.report_ref.decision_id!r} does not contain finding {finding_id!r}"
            )
        if finding.rule_version != rule_version:
            raise AdaptationWaiverNotApplicableError(
                f"finding {finding_id!r} is at rule version {finding.rule_version!r} in the resolved report, not "
                f"the waiver command's declared {rule_version!r}"
            )
        if finding.disposition == FindingDisposition.INTEGRITY_BLOCK:
            raise AdaptationWaiverNotApplicableError(
                f"finding {finding_id!r} is an INTEGRITY_BLOCK finding, which is never waivable"
            )


def _derive_admitted_screenplay(proposal: ScreenplayArtifactV2) -> ScreenplayArtifactV2:
    """The one legal N+1 shape for admitting proposal N: every field equal to N except
    ``version`` (+1), ``approval_status`` (``APPROVED``) and ``locked_for_direction``
    (``True``); ``content_hash`` is recomputed over that exact tuple. A command whose
    ``admitted_screenplay`` disagrees with this by even one byte is rejected before any
    write — this is the "deep-snapshot and rehash" the plan requires, not a bare
    content-hash comparison."""
    draft = proposal.model_copy(
        update={
            "version": proposal.version + 1,
            "approval_status": CreativeApprovalStatus.APPROVED,
            "locked_for_direction": True,
            "content_hash": "pending",
        }
    )
    return draft.model_copy(update={"content_hash": compute_adaptation_hash(draft)})


async def _verify_admission_applicability(repo: AdaptationRepositoryPort, command: ScreenplayAdmissionCommand) -> None:
    proposal_ref = command.proposal_ref
    proposal = await repo.get_exact_screenplay(
        screenplay_id=proposal_ref.artifact_id,
        version=proposal_ref.version,
        project_name=command.project_name,
        user_id=command.user_id,
    )
    if proposal is None:
        raise AdaptationNotFoundError(
            f"screenplay proposal {proposal_ref.artifact_id!r} v{proposal_ref.version} does not resolve"
        )
    if proposal.content_hash != proposal_ref.content_hash:
        raise AdaptationStaleDependencyError(
            f"admission command declares content hash {proposal_ref.content_hash!r} for proposal "
            f"{proposal_ref.artifact_id!r} v{proposal_ref.version}, but the stored hash is {proposal.content_hash!r}"
        )
    if proposal.locked_for_direction:
        raise AdaptationStaleDependencyError(
            f"screenplay {proposal_ref.artifact_id!r} v{proposal_ref.version} is already locked for direction; "
            "an admitted screenplay is a terminal state and is never the source proposal of a new admission"
        )
    if command.admitted_screenplay.screenplay_id != proposal.screenplay_id:
        raise AdaptationStaleDependencyError(
            f"admission command's admitted_screenplay names screenplay id "
            f"{command.admitted_screenplay.screenplay_id!r}, which disagrees with proposal id "
            f"{proposal.screenplay_id!r}"
        )

    branch = await repo.get_latest_branch_version(
        branch_id=proposal.adaptation_branch_ref.artifact_id, project_name=command.project_name, user_id=command.user_id
    )
    if branch is None:
        raise AdaptationNotFoundError(
            f"adaptation branch {proposal.adaptation_branch_ref.artifact_id!r} does not resolve in this scope"
        )
    if command.branch_id != proposal.adaptation_branch_ref.artifact_id:
        raise AdaptationStaleDependencyError(
            f"admission command names branch {command.branch_id!r}, which disagrees with proposal "
            f"{proposal_ref.artifact_id!r}'s own branch {proposal.adaptation_branch_ref.artifact_id!r}"
        )
    if command.profile_ref.profile_id != branch.profile_ref.profile_id:
        raise AdaptationProfileMismatchError(
            f"admission command names profile {command.profile_ref.profile_id!r}, which disagrees with branch "
            f"{command.branch_id!r}'s bound profile {branch.profile_ref.profile_id!r}"
        )
    if command.profile_ref != branch.profile_ref:
        raise AdaptationPolicyDigestMismatchError(
            f"admission command's profile ref {command.profile_ref!r} disagrees with branch "
            f"{command.branch_id!r}'s exact bound profile ref {branch.profile_ref!r}"
        )

    expected = _derive_admitted_screenplay(proposal)
    if command.admitted_screenplay != expected:
        raise AdaptationStaleDependencyError(
            f"admission command's admitted_screenplay for {proposal_ref.artifact_id!r} is not the exact N+1 "
            "snapshot derived from its proposal -- only approval_status and locked_for_direction may change "
            "between proposal and admission; a content edit requires a new proposal before admission"
        )

    map_decision = await repo.get_decision_by_id(
        user_id=command.user_id,
        project_name=command.project_name,
        decision_id=command.effective_map_approval_ref.decision_id,
    )
    if map_decision is None or not isinstance(map_decision, MapApprovalDecision):
        raise AdaptationNotFoundError(
            f"map approval decision {command.effective_map_approval_ref.decision_id!r} does not resolve"
        )
    if map_decision.decision_digest != command.effective_map_approval_ref.decision_digest:
        raise AdaptationStaleDependencyError(
            f"admission command names map approval digest {command.effective_map_approval_ref.decision_digest!r}, "
            f"but the resolved decision's own digest is {map_decision.decision_digest!r}"
        )
    if map_decision.command.branch_id != command.branch_id:
        raise AdaptationStaleDependencyError(
            f"map approval decision {command.effective_map_approval_ref.decision_id!r} belongs to branch "
            f"{map_decision.command.branch_id!r}, not the admission's own branch {command.branch_id!r}"
        )
    if map_decision.command.map_ref.artifact_id != proposal.adaptation_map_ref.artifact_id:
        raise AdaptationStaleDependencyError(
            f"map approval decision {command.effective_map_approval_ref.decision_id!r} approved map "
            f"{map_decision.command.map_ref.artifact_id!r}, not the proposal's own bound map "
            f"{proposal.adaptation_map_ref.artifact_id!r}"
        )
    map_head = await repo.prepare_or_lock_head(
        user_id=command.user_id,
        project_name=command.project_name,
        family=AdaptationAuthorityFamily.MAP_APPROVAL,
        head_key=command.branch_id,
    )
    if map_head is None:
        raise AdaptationStaleDependencyError(f"branch {command.branch_id!r} has no map approval head")
    await verify_locked_adaptation_selection(
        repo,
        locked_head=map_head,
        expected_decision_id=map_decision.command.decision_id,
        expected_artifact_ref=map_decision.command.map_ref,
    )

    blocking_findings: dict[str, FindingDisposition] = {}
    for report_ref in command.report_refs:
        report = await repo.get_exact_report(
            report_digest=report_ref.decision_id, project_name=command.project_name, user_id=command.user_id
        )
        if report is None:
            raise AdaptationNotFoundError(f"evaluation report {report_ref.decision_id!r} does not resolve")
        if report.report_digest != report_ref.decision_digest:
            raise AdaptationStaleDependencyError(
                f"admission command names report digest {report_ref.decision_digest!r}, but the resolved "
                f"report's own digest is {report.report_digest!r}"
            )
        if report.artifact_hash != proposal.content_hash:
            raise AdaptationStaleDependencyError(
                f"report {report_ref.decision_id!r} evaluated artifact content {report.artifact_hash!r}, which "
                f"disagrees with proposal {proposal_ref.artifact_id!r}'s exact content {proposal.content_hash!r}"
            )
        if report.profile_ref != command.profile_ref:
            raise AdaptationProfileMismatchError(
                f"report {report_ref.decision_id!r} was evaluated against profile {report.profile_ref!r}, which "
                f"disagrees with the admission command's exact profile {command.profile_ref!r}"
            )
        for finding in report.findings:
            if finding.disposition in (FindingDisposition.INTEGRITY_BLOCK, FindingDisposition.PROFILE_BLOCK):
                blocking_findings[finding.finding_id] = finding.disposition

    if any(disposition == FindingDisposition.INTEGRITY_BLOCK for disposition in blocking_findings.values()):
        raise AdaptationBlockingFindingUnresolvedError(
            "at least one dependency report carries an INTEGRITY_BLOCK finding, which is never waivable"
        )

    covered_finding_ids: set[str] = set()
    for waiver_ref in command.waiver_refs:
        waiver_decision = await repo.get_decision_by_id(
            user_id=command.user_id, project_name=command.project_name, decision_id=waiver_ref.decision_id
        )
        if waiver_decision is None or not isinstance(waiver_decision, ProfileWaiverDecision):
            raise AdaptationWaiverNotApplicableError(f"waiver decision {waiver_ref.decision_id!r} does not resolve")
        if waiver_decision.decision_digest != waiver_ref.decision_digest:
            raise AdaptationWaiverNotApplicableError(
                f"admission command names waiver digest {waiver_ref.decision_digest!r}, but the resolved "
                f"decision's own digest is {waiver_decision.decision_digest!r}"
            )
        if waiver_decision.command.action != AdaptationDecisionAction.WAIVE:
            raise AdaptationWaiverNotApplicableError(
                f"waiver decision {waiver_ref.decision_id!r} is a {waiver_decision.command.action.value}, not a "
                "WAIVE decision"
            )
        if waiver_decision.command.artifact_ref.content_hash != proposal.content_hash:
            raise AdaptationWaiverNotApplicableError(
                f"waiver decision {waiver_ref.decision_id!r} targets content "
                f"{waiver_decision.command.artifact_ref.content_hash!r}, which disagrees with proposal "
                f"{proposal_ref.artifact_id!r}'s exact content {proposal.content_hash!r}"
            )
        if waiver_decision.command.profile_ref != command.profile_ref:
            raise AdaptationWaiverNotApplicableError(
                f"waiver decision {waiver_ref.decision_id!r} targets profile "
                f"{waiver_decision.command.profile_ref!r}, which disagrees with the admission command's exact "
                f"profile {command.profile_ref!r}"
            )
        waiver_artifact_ref: ArtifactVersionRef = waiver_decision.command.artifact_ref
        waiver_head_key = f"{waiver_artifact_ref.artifact_id}:{waiver_artifact_ref.version}"
        waiver_head = await repo.prepare_or_lock_head(
            user_id=command.user_id,
            project_name=command.project_name,
            family=AdaptationAuthorityFamily.PROFILE_WAIVER,
            head_key=waiver_head_key,
        )
        if waiver_head is None:
            raise AdaptationWaiverNotApplicableError(f"waiver decision {waiver_ref.decision_id!r} has no waiver head")
        await verify_locked_adaptation_selection(
            repo,
            locked_head=waiver_head,
            expected_decision_id=waiver_decision.command.decision_id,
            expected_artifact_ref=waiver_artifact_ref,
        )
        covered_finding_ids.update(waiver_decision.command.finding_ids)

    for finding_id, disposition in blocking_findings.items():
        assert disposition == FindingDisposition.PROFILE_BLOCK
        if finding_id not in covered_finding_ids:
            raise AdaptationBlockingFindingUnresolvedError(
                f"finding {finding_id!r} is a PROFILE_BLOCK finding with no applicable waiver covering it"
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

    async def decide_waiver(
        self, command: ProfileWaiverCommand, *, authenticated_principal: str
    ) -> AdaptationDecisionReceipt:
        command_identity_hash = compute_command_identity_hash(command)
        head_key = f"{command.artifact_ref.artifact_id}:{command.artifact_ref.version}"
        async with self._uow_factory() as uow:
            repo = uow.repository

            stored = await repo.get_decision_by_id(
                user_id=command.user_id, project_name=command.project_name, decision_id=command.decision_id
            )
            if stored is not None:
                receipt = await self._resolve_waiver_exact_retry(repo, command, stored, authenticated_principal)
                await uow.commit()
                return receipt

            head = await repo.prepare_or_lock_head(
                user_id=command.user_id,
                project_name=command.project_name,
                family=AdaptationAuthorityFamily.PROFILE_WAIVER,
                head_key=head_key,
            )

            stored = await repo.get_decision_by_id(
                user_id=command.user_id, project_name=command.project_name, decision_id=command.decision_id
            )
            if stored is not None:
                receipt = await self._resolve_waiver_exact_retry(repo, command, stored, authenticated_principal)
                await uow.commit()
                return receipt

            if head is not None:
                decisions = await repo.list_decisions_for_locked_head(
                    user_id=command.user_id,
                    project_name=command.project_name,
                    family=AdaptationAuthorityFamily.PROFILE_WAIVER,
                    head_key=head_key,
                )
                require_head_matches_fold(decisions, head)

            actual_predecessor = head.latest_decision_id if head is not None else None
            if command.expected_predecessor_id != actual_predecessor:
                raise AdaptationStaleHeadError(
                    f"decision {command.decision_id!r} expected predecessor {command.expected_predecessor_id!r}, "
                    f"but {head_key!r}'s current predecessor is {actual_predecessor!r}"
                )

            await _verify_waiver_applicability(repo, command)

            authorization = await self._authority.authorize(
                authenticated_principal=authenticated_principal,
                action=command.action,
                command_identity_hash=command_identity_hash,
            )
            _verify_authorization_binding(command, authorization, authenticated_principal)

            new_generation = (head.generation if head is not None else 0) + 1
            decision_digest = compute_decision_identity_hash(command, authorization)
            decision = ProfileWaiverDecision(
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
                family=AdaptationAuthorityFamily.PROFILE_WAIVER,
                head_key=head_key,
                outcome="RECORDED",
                current_at_return=True,
            )

    async def _resolve_waiver_exact_retry(
        self,
        repo: AdaptationRepositoryPort,
        command: ProfileWaiverCommand,
        stored: object,
        authenticated_principal: str,
    ) -> AdaptationDecisionReceipt:
        if not isinstance(stored, ProfileWaiverDecision) or stored.command != command:
            raise AdaptationIdentityConflictError(
                f"decision {command.decision_id!r} was already recorded with a different command"
            )
        authorization = await self._authority.authorize(
            authenticated_principal=authenticated_principal,
            action=command.action,
            command_identity_hash=compute_command_identity_hash(command),
        )
        _verify_authorization_binding(command, authorization, authenticated_principal)

        head_key = f"{command.artifact_ref.artifact_id}:{command.artifact_ref.version}"
        head = await repo.prepare_or_lock_head(
            user_id=command.user_id,
            project_name=command.project_name,
            family=AdaptationAuthorityFamily.PROFILE_WAIVER,
            head_key=head_key,
        )
        current_at_return = head is not None and head.effective_decision_id == stored.command.decision_id
        return AdaptationDecisionReceipt(
            decision_ref=DecisionRef(decision_id=stored.command.decision_id, decision_digest=stored.decision_digest),
            family=AdaptationAuthorityFamily.PROFILE_WAIVER,
            head_key=head_key,
            outcome="EXACT_RETRY",
            current_at_return=current_at_return,
        )

    async def admit_screenplay_for_direction(
        self, command: ScreenplayAdmissionCommand, *, authenticated_principal: str
    ) -> AdaptationDecisionReceipt:
        command_identity_hash = compute_command_identity_hash(command)
        head_key = command.admitted_screenplay.screenplay_id
        async with self._uow_factory() as uow:
            repo = uow.repository

            stored = await repo.get_decision_by_id(
                user_id=command.user_id, project_name=command.project_name, decision_id=command.decision_id
            )
            if stored is not None:
                receipt = await self._resolve_admission_exact_retry(repo, command, stored, authenticated_principal)
                await uow.commit()
                return receipt

            head = await repo.prepare_or_lock_head(
                user_id=command.user_id,
                project_name=command.project_name,
                family=AdaptationAuthorityFamily.SCREENPLAY_ADMISSION,
                head_key=head_key,
            )

            stored = await repo.get_decision_by_id(
                user_id=command.user_id, project_name=command.project_name, decision_id=command.decision_id
            )
            if stored is not None:
                receipt = await self._resolve_admission_exact_retry(repo, command, stored, authenticated_principal)
                await uow.commit()
                return receipt

            if head is not None:
                decisions = await repo.list_decisions_for_locked_head(
                    user_id=command.user_id,
                    project_name=command.project_name,
                    family=AdaptationAuthorityFamily.SCREENPLAY_ADMISSION,
                    head_key=head_key,
                )
                require_head_matches_fold(decisions, head)

            actual_predecessor = head.latest_decision_id if head is not None else None
            if command.expected_predecessor_id != actual_predecessor:
                raise AdaptationStaleHeadError(
                    f"decision {command.decision_id!r} expected predecessor {command.expected_predecessor_id!r}, "
                    f"but {head_key!r}'s current predecessor is {actual_predecessor!r}"
                )

            await _verify_admission_applicability(repo, command)

            authorization = await self._authority.authorize(
                authenticated_principal=authenticated_principal,
                action=command.action,
                command_identity_hash=command_identity_hash,
            )
            _verify_authorization_binding(command, authorization, authenticated_principal)

            new_generation = (head.generation if head is not None else 0) + 1
            decision_digest = compute_decision_identity_hash(command, authorization)
            decision = ScreenplayAdmissionDecision(
                command=command,
                authorization=authorization,
                sequence=new_generation,
                decision_digest=decision_digest,
                created_at=datetime.now(UTC),
            )

            if command.action == AdaptationDecisionAction.ADMIT:
                admitted = command.admitted_screenplay
                await repo.insert_screenplay(admitted, user_id=command.user_id, project_name=command.project_name)
                await repo.insert_screenplay_admission(
                    screenplay_ref=ArtifactVersionRef(
                        artifact_id=admitted.screenplay_id, version=admitted.version, content_hash=admitted.content_hash
                    ),
                    admission_decision_id=command.decision_id,
                    admission_decision_digest=decision_digest,
                    profile_ref=command.profile_ref,
                    created_at=decision.created_at,
                    user_id=command.user_id,
                    project_name=command.project_name,
                )

            await repo.append_decision_and_advance_head(
                decision, expected_generation=head.generation if head is not None else 0
            )
            await uow.commit()

            return AdaptationDecisionReceipt(
                decision_ref=DecisionRef(decision_id=command.decision_id, decision_digest=decision_digest),
                family=AdaptationAuthorityFamily.SCREENPLAY_ADMISSION,
                head_key=head_key,
                outcome="RECORDED",
                current_at_return=True,
            )

    async def _resolve_admission_exact_retry(
        self,
        repo: AdaptationRepositoryPort,
        command: ScreenplayAdmissionCommand,
        stored: object,
        authenticated_principal: str,
    ) -> AdaptationDecisionReceipt:
        if not isinstance(stored, ScreenplayAdmissionDecision) or stored.command != command:
            raise AdaptationIdentityConflictError(
                f"decision {command.decision_id!r} was already recorded with a different command"
            )
        authorization = await self._authority.authorize(
            authenticated_principal=authenticated_principal,
            action=command.action,
            command_identity_hash=compute_command_identity_hash(command),
        )
        _verify_authorization_binding(command, authorization, authenticated_principal)

        head_key = command.admitted_screenplay.screenplay_id
        head = await repo.prepare_or_lock_head(
            user_id=command.user_id,
            project_name=command.project_name,
            family=AdaptationAuthorityFamily.SCREENPLAY_ADMISSION,
            head_key=head_key,
        )
        current_at_return = head is not None and head.effective_decision_id == stored.command.decision_id
        return AdaptationDecisionReceipt(
            decision_ref=DecisionRef(decision_id=stored.command.decision_id, decision_digest=stored.decision_digest),
            family=AdaptationAuthorityFamily.SCREENPLAY_ADMISSION,
            head_key=head_key,
            outcome="EXACT_RETRY",
            current_at_return=current_at_return,
        )


__all__ = ["AdaptationAuthorityService"]
