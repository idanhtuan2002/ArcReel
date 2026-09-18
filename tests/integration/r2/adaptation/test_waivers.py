"""Integration coverage for ``AdaptationAuthorityService.decide_waiver`` (plan Task 11).

Human Showrunner denial, exact retry, stale predecessor/identity conflict, and the
waiver applicability guard: a missing report, a report-digest mismatch, an
unrecognized finding, a rule-version mismatch, a non-waivable ``INTEGRITY_BLOCK``
finding, a cross-profile report, and a semantic-change "waiver laundering" attempt —
all fail closed with no decision written. Over a real
``AdaptationRepository``/``SqlAlchemyAdaptationUnitOfWork`` against the
dialect-sensitive ``session_factory`` fixture.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.adaptation_uow import adaptation_uow_factory
from r2.adaptation.authority import AdaptationAuthorityService
from r2.adaptation.errors import (
    AdaptationAuthorityDeniedError,
    AdaptationIdentityConflictError,
    AdaptationNotFoundError,
    AdaptationStaleHeadError,
    AdaptationWaiverNotApplicableError,
)
from r2.adaptation.evaluation import ProfileEvaluationService, report_ref_of
from r2.adaptation.evidence import AdaptationEvidenceService
from r2.adaptation.hashing import compute_adaptation_hash, compute_profile_evaluation_report_digest
from r2.adaptation.profiles import _PACKS_DIR, _compute_policy_pack_digest
from r2.contracts.adaptation import (
    AdaptationBranchV2,
    AdaptationDecisionAction,
    AdaptationMapEntry,
    AdaptationMapV2,
    AdaptationOperation,
    AdaptationPolicy,
    AdaptationProfileId,
    AdaptationProfileRef,
    ArtifactVersionRef,
    DecisionRef,
    FindingDisposition,
    ProfileEvaluationReport,
    ProfileFinding,
    ProfileWaiverCommand,
    ScreenplayArtifactV2,
    ScreenplayScene,
)
from r2.contracts.content_basis import ContentBasis
from r2.contracts.enums import ContentBasisType, CreativeApprovalStatus
from tests.integration.r2.adaptation._fakes import FakeAuthority

USER = "u1"
PROJECT = "project-a"

type Factory = async_sessionmaker[AsyncSession]

_CANON_HASH = "sha256:" + "a1" * 32
_PRINCIPAL = "human:anhtuan"


def _western_ref() -> AdaptationProfileRef:
    raw = json.loads((_PACKS_DIR / "western_generic_v1.json").read_bytes())
    return AdaptationProfileRef(
        profile_id=AdaptationProfileId.WESTERN_GENERIC,
        profile_version="v1",
        policy_pack_digest=_compute_policy_pack_digest(raw),
    )


def _branch(*, branch_id: str, profile_ref: AdaptationProfileRef) -> AdaptationBranchV2:
    return AdaptationBranchV2(
        branch_id=branch_id,
        schema_version="r2-adaptation-branch-v2",
        version=1,
        parent_branch_id=None,
        parent_canon_version=ArtifactVersionRef(artifact_id="canon-1", version=1, content_hash=_CANON_HASH),
        medium="SHORT_FORM_VIDEO",
        adaptation_policy=AdaptationPolicy.FAITHFUL,
        overlay_version=1,
        profile_ref=profile_ref,
        created_at=datetime.now(UTC),
        created_by=_PRINCIPAL,
    )


def _branch_ref(branch: AdaptationBranchV2) -> ArtifactVersionRef:
    return ArtifactVersionRef(artifact_id=branch.branch_id, version=branch.version, content_hash="sha256:" + "b0" * 32)


def _map(*, adaptation_map_id: str, branch_ref: ArtifactVersionRef) -> AdaptationMapV2:
    entry = AdaptationMapEntry(
        entry_id="entry-1",
        source_refs=["src-1"],
        target_refs=["tgt-1"],
        operation=AdaptationOperation.PRESERVE,
        rationale="keep the scene",
        fidelity_risk="low",
        approval_status=CreativeApprovalStatus.APPROVED,
    )
    draft = AdaptationMapV2(
        adaptation_map_id=adaptation_map_id,
        schema_version="r2-adaptation-map-v2",
        version=1,
        adaptation_branch_ref=branch_ref,
        entries=[entry],
        profile_analysis_refs=[],
        content_hash="pending",
    )
    return draft.model_copy(update={"content_hash": compute_adaptation_hash(draft)})


def _map_ref(map_: AdaptationMapV2) -> ArtifactVersionRef:
    return ArtifactVersionRef(artifact_id=map_.adaptation_map_id, version=map_.version, content_hash=map_.content_hash)


def _screenplay(
    *, screenplay_id: str, branch_ref: ArtifactVersionRef, map_ref: ArtifactVersionRef, dramatic_text: str
) -> ScreenplayArtifactV2:
    scene = ScreenplayScene(
        scene_id="scene-1",
        purpose="advance the plot",
        duration_target=30.0,
        location_ref=None,
        character_refs=["char-1"],
        source_mapping_refs=["entry-1"],
        dramatic_text=dramatic_text,
    )
    draft = ScreenplayArtifactV2(
        screenplay_id=screenplay_id,
        schema_version="r2-screenplay-artifact-v2",
        version=1,
        adaptation_branch_ref=branch_ref,
        content_basis=ContentBasis(basis_type=ContentBasisType.ADAPTATION, basis_version="v1", refs=["src-1"]),
        scenes=[scene],
        characters=["char-1"],
        source_mapping_refs=["entry-1"],
        approval_status=CreativeApprovalStatus.DRAFT,
        locked_for_direction=False,
        content_hash="pending",
        adaptation_map_ref=map_ref,
        profile_analysis_refs=[],
    )
    return draft.model_copy(update={"content_hash": compute_adaptation_hash(draft)})


def _screenplay_ref(screenplay: ScreenplayArtifactV2) -> ArtifactVersionRef:
    return ArtifactVersionRef(
        artifact_id=screenplay.screenplay_id, version=screenplay.version, content_hash=screenplay.content_hash
    )


async def _seed_screenplay_with_a_profile_block_finding(
    adaptation_evidence_service: AdaptationEvidenceService,
    evaluation_service: ProfileEvaluationService,
    *,
    branch_id: str = "branch-1",
    map_id: str = "map-1",
    screenplay_id: str = "sp-1",
) -> tuple[ScreenplayArtifactV2, ProfileEvaluationReport]:
    profile_ref = _western_ref()
    branch = await adaptation_evidence_service.create_branch(
        _branch(branch_id=branch_id, profile_ref=profile_ref), user_id=USER, project_name=PROJECT
    )
    branch_ref = _branch_ref(branch)
    map_ = await adaptation_evidence_service.append_map(
        _map(adaptation_map_id=map_id, branch_ref=branch_ref), user_id=USER, project_name=PROJECT
    )
    screenplay = await adaptation_evidence_service.append_screenplay(
        # No INT./EXT. slugline prefix triggers WESTERN_SCENE_HEADING_STRUCTURE (PROFILE_BLOCK).
        _screenplay(
            screenplay_id=screenplay_id,
            branch_ref=branch_ref,
            map_ref=_map_ref(map_),
            dramatic_text="Something happens.\nMore happens.",
        ),
        user_id=USER,
        project_name=PROJECT,
    )
    report = await evaluation_service.evaluate(
        artifact_ref=_screenplay_ref(screenplay), profile_ref=profile_ref, user_id=USER, project_name=PROJECT
    )
    assert len(report.findings) == 1
    assert report.findings[0].disposition == FindingDisposition.PROFILE_BLOCK
    return screenplay, report


def _waive_command(
    *,
    decision_id: str = "w-1",
    branch_id: str = "branch-1",
    artifact_ref: ArtifactVersionRef,
    profile_ref: AdaptationProfileRef,
    report_ref: DecisionRef,
    finding_ids: list[str],
    rule_versions: list[str],
    expected_predecessor_id: str | None = None,
    action: AdaptationDecisionAction = AdaptationDecisionAction.WAIVE,
) -> ProfileWaiverCommand:
    return ProfileWaiverCommand(
        user_id=USER,
        project_name=PROJECT,
        decision_id=decision_id,
        branch_id=branch_id,
        artifact_ref=artifact_ref,
        profile_ref=profile_ref,
        report_ref=report_ref,
        finding_ids=finding_ids,
        rule_versions=rule_versions,
        rationale="approved by the Human Showrunner for this cut",
        expected_predecessor_id=expected_predecessor_id,
        action=action,
    )


# --- happy path: waive, deny, sequencing ------------------------------------------------


async def test_decide_waiver_approves_a_waivable_finding(
    authority_service: AdaptationAuthorityService,
    adaptation_evidence_service: AdaptationEvidenceService,
    evaluation_service: ProfileEvaluationService,
) -> None:
    screenplay, report = await _seed_screenplay_with_a_profile_block_finding(
        adaptation_evidence_service, evaluation_service
    )
    finding = report.findings[0]
    command = _waive_command(
        artifact_ref=_screenplay_ref(screenplay),
        profile_ref=report.profile_ref,
        report_ref=report_ref_of(report),
        finding_ids=[finding.finding_id],
        rule_versions=[finding.rule_version],
    )
    receipt = await authority_service.decide_waiver(command, authenticated_principal=_PRINCIPAL)
    assert receipt.outcome == "RECORDED"
    assert receipt.current_at_return is True


async def test_decide_waiver_deny_waiver_leaves_no_effective_selection(
    authority_service: AdaptationAuthorityService,
    adaptation_evidence_service: AdaptationEvidenceService,
    evaluation_service: ProfileEvaluationService,
) -> None:
    screenplay, report = await _seed_screenplay_with_a_profile_block_finding(
        adaptation_evidence_service, evaluation_service
    )
    finding = report.findings[0]
    command = _waive_command(
        artifact_ref=_screenplay_ref(screenplay),
        profile_ref=report.profile_ref,
        report_ref=report_ref_of(report),
        finding_ids=[finding.finding_id],
        rule_versions=[finding.rule_version],
        action=AdaptationDecisionAction.DENY_WAIVER,
    )
    receipt = await authority_service.decide_waiver(command, authenticated_principal=_PRINCIPAL)
    assert receipt.outcome == "RECORDED"
    assert receipt.current_at_return is False


# --- Human Showrunner denial -------------------------------------------------------------


async def test_decide_waiver_denial_grants_nothing(
    session_factory: Factory,
    adaptation_evidence_service: AdaptationEvidenceService,
    evaluation_service: ProfileEvaluationService,
    denying_authority_service: AdaptationAuthorityService,
) -> None:
    screenplay, report = await _seed_screenplay_with_a_profile_block_finding(
        adaptation_evidence_service, evaluation_service
    )
    finding = report.findings[0]
    command = _waive_command(
        artifact_ref=_screenplay_ref(screenplay),
        profile_ref=report.profile_ref,
        report_ref=report_ref_of(report),
        finding_ids=[finding.finding_id],
        rule_versions=[finding.rule_version],
    )
    with pytest.raises(AdaptationAuthorityDeniedError):
        await denying_authority_service.decide_waiver(command, authenticated_principal=_PRINCIPAL)
    async with adaptation_uow_factory(session_factory)() as uow:
        assert await uow.repository.get_decision_by_id(user_id=USER, project_name=PROJECT, decision_id="w-1") is None


async def test_decide_waiver_rejects_authorization_for_another_command(
    session_factory: Factory,
    adaptation_evidence_service: AdaptationEvidenceService,
    evaluation_service: ProfileEvaluationService,
) -> None:
    screenplay, report = await _seed_screenplay_with_a_profile_block_finding(
        adaptation_evidence_service, evaluation_service
    )
    finding = report.findings[0]
    command = _waive_command(
        artifact_ref=_screenplay_ref(screenplay),
        profile_ref=report.profile_ref,
        report_ref=report_ref_of(report),
        finding_ids=[finding.finding_id],
        rule_versions=[finding.rule_version],
    )
    service = AdaptationAuthorityService(
        adaptation_uow_factory(session_factory), FakeAuthority(command_identity_hash="cid:wrong-command")
    )

    with pytest.raises(AdaptationAuthorityDeniedError):
        await service.decide_waiver(command, authenticated_principal=_PRINCIPAL)


# --- applicability guard: missing report, digest mismatch, unknown finding -------------


async def test_decide_waiver_rejects_a_missing_report(
    authority_service: AdaptationAuthorityService,
    adaptation_evidence_service: AdaptationEvidenceService,
    evaluation_service: ProfileEvaluationService,
) -> None:
    screenplay, report = await _seed_screenplay_with_a_profile_block_finding(
        adaptation_evidence_service, evaluation_service
    )
    finding = report.findings[0]
    command = _waive_command(
        artifact_ref=_screenplay_ref(screenplay),
        profile_ref=report.profile_ref,
        report_ref=DecisionRef(decision_id="sha256:" + "ff" * 32, decision_digest="sha256:" + "ff" * 32),
        finding_ids=[finding.finding_id],
        rule_versions=[finding.rule_version],
    )
    with pytest.raises(AdaptationNotFoundError):
        await authority_service.decide_waiver(command, authenticated_principal=_PRINCIPAL)


async def test_decide_waiver_rejects_a_report_digest_mismatch(
    authority_service: AdaptationAuthorityService,
    adaptation_evidence_service: AdaptationEvidenceService,
    evaluation_service: ProfileEvaluationService,
) -> None:
    screenplay, report = await _seed_screenplay_with_a_profile_block_finding(
        adaptation_evidence_service, evaluation_service
    )
    finding = report.findings[0]
    command = _waive_command(
        artifact_ref=_screenplay_ref(screenplay),
        profile_ref=report.profile_ref,
        report_ref=DecisionRef(decision_id=report.report_digest, decision_digest="sha256:" + "ff" * 32),
        finding_ids=[finding.finding_id],
        rule_versions=[finding.rule_version],
    )
    with pytest.raises(AdaptationWaiverNotApplicableError):
        await authority_service.decide_waiver(command, authenticated_principal=_PRINCIPAL)


async def test_decide_waiver_rejects_an_unresolved_artifact_with_matching_bytes(
    authority_service: AdaptationAuthorityService,
    adaptation_evidence_service: AdaptationEvidenceService,
    evaluation_service: ProfileEvaluationService,
) -> None:
    screenplay, report = await _seed_screenplay_with_a_profile_block_finding(
        adaptation_evidence_service, evaluation_service
    )
    finding = report.findings[0]
    laundered_ref = ArtifactVersionRef(
        artifact_id="another-screenplay",
        version=99,
        content_hash=screenplay.content_hash,
    )
    command = _waive_command(
        artifact_ref=laundered_ref,
        profile_ref=report.profile_ref,
        report_ref=report_ref_of(report),
        finding_ids=[finding.finding_id],
        rule_versions=[finding.rule_version],
    )

    with pytest.raises(AdaptationNotFoundError):
        await authority_service.decide_waiver(command, authenticated_principal=_PRINCIPAL)


async def test_decide_waiver_rejects_an_unrecognized_finding(
    authority_service: AdaptationAuthorityService,
    adaptation_evidence_service: AdaptationEvidenceService,
    evaluation_service: ProfileEvaluationService,
) -> None:
    screenplay, report = await _seed_screenplay_with_a_profile_block_finding(
        adaptation_evidence_service, evaluation_service
    )
    command = _waive_command(
        artifact_ref=_screenplay_ref(screenplay),
        profile_ref=report.profile_ref,
        report_ref=report_ref_of(report),
        finding_ids=["NOT_A_REAL_FINDING"],
        rule_versions=["v1"],
    )
    with pytest.raises(AdaptationWaiverNotApplicableError):
        await authority_service.decide_waiver(command, authenticated_principal=_PRINCIPAL)


async def test_decide_waiver_rejects_a_rule_version_mismatch(
    authority_service: AdaptationAuthorityService,
    adaptation_evidence_service: AdaptationEvidenceService,
    evaluation_service: ProfileEvaluationService,
) -> None:
    screenplay, report = await _seed_screenplay_with_a_profile_block_finding(
        adaptation_evidence_service, evaluation_service
    )
    finding = report.findings[0]
    command = _waive_command(
        artifact_ref=_screenplay_ref(screenplay),
        profile_ref=report.profile_ref,
        report_ref=report_ref_of(report),
        finding_ids=[finding.finding_id],
        rule_versions=["not-the-real-rule-version"],
    )
    with pytest.raises(AdaptationWaiverNotApplicableError):
        await authority_service.decide_waiver(command, authenticated_principal=_PRINCIPAL)


async def test_decide_waiver_rejects_an_integrity_block_finding(
    authority_service: AdaptationAuthorityService,
    adaptation_evidence_service: AdaptationEvidenceService,
    evaluation_service: ProfileEvaluationService,
    session_factory: Factory,
) -> None:
    screenplay, report = await _seed_screenplay_with_a_profile_block_finding(
        adaptation_evidence_service, evaluation_service
    )
    integrity_finding = ProfileFinding(
        finding_id="SHARED_CANON_LINEAGE:scene-1",
        rule_id="SHARED_CANON_LINEAGE",
        rule_version="v1",
        disposition=FindingDisposition.INTEGRITY_BLOCK,
        applicability="ALWAYS",
        severity="BLOCKING",
        target_path="scenes[0]",
        source_span="n/a",
        evidence_refs=[],
        message_params={},
    )
    tainted_draft = report.model_copy(
        update={"findings": [*report.findings, integrity_finding], "report_digest": "pending"}
    )
    tainted_report = tainted_draft.model_copy(
        update={"report_digest": compute_profile_evaluation_report_digest(tainted_draft)}
    )
    async with adaptation_uow_factory(session_factory)() as uow:
        await uow.repository.insert_report(tainted_report, user_id=USER, project_name=PROJECT)
        await uow.commit()

    command = _waive_command(
        artifact_ref=_screenplay_ref(screenplay),
        profile_ref=tainted_report.profile_ref,
        report_ref=DecisionRef(decision_id=tainted_report.report_digest, decision_digest=tainted_report.report_digest),
        finding_ids=[integrity_finding.finding_id],
        rule_versions=[integrity_finding.rule_version],
    )
    with pytest.raises(AdaptationWaiverNotApplicableError):
        await authority_service.decide_waiver(command, authenticated_principal=_PRINCIPAL)


async def test_decide_waiver_rejects_a_cross_profile_report(
    authority_service: AdaptationAuthorityService,
    adaptation_evidence_service: AdaptationEvidenceService,
    evaluation_service: ProfileEvaluationService,
) -> None:
    screenplay, report = await _seed_screenplay_with_a_profile_block_finding(
        adaptation_evidence_service, evaluation_service
    )
    finding = report.findings[0]
    other_profile = AdaptationProfileRef(
        profile_id=AdaptationProfileId.CN_SHORT_DRAMA_SHUANGWEN,
        profile_version=report.profile_ref.profile_version,
        policy_pack_digest=report.profile_ref.policy_pack_digest,
    )
    command = _waive_command(
        artifact_ref=_screenplay_ref(screenplay),
        profile_ref=other_profile,
        report_ref=report_ref_of(report),
        finding_ids=[finding.finding_id],
        rule_versions=[finding.rule_version],
    )
    with pytest.raises(AdaptationWaiverNotApplicableError):
        await authority_service.decide_waiver(command, authenticated_principal=_PRINCIPAL)


async def test_decide_waiver_rejects_laundering_after_a_semantic_change(
    authority_service: AdaptationAuthorityService,
    adaptation_evidence_service: AdaptationEvidenceService,
    evaluation_service: ProfileEvaluationService,
) -> None:
    screenplay, report = await _seed_screenplay_with_a_profile_block_finding(
        adaptation_evidence_service, evaluation_service
    )
    finding = report.findings[0]
    changed_artifact_ref = ArtifactVersionRef(
        artifact_id=screenplay.screenplay_id, version=screenplay.version, content_hash="sha256:" + "9c" * 32
    )
    command = _waive_command(
        artifact_ref=changed_artifact_ref,
        profile_ref=report.profile_ref,
        report_ref=report_ref_of(report),
        finding_ids=[finding.finding_id],
        rule_versions=[finding.rule_version],
    )
    with pytest.raises(AdaptationWaiverNotApplicableError):
        await authority_service.decide_waiver(command, authenticated_principal=_PRINCIPAL)


# --- exact retry / stale predecessor / identity conflict --------------------------------


async def test_decide_waiver_exact_retry_returns_the_same_receipt(
    authority_service: AdaptationAuthorityService,
    adaptation_evidence_service: AdaptationEvidenceService,
    evaluation_service: ProfileEvaluationService,
) -> None:
    screenplay, report = await _seed_screenplay_with_a_profile_block_finding(
        adaptation_evidence_service, evaluation_service
    )
    finding = report.findings[0]
    command = _waive_command(
        artifact_ref=_screenplay_ref(screenplay),
        profile_ref=report.profile_ref,
        report_ref=report_ref_of(report),
        finding_ids=[finding.finding_id],
        rule_versions=[finding.rule_version],
    )
    first = await authority_service.decide_waiver(command, authenticated_principal=_PRINCIPAL)
    second = await authority_service.decide_waiver(command, authenticated_principal=_PRINCIPAL)
    assert first.decision_ref == second.decision_ref
    assert second.outcome == "EXACT_RETRY"
    assert second.current_at_return is True


async def test_decide_waiver_rejects_a_stale_expected_predecessor(
    authority_service: AdaptationAuthorityService,
    adaptation_evidence_service: AdaptationEvidenceService,
    evaluation_service: ProfileEvaluationService,
) -> None:
    screenplay, report = await _seed_screenplay_with_a_profile_block_finding(
        adaptation_evidence_service, evaluation_service
    )
    finding = report.findings[0]
    command = _waive_command(
        artifact_ref=_screenplay_ref(screenplay),
        profile_ref=report.profile_ref,
        report_ref=report_ref_of(report),
        finding_ids=[finding.finding_id],
        rule_versions=[finding.rule_version],
        expected_predecessor_id="w-0",
    )
    with pytest.raises(AdaptationStaleHeadError):
        await authority_service.decide_waiver(command, authenticated_principal=_PRINCIPAL)


async def test_decide_waiver_rejects_a_reused_id_with_a_different_command(
    authority_service: AdaptationAuthorityService,
    adaptation_evidence_service: AdaptationEvidenceService,
    evaluation_service: ProfileEvaluationService,
) -> None:
    screenplay, report = await _seed_screenplay_with_a_profile_block_finding(
        adaptation_evidence_service, evaluation_service
    )
    finding = report.findings[0]
    first = _waive_command(
        artifact_ref=_screenplay_ref(screenplay),
        profile_ref=report.profile_ref,
        report_ref=report_ref_of(report),
        finding_ids=[finding.finding_id],
        rule_versions=[finding.rule_version],
    )
    await authority_service.decide_waiver(first, authenticated_principal=_PRINCIPAL)

    conflicting = _waive_command(
        artifact_ref=_screenplay_ref(screenplay),
        profile_ref=report.profile_ref,
        report_ref=report_ref_of(report),
        finding_ids=[finding.finding_id],
        rule_versions=[finding.rule_version],
        action=AdaptationDecisionAction.DENY_WAIVER,
    )
    with pytest.raises(AdaptationIdentityConflictError):
        await authority_service.decide_waiver(conflicting, authenticated_principal=_PRINCIPAL)
