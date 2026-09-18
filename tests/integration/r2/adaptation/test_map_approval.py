"""Integration coverage for ``AdaptationAuthorityService.decide_map`` (plan Task 7).

Human Showrunner denial, whole-map hash binding, incomplete entry evidence, exact
retry before stale head, retry after supersession, stale policy, cross-profile refs,
and FK-valid corrupted-head integrity guards — over a real ``AdaptationRepository``/
``SqlAlchemyAdaptationUnitOfWork`` against the dialect-sensitive ``session_factory``
fixture. Real-PostgreSQL concurrency races live in ``test_concurrency.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.adaptation_uow import adaptation_uow_factory
from lib.db.models.adaptation import AdaptationEvaluationReportModel, AdaptationHeadModel
from r2.adaptation.authority import AdaptationAuthorityService
from r2.adaptation.authority_kernel import fold_adaptation_head, verify_locked_adaptation_selection
from r2.adaptation.errors import (
    AdaptationAuthorityDeniedError,
    AdaptationAuthorityIntegrityError,
    AdaptationIdentityConflictError,
    AdaptationNotFoundError,
    AdaptationPolicyDigestMismatchError,
    AdaptationProfileMismatchError,
    AdaptationStaleDependencyError,
    AdaptationStaleHeadError,
)
from r2.adaptation.evidence import AdaptationEvidenceService
from r2.adaptation.hashing import (
    compute_adaptation_hash,
    compute_profile_evaluation_report_digest,
    compute_profile_sidecar_id,
)
from r2.contracts.adaptation import (
    AdaptationAuthorityFamily,
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
    MapApprovalCommand,
    ProfileEvaluationReport,
    WesternDramaAnalysis,
)
from r2.contracts.enums import CreativeApprovalStatus
from tests.integration.r2.adaptation._fakes import FakeAuthority

USER = "u1"
PROJECT = "project-a"

type Factory = async_sessionmaker[AsyncSession]

_CANON_HASH = "sha256:" + "a1" * 32
_UNVERIFIED_BRANCH_HASH = "sha256:" + "b2" * 32
_PRINCIPAL = "human:anhtuan"


def _branch(
    *,
    branch_id: str = "branch-1",
    profile_id: AdaptationProfileId = AdaptationProfileId.WESTERN_GENERIC,
    profile_version: str = "v1",
    policy_pack_digest: str = "sha256:" + "c3" * 32,
) -> AdaptationBranchV2:
    return AdaptationBranchV2(
        branch_id=branch_id,
        schema_version="r2-adaptation-branch-v2",
        version=1,
        parent_branch_id=None,
        parent_canon_version=ArtifactVersionRef(artifact_id="canon-1", version=1, content_hash=_CANON_HASH),
        medium="SHORT_FORM_VIDEO",
        adaptation_policy=AdaptationPolicy.FAITHFUL,
        overlay_version=1,
        profile_ref=AdaptationProfileRef(
            profile_id=profile_id, profile_version=profile_version, policy_pack_digest=policy_pack_digest
        ),
        created_at=datetime.now(UTC),
        created_by=_PRINCIPAL,
    )


def _branch_ref(branch: AdaptationBranchV2) -> ArtifactVersionRef:
    return ArtifactVersionRef(
        artifact_id=branch.branch_id, version=branch.version, content_hash=_UNVERIFIED_BRANCH_HASH
    )


def _map(
    *,
    adaptation_map_id: str = "map-1",
    branch_ref: ArtifactVersionRef,
    all_entries_approved: bool = True,
    profile_analysis_refs: list[ArtifactVersionRef] | None = None,
) -> AdaptationMapV2:
    from r2.adaptation.hashing import compute_adaptation_hash

    entry = AdaptationMapEntry(
        entry_id="entry-1",
        source_refs=["src-1"],
        target_refs=["tgt-1"],
        operation=AdaptationOperation.PRESERVE,
        rationale="keep the scene",
        fidelity_risk="low",
        approval_status=CreativeApprovalStatus.APPROVED if all_entries_approved else CreativeApprovalStatus.DRAFT,
    )
    draft = AdaptationMapV2(
        adaptation_map_id=adaptation_map_id,
        schema_version="r2-adaptation-map-v2",
        version=1,
        adaptation_branch_ref=branch_ref,
        entries=[entry],
        profile_analysis_refs=profile_analysis_refs or [],
        content_hash="pending",
    )
    return draft.model_copy(update={"content_hash": compute_adaptation_hash(draft)})


def _map_ref(map_: AdaptationMapV2, *, content_hash: str | None = None) -> ArtifactVersionRef:
    return ArtifactVersionRef(
        artifact_id=map_.adaptation_map_id, version=map_.version, content_hash=content_hash or map_.content_hash
    )


def _approve_command(
    *,
    decision_id: str = "d-1",
    branch_id: str = "branch-1",
    map_ref: ArtifactVersionRef,
    profile_ref: AdaptationProfileRef,
    relied_report_refs: list[DecisionRef] | None = None,
    expected_predecessor_id: str | None = None,
    action: AdaptationDecisionAction = AdaptationDecisionAction.APPROVE,
) -> MapApprovalCommand:
    return MapApprovalCommand(
        user_id=USER,
        project_name=PROJECT,
        decision_id=decision_id,
        branch_id=branch_id,
        map_ref=map_ref,
        profile_ref=profile_ref,
        relied_report_refs=relied_report_refs or [],
        expected_predecessor_id=expected_predecessor_id,
        action=action,
    )


class InjectedFault(RuntimeError):
    pass


@pytest.fixture
def corrupt_head(session_factory: Factory):
    async def _corrupt(*, branch_id: str = "branch-1", **updates: object) -> None:
        async with adaptation_uow_factory(session_factory)() as uow:
            await uow.session.execute(
                update(AdaptationHeadModel)
                .where(
                    AdaptationHeadModel.user_id == USER,
                    AdaptationHeadModel.project_name == PROJECT,
                    AdaptationHeadModel.family == AdaptationAuthorityFamily.MAP_APPROVAL.value,
                    AdaptationHeadModel.head_key == branch_id,
                )
                .values(**updates)
            )
            await uow.commit()

    return _corrupt


async def _seed_branch_and_map(
    adaptation_evidence_service: AdaptationEvidenceService,
    *,
    branch_id: str = "branch-1",
    map_id: str = "map-1",
    **map_kwargs,
) -> tuple[AdaptationBranchV2, AdaptationMapV2]:
    branch = await adaptation_evidence_service.create_branch(
        _branch(branch_id=branch_id), user_id=USER, project_name=PROJECT
    )
    branch_ref = _branch_ref(branch)
    map_ = await adaptation_evidence_service.append_map(
        _map(adaptation_map_id=map_id, branch_ref=branch_ref, **map_kwargs), user_id=USER, project_name=PROJECT
    )
    return branch, map_


# --- happy path: approve, reject, sequencing ------------------------------------------


async def test_decide_map_approve_first_decision_succeeds(
    authority_service: AdaptationAuthorityService, adaptation_evidence_service: AdaptationEvidenceService
) -> None:
    branch, map_ = await _seed_branch_and_map(adaptation_evidence_service)
    command = _approve_command(map_ref=_map_ref(map_), profile_ref=branch.profile_ref)
    receipt = await authority_service.decide_map(command, authenticated_principal=_PRINCIPAL)
    assert receipt.outcome == "RECORDED"
    assert receipt.current_at_return is True
    assert receipt.decision_ref.decision_id == "d-1"


async def test_decide_map_reject_leaves_no_effective_selection(
    authority_service: AdaptationAuthorityService, adaptation_evidence_service: AdaptationEvidenceService
) -> None:
    branch, map_ = await _seed_branch_and_map(adaptation_evidence_service)
    command = _approve_command(
        map_ref=_map_ref(map_), profile_ref=branch.profile_ref, action=AdaptationDecisionAction.REJECT
    )
    receipt = await authority_service.decide_map(command, authenticated_principal=_PRINCIPAL)
    assert receipt.outcome == "RECORDED"
    assert receipt.current_at_return is False


async def test_decide_map_second_approval_advances_generation_after_reject(
    authority_service: AdaptationAuthorityService, adaptation_evidence_service: AdaptationEvidenceService
) -> None:
    branch, map_a = await _seed_branch_and_map(adaptation_evidence_service, map_id="map-a")
    reject = _approve_command(
        map_ref=_map_ref(map_a), profile_ref=branch.profile_ref, action=AdaptationDecisionAction.REJECT
    )
    await authority_service.decide_map(reject, authenticated_principal=_PRINCIPAL)

    map_b = await adaptation_evidence_service.append_map(
        _map(adaptation_map_id="map-b", branch_ref=_branch_ref(branch)), user_id=USER, project_name=PROJECT
    )
    approve = _approve_command(
        decision_id="d-2", map_ref=_map_ref(map_b), profile_ref=branch.profile_ref, expected_predecessor_id="d-1"
    )
    receipt = await authority_service.decide_map(approve, authenticated_principal=_PRINCIPAL)
    assert receipt.outcome == "RECORDED"


# --- Human Showrunner denial ---------------------------------------------------------


async def test_decide_map_denial_grants_nothing(
    session_factory: Factory,
    adaptation_evidence_service: AdaptationEvidenceService,
    denying_authority_service: AdaptationAuthorityService,
) -> None:
    branch, map_ = await _seed_branch_and_map(adaptation_evidence_service)
    command = _approve_command(map_ref=_map_ref(map_), profile_ref=branch.profile_ref)
    with pytest.raises(AdaptationAuthorityDeniedError):
        await denying_authority_service.decide_map(command, authenticated_principal=_PRINCIPAL)
    stored = await adaptation_evidence_service.get_exact_branch(
        branch_id=branch.branch_id, version=1, project_name=PROJECT, user_id=USER
    )
    assert stored is not None  # branch/map evidence untouched; assert no decision below
    async with adaptation_uow_factory(session_factory)() as uow:
        assert await uow.repository.get_decision_by_id(user_id=USER, project_name=PROJECT, decision_id="d-1") is None


async def test_decide_map_rejects_authorization_for_another_command(
    session_factory: Factory, adaptation_evidence_service: AdaptationEvidenceService
) -> None:
    branch, map_ = await _seed_branch_and_map(adaptation_evidence_service)
    service = AdaptationAuthorityService(
        adaptation_uow_factory(session_factory), FakeAuthority(command_identity_hash="cid:wrong-command")
    )
    command = _approve_command(map_ref=_map_ref(map_), profile_ref=branch.profile_ref)

    with pytest.raises(AdaptationAuthorityDeniedError):
        await service.decide_map(command, authenticated_principal=_PRINCIPAL)

    async with adaptation_uow_factory(session_factory)() as uow:
        assert await uow.repository.get_decision_by_id(user_id=USER, project_name=PROJECT, decision_id="d-1") is None


# --- whole-map hash binding / integrity of referenced evidence ------------------------


async def test_decide_map_rejects_a_missing_map(
    authority_service: AdaptationAuthorityService, adaptation_evidence_service: AdaptationEvidenceService
) -> None:
    branch = await adaptation_evidence_service.create_branch(_branch(), user_id=USER, project_name=PROJECT)
    dangling_ref = ArtifactVersionRef(artifact_id="map-nonexistent", version=1, content_hash="sha256:" + "d4" * 32)
    command = _approve_command(map_ref=dangling_ref, profile_ref=branch.profile_ref)
    with pytest.raises(AdaptationNotFoundError):
        await authority_service.decide_map(command, authenticated_principal=_PRINCIPAL)


async def test_decide_map_rejects_a_stale_map_content_hash(
    authority_service: AdaptationAuthorityService, adaptation_evidence_service: AdaptationEvidenceService
) -> None:
    branch, map_ = await _seed_branch_and_map(adaptation_evidence_service)
    stale_ref = _map_ref(map_, content_hash="sha256:" + "e5" * 32)
    command = _approve_command(map_ref=stale_ref, profile_ref=branch.profile_ref)
    with pytest.raises(AdaptationStaleDependencyError):
        await authority_service.decide_map(command, authenticated_principal=_PRINCIPAL)


async def test_decide_map_rejects_incomplete_entry_evidence(
    authority_service: AdaptationAuthorityService, adaptation_evidence_service: AdaptationEvidenceService
) -> None:
    branch, map_ = await _seed_branch_and_map(adaptation_evidence_service, all_entries_approved=False)
    command = _approve_command(map_ref=_map_ref(map_), profile_ref=branch.profile_ref)
    with pytest.raises(AdaptationStaleDependencyError):
        await authority_service.decide_map(command, authenticated_principal=_PRINCIPAL)


async def test_decide_map_rejects_analyzed_map_with_zero_relied_reports(
    authority_service: AdaptationAuthorityService, adaptation_evidence_service: AdaptationEvidenceService
) -> None:
    analysis_ref = ArtifactVersionRef(artifact_id="report-1", version=1, content_hash="sha256:" + "f6" * 32)
    branch, map_ = await _seed_branch_and_map(adaptation_evidence_service, profile_analysis_refs=[analysis_ref])
    command = _approve_command(map_ref=_map_ref(map_), profile_ref=branch.profile_ref)
    with pytest.raises(AdaptationStaleDependencyError):
        await authority_service.decide_map(command, authenticated_principal=_PRINCIPAL)


async def test_decide_map_rejects_a_dangling_relied_report(
    authority_service: AdaptationAuthorityService, adaptation_evidence_service: AdaptationEvidenceService
) -> None:
    analysis_ref = ArtifactVersionRef(artifact_id="analysis-1", version=1, content_hash="sha256:" + "f6" * 32)
    branch, map_ = await _seed_branch_and_map(adaptation_evidence_service, profile_analysis_refs=[analysis_ref])
    dangling_report = DecisionRef(decision_id="report-missing", decision_digest="report-missing")
    command = _approve_command(
        map_ref=_map_ref(map_),
        profile_ref=branch.profile_ref,
        relied_report_refs=[dangling_report],
    )

    with pytest.raises(AdaptationNotFoundError):
        await authority_service.decide_map(command, authenticated_principal=_PRINCIPAL)


async def test_decide_map_accepts_reports_that_bind_the_exact_ordered_analysis_sidecars(
    session_factory: Factory,
    authority_service: AdaptationAuthorityService,
    adaptation_evidence_service: AdaptationEvidenceService,
) -> None:
    sidecar_draft = WesternDramaAnalysis(
        schema_version="r2-western-drama-analysis-v1",
        content_hash="pending",
        format_findings=[],
        rubric_observations=["reviewed"],
        evidence_locations=["scene-1"],
    )
    sidecar = sidecar_draft.model_copy(update={"content_hash": compute_adaptation_hash(sidecar_draft)})
    branch = await adaptation_evidence_service.create_branch(_branch(), user_id=USER, project_name=PROJECT)
    map_draft = _map(adaptation_map_id="map-1", branch_ref=_branch_ref(branch))
    sidecar_ref = ArtifactVersionRef(
        artifact_id=compute_profile_sidecar_id(map_draft.adaptation_map_id, branch.profile_ref),
        version=map_draft.version,
        content_hash=sidecar.content_hash,
    )
    analyzed_draft = map_draft.model_copy(update={"profile_analysis_refs": [sidecar_ref], "content_hash": "pending"})
    analyzed_map = analyzed_draft.model_copy(update={"content_hash": compute_adaptation_hash(analyzed_draft)})
    map_ = await adaptation_evidence_service.append_map(analyzed_map, user_id=USER, project_name=PROJECT)
    report_draft = ProfileEvaluationReport(
        schema_version="r2-profile-evaluation-report-v1",
        artifact_hash=map_.content_hash,
        profile_ref=branch.profile_ref,
        evaluator_version="test-evaluator-v1",
        sidecar_ref=sidecar_ref,
        sidecar_digest=sidecar.content_hash,
        findings=[],
        report_digest="pending",
        created_at=datetime.now(UTC),
    )
    report = report_draft.model_copy(update={"report_digest": compute_profile_evaluation_report_digest(report_draft)})
    async with adaptation_uow_factory(session_factory)() as uow:
        await uow.repository.insert_sidecar(
            sidecar_ref.artifact_id,
            sidecar_ref.version,
            sidecar,
            user_id=USER,
            project_name=PROJECT,
        )
        await uow.repository.insert_report(report, user_id=USER, project_name=PROJECT)
        await uow.commit()
    command = _approve_command(
        map_ref=_map_ref(map_),
        profile_ref=branch.profile_ref,
        relied_report_refs=[DecisionRef(decision_id=report.report_digest, decision_digest=report.report_digest)],
    )

    receipt = await authority_service.decide_map(command, authenticated_principal=_PRINCIPAL)

    assert receipt.outcome == "RECORDED"


async def test_decide_map_rejects_a_report_for_different_artifact_content(
    session_factory: Factory,
    authority_service: AdaptationAuthorityService,
    adaptation_evidence_service: AdaptationEvidenceService,
) -> None:
    sidecar_draft = WesternDramaAnalysis(
        schema_version="r2-western-drama-analysis-v1",
        content_hash="pending",
        format_findings=[],
        rubric_observations=["reviewed"],
        evidence_locations=["scene-1"],
    )
    sidecar = sidecar_draft.model_copy(update={"content_hash": compute_adaptation_hash(sidecar_draft)})
    branch = await adaptation_evidence_service.create_branch(_branch(), user_id=USER, project_name=PROJECT)
    map_draft = _map(adaptation_map_id="map-1", branch_ref=_branch_ref(branch))
    sidecar_ref = ArtifactVersionRef(
        artifact_id=compute_profile_sidecar_id(map_draft.adaptation_map_id, branch.profile_ref),
        version=map_draft.version,
        content_hash=sidecar.content_hash,
    )
    analyzed_draft = map_draft.model_copy(update={"profile_analysis_refs": [sidecar_ref], "content_hash": "pending"})
    analyzed_map = analyzed_draft.model_copy(update={"content_hash": compute_adaptation_hash(analyzed_draft)})
    map_ = await adaptation_evidence_service.append_map(analyzed_map, user_id=USER, project_name=PROJECT)
    report_draft = ProfileEvaluationReport(
        schema_version="r2-profile-evaluation-report-v1",
        artifact_hash="sha256:" + "11" * 32,
        profile_ref=branch.profile_ref,
        evaluator_version="test-evaluator-v1",
        sidecar_ref=sidecar_ref,
        sidecar_digest=sidecar.content_hash,
        findings=[],
        report_digest="pending",
        created_at=datetime.now(UTC),
    )
    report = report_draft.model_copy(update={"report_digest": compute_profile_evaluation_report_digest(report_draft)})
    async with adaptation_uow_factory(session_factory)() as uow:
        await uow.repository.insert_sidecar(
            sidecar_ref.artifact_id,
            sidecar_ref.version,
            sidecar,
            user_id=USER,
            project_name=PROJECT,
        )
        await uow.repository.insert_report(report, user_id=USER, project_name=PROJECT)
        await uow.commit()

    command = _approve_command(
        map_ref=_map_ref(map_),
        profile_ref=branch.profile_ref,
        relied_report_refs=[DecisionRef(decision_id=report.report_digest, decision_digest=report.report_digest)],
    )
    with pytest.raises(AdaptationStaleDependencyError):
        await authority_service.decide_map(command, authenticated_principal=_PRINCIPAL)


async def test_decide_map_rejects_a_resolved_sidecar_with_tampered_semantic_content(
    session_factory: Factory,
    authority_service: AdaptationAuthorityService,
    adaptation_evidence_service: AdaptationEvidenceService,
) -> None:
    claimed_hash = "sha256:" + "22" * 32
    tampered_sidecar = WesternDramaAnalysis(
        schema_version="r2-western-drama-analysis-v1",
        content_hash=claimed_hash,
        format_findings=[],
        rubric_observations=["semantic content does not hash to the claimed value"],
        evidence_locations=["scene-1"],
    )
    branch = await adaptation_evidence_service.create_branch(_branch(), user_id=USER, project_name=PROJECT)
    map_draft = _map(adaptation_map_id="map-1", branch_ref=_branch_ref(branch))
    sidecar_ref = ArtifactVersionRef(
        artifact_id=compute_profile_sidecar_id(map_draft.adaptation_map_id, branch.profile_ref),
        version=map_draft.version,
        content_hash=claimed_hash,
    )
    analyzed_draft = map_draft.model_copy(update={"profile_analysis_refs": [sidecar_ref], "content_hash": "pending"})
    analyzed_map = analyzed_draft.model_copy(update={"content_hash": compute_adaptation_hash(analyzed_draft)})
    map_ = await adaptation_evidence_service.append_map(analyzed_map, user_id=USER, project_name=PROJECT)
    report_draft = ProfileEvaluationReport(
        schema_version="r2-profile-evaluation-report-v1",
        artifact_hash=map_.content_hash,
        profile_ref=branch.profile_ref,
        evaluator_version="test-evaluator-v1",
        sidecar_ref=sidecar_ref,
        sidecar_digest=claimed_hash,
        findings=[],
        report_digest="pending",
        created_at=datetime.now(UTC),
    )
    report = report_draft.model_copy(update={"report_digest": compute_profile_evaluation_report_digest(report_draft)})
    async with adaptation_uow_factory(session_factory)() as uow:
        await uow.repository.insert_sidecar(
            sidecar_ref.artifact_id,
            sidecar_ref.version,
            tampered_sidecar,
            user_id=USER,
            project_name=PROJECT,
        )
        await uow.repository.insert_report(report, user_id=USER, project_name=PROJECT)
        await uow.commit()

    command = _approve_command(
        map_ref=_map_ref(map_),
        profile_ref=branch.profile_ref,
        relied_report_refs=[DecisionRef(decision_id=report.report_digest, decision_digest=report.report_digest)],
    )
    with pytest.raises(AdaptationStaleDependencyError):
        await authority_service.decide_map(command, authenticated_principal=_PRINCIPAL)


async def test_decide_map_rejects_tampered_report_metadata_that_retains_its_digest(
    session_factory: Factory,
    authority_service: AdaptationAuthorityService,
    adaptation_evidence_service: AdaptationEvidenceService,
) -> None:
    sidecar_draft = WesternDramaAnalysis(
        schema_version="r2-western-drama-analysis-v1",
        content_hash="pending",
        format_findings=[],
        rubric_observations=["reviewed"],
        evidence_locations=["scene-1"],
    )
    sidecar = sidecar_draft.model_copy(update={"content_hash": compute_adaptation_hash(sidecar_draft)})
    branch = await adaptation_evidence_service.create_branch(_branch(), user_id=USER, project_name=PROJECT)
    map_draft = _map(adaptation_map_id="map-1", branch_ref=_branch_ref(branch))
    sidecar_ref = ArtifactVersionRef(
        artifact_id=compute_profile_sidecar_id(map_draft.adaptation_map_id, branch.profile_ref),
        version=map_draft.version,
        content_hash=sidecar.content_hash,
    )
    analyzed_draft = map_draft.model_copy(update={"profile_analysis_refs": [sidecar_ref], "content_hash": "pending"})
    analyzed_map = analyzed_draft.model_copy(update={"content_hash": compute_adaptation_hash(analyzed_draft)})
    map_ = await adaptation_evidence_service.append_map(analyzed_map, user_id=USER, project_name=PROJECT)
    report_draft = ProfileEvaluationReport(
        schema_version="r2-profile-evaluation-report-v1",
        artifact_hash=map_.content_hash,
        profile_ref=branch.profile_ref,
        evaluator_version="test-evaluator-v1",
        sidecar_ref=sidecar_ref,
        sidecar_digest=sidecar.content_hash,
        findings=[],
        report_digest="pending",
        created_at=datetime.now(UTC),
    )
    report = report_draft.model_copy(update={"report_digest": compute_profile_evaluation_report_digest(report_draft)})
    async with adaptation_uow_factory(session_factory)() as uow:
        await uow.repository.insert_sidecar(
            sidecar_ref.artifact_id,
            sidecar_ref.version,
            sidecar,
            user_id=USER,
            project_name=PROJECT,
        )
        await uow.repository.insert_report(report, user_id=USER, project_name=PROJECT)
        await uow.session.execute(
            update(AdaptationEvaluationReportModel)
            .where(
                AdaptationEvaluationReportModel.user_id == USER,
                AdaptationEvaluationReportModel.project_name == PROJECT,
                AdaptationEvaluationReportModel.report_digest == report.report_digest,
            )
            .values(evaluator_version="tampered-evaluator-v2")
        )
        await uow.commit()

    command = _approve_command(
        map_ref=_map_ref(map_),
        profile_ref=branch.profile_ref,
        relied_report_refs=[DecisionRef(decision_id=report.report_digest, decision_digest=report.report_digest)],
    )
    with pytest.raises(AdaptationStaleDependencyError):
        await authority_service.decide_map(command, authenticated_principal=_PRINCIPAL)


# --- cross-profile refs / stale policy digest -----------------------------------------


async def test_decide_map_rejects_a_cross_profile_ref(
    authority_service: AdaptationAuthorityService, adaptation_evidence_service: AdaptationEvidenceService
) -> None:
    branch, map_ = await _seed_branch_and_map(adaptation_evidence_service)
    other_profile = AdaptationProfileRef(
        profile_id=AdaptationProfileId.CN_SHORT_DRAMA_SHUANGWEN,
        profile_version=branch.profile_ref.profile_version,
        policy_pack_digest=branch.profile_ref.policy_pack_digest,
    )
    command = _approve_command(map_ref=_map_ref(map_), profile_ref=other_profile)
    with pytest.raises(AdaptationProfileMismatchError):
        await authority_service.decide_map(command, authenticated_principal=_PRINCIPAL)


async def test_decide_map_rejects_a_stale_policy_digest(
    authority_service: AdaptationAuthorityService, adaptation_evidence_service: AdaptationEvidenceService
) -> None:
    branch, map_ = await _seed_branch_and_map(adaptation_evidence_service)
    stale_profile = AdaptationProfileRef(
        profile_id=branch.profile_ref.profile_id,
        profile_version=branch.profile_ref.profile_version,
        policy_pack_digest="sha256:" + "00" * 32,
    )
    command = _approve_command(map_ref=_map_ref(map_), profile_ref=stale_profile)
    with pytest.raises(AdaptationPolicyDigestMismatchError):
        await authority_service.decide_map(command, authenticated_principal=_PRINCIPAL)


# --- exact retry / stale predecessor / identity conflict ------------------------------


async def test_decide_map_exact_retry_returns_the_same_receipt(
    authority_service: AdaptationAuthorityService, adaptation_evidence_service: AdaptationEvidenceService
) -> None:
    branch, map_ = await _seed_branch_and_map(adaptation_evidence_service)
    command = _approve_command(map_ref=_map_ref(map_), profile_ref=branch.profile_ref)
    first = await authority_service.decide_map(command, authenticated_principal=_PRINCIPAL)
    second = await authority_service.decide_map(command, authenticated_principal=_PRINCIPAL)
    assert first.decision_ref == second.decision_ref
    assert second.outcome == "EXACT_RETRY"
    assert second.current_at_return is True


async def test_decide_map_retry_after_supersession_is_not_current(
    authority_service: AdaptationAuthorityService, adaptation_evidence_service: AdaptationEvidenceService
) -> None:
    branch, map_a = await _seed_branch_and_map(adaptation_evidence_service, map_id="map-a")
    reject = _approve_command(
        map_ref=_map_ref(map_a), profile_ref=branch.profile_ref, action=AdaptationDecisionAction.REJECT
    )
    await authority_service.decide_map(reject, authenticated_principal=_PRINCIPAL)

    map_b = await adaptation_evidence_service.append_map(
        _map(adaptation_map_id="map-b", branch_ref=_branch_ref(branch)), user_id=USER, project_name=PROJECT
    )
    approve = _approve_command(
        decision_id="d-2", map_ref=_map_ref(map_b), profile_ref=branch.profile_ref, expected_predecessor_id="d-1"
    )
    await authority_service.decide_map(approve, authenticated_principal=_PRINCIPAL)

    retry_reject = await authority_service.decide_map(reject, authenticated_principal=_PRINCIPAL)
    assert retry_reject.outcome == "EXACT_RETRY"
    assert retry_reject.current_at_return is False


async def test_decide_map_rejects_a_stale_expected_predecessor(
    authority_service: AdaptationAuthorityService, adaptation_evidence_service: AdaptationEvidenceService
) -> None:
    branch, map_ = await _seed_branch_and_map(adaptation_evidence_service)
    command = _approve_command(map_ref=_map_ref(map_), profile_ref=branch.profile_ref, expected_predecessor_id="d-0")
    with pytest.raises(AdaptationStaleHeadError):
        await authority_service.decide_map(command, authenticated_principal=_PRINCIPAL)


async def test_decide_map_rejects_a_reused_id_with_a_different_command(
    authority_service: AdaptationAuthorityService, adaptation_evidence_service: AdaptationEvidenceService
) -> None:
    branch, map_a = await _seed_branch_and_map(adaptation_evidence_service, map_id="map-a")
    first = _approve_command(map_ref=_map_ref(map_a), profile_ref=branch.profile_ref)
    await authority_service.decide_map(first, authenticated_principal=_PRINCIPAL)

    map_b = await adaptation_evidence_service.append_map(
        _map(adaptation_map_id="map-b", branch_ref=_branch_ref(branch)), user_id=USER, project_name=PROJECT
    )
    conflicting = _approve_command(map_ref=_map_ref(map_b), profile_ref=branch.profile_ref)
    with pytest.raises(AdaptationIdentityConflictError):
        await authority_service.decide_map(conflicting, authenticated_principal=_PRINCIPAL)


# --- FK-valid corrupted-head integrity guards ------------------------------------------


async def test_decide_map_rejects_an_effective_pointer_at_a_reject_decision(
    authority_service: AdaptationAuthorityService, adaptation_evidence_service: AdaptationEvidenceService, corrupt_head
) -> None:
    branch, map_a = await _seed_branch_and_map(adaptation_evidence_service, map_id="map-a")
    approve = _approve_command(map_ref=_map_ref(map_a), profile_ref=branch.profile_ref)
    await authority_service.decide_map(approve, authenticated_principal=_PRINCIPAL)

    map_b = await adaptation_evidence_service.append_map(
        _map(adaptation_map_id="map-b", branch_ref=_branch_ref(branch)), user_id=USER, project_name=PROJECT
    )
    reject = _approve_command(
        decision_id="d-2",
        map_ref=_map_ref(map_b),
        profile_ref=branch.profile_ref,
        expected_predecessor_id="d-1",
        action=AdaptationDecisionAction.REJECT,
    )
    await authority_service.decide_map(reject, authenticated_principal=_PRINCIPAL)

    await corrupt_head(effective_decision_id="d-2")

    next_command = _approve_command(
        decision_id="d-3", map_ref=_map_ref(map_b), profile_ref=branch.profile_ref, expected_predecessor_id="d-2"
    )
    with pytest.raises(AdaptationAuthorityIntegrityError):
        await authority_service.decide_map(next_command, authenticated_principal=_PRINCIPAL)


async def test_decide_map_rejects_a_selected_artifact_that_disagrees_with_the_fold(
    authority_service: AdaptationAuthorityService, adaptation_evidence_service: AdaptationEvidenceService, corrupt_head
) -> None:
    branch, map_a = await _seed_branch_and_map(adaptation_evidence_service, map_id="map-a")
    approve = _approve_command(map_ref=_map_ref(map_a), profile_ref=branch.profile_ref)
    await authority_service.decide_map(approve, authenticated_principal=_PRINCIPAL)

    await corrupt_head(selected_artifact_id="map-nonexistent", selected_artifact_version=99)

    map_b = await adaptation_evidence_service.append_map(
        _map(adaptation_map_id="map-b", branch_ref=_branch_ref(branch)), user_id=USER, project_name=PROJECT
    )
    next_command = _approve_command(
        decision_id="d-2", map_ref=_map_ref(map_b), profile_ref=branch.profile_ref, expected_predecessor_id="d-1"
    )
    with pytest.raises(AdaptationAuthorityIntegrityError):
        await authority_service.decide_map(next_command, authenticated_principal=_PRINCIPAL)


async def test_decide_map_rejects_a_broken_generation(
    authority_service: AdaptationAuthorityService, adaptation_evidence_service: AdaptationEvidenceService, corrupt_head
) -> None:
    branch, map_ = await _seed_branch_and_map(adaptation_evidence_service)
    approve = _approve_command(map_ref=_map_ref(map_), profile_ref=branch.profile_ref)
    await authority_service.decide_map(approve, authenticated_principal=_PRINCIPAL)

    await corrupt_head(generation=5)

    next_command = _approve_command(
        decision_id="d-2", map_ref=_map_ref(map_), profile_ref=branch.profile_ref, expected_predecessor_id="d-1"
    )
    with pytest.raises(AdaptationAuthorityIntegrityError):
        await authority_service.decide_map(next_command, authenticated_principal=_PRINCIPAL)


async def test_decide_map_rejects_a_ghost_latest_decision(
    authority_service: AdaptationAuthorityService, adaptation_evidence_service: AdaptationEvidenceService, corrupt_head
) -> None:
    branch, map_a = await _seed_branch_and_map(adaptation_evidence_service, map_id="map-a")
    approve = _approve_command(map_ref=_map_ref(map_a), profile_ref=branch.profile_ref)
    await authority_service.decide_map(approve, authenticated_principal=_PRINCIPAL)

    map_b = await adaptation_evidence_service.append_map(
        _map(adaptation_map_id="map-b", branch_ref=_branch_ref(branch)), user_id=USER, project_name=PROJECT
    )
    reject = _approve_command(
        decision_id="d-2",
        map_ref=_map_ref(map_b),
        profile_ref=branch.profile_ref,
        expected_predecessor_id="d-1",
        action=AdaptationDecisionAction.REJECT,
    )
    await authority_service.decide_map(reject, authenticated_principal=_PRINCIPAL)

    # Corrupt latest_decision_id back to d-1 even though the true latest is d-2.
    await corrupt_head(latest_decision_id="d-1")

    next_command = _approve_command(
        decision_id="d-3", map_ref=_map_ref(map_b), profile_ref=branch.profile_ref, expected_predecessor_id="d-1"
    )
    with pytest.raises(AdaptationAuthorityIntegrityError):
        await authority_service.decide_map(next_command, authenticated_principal=_PRINCIPAL)


# --- rebuild equality / no-partial-write sanity ----------------------------------------


async def test_a_real_decision_chain_folds_to_exactly_the_stored_head(
    authority_service: AdaptationAuthorityService,
    adaptation_evidence_service: AdaptationEvidenceService,
    session_factory: Factory,
) -> None:
    branch, map_a = await _seed_branch_and_map(adaptation_evidence_service, map_id="map-a")
    approve = _approve_command(map_ref=_map_ref(map_a), profile_ref=branch.profile_ref)
    await authority_service.decide_map(approve, authenticated_principal=_PRINCIPAL)

    async with adaptation_uow_factory(session_factory)() as uow:
        head = await uow.repository.prepare_or_lock_head(
            user_id=USER, project_name=PROJECT, family=AdaptationAuthorityFamily.MAP_APPROVAL, head_key="branch-1"
        )
        assert head is not None
        decisions = await uow.repository.list_decisions_for_locked_head(
            user_id=USER, project_name=PROJECT, family=AdaptationAuthorityFamily.MAP_APPROVAL, head_key="branch-1"
        )
        assert fold_adaptation_head(decisions) == head
        await verify_locked_adaptation_selection(
            uow.repository, locked_head=head, expected_decision_id="d-1", expected_artifact_ref=_map_ref(map_a)
        )


async def test_a_validation_failure_leaves_no_decision_and_no_generation_bump(
    authority_service: AdaptationAuthorityService,
    adaptation_evidence_service: AdaptationEvidenceService,
    session_factory: Factory,
) -> None:
    branch, map_ = await _seed_branch_and_map(adaptation_evidence_service, all_entries_approved=False)
    command = _approve_command(map_ref=_map_ref(map_), profile_ref=branch.profile_ref)
    with pytest.raises(AdaptationStaleDependencyError):
        await authority_service.decide_map(command, authenticated_principal=_PRINCIPAL)

    async with adaptation_uow_factory(session_factory)() as uow:
        assert await uow.repository.get_decision_by_id(user_id=USER, project_name=PROJECT, decision_id="d-1") is None
        head = await uow.repository.prepare_or_lock_head(
            user_id=USER, project_name=PROJECT, family=AdaptationAuthorityFamily.MAP_APPROVAL, head_key="branch-1"
        )
        assert head is None
