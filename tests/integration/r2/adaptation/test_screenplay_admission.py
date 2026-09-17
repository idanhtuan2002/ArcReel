"""Integration coverage for ``AdaptationAuthorityService.admit_screenplay_for_direction``
and ``ApprovedScreenplayReader`` (plan Task 12).

Missing/stale map approval, a blocking report, an invalid waiver, an edit between
evaluation and admission, exact retry after supersession, cross-profile refs, and
FK-valid corrupted-head integrity guards — over a real ``AdaptationRepository``/
``SqlAlchemyAdaptationUnitOfWork`` against the dialect-sensitive ``session_factory``
fixture. Real-PostgreSQL concurrency races are covered separately below (skipped on
SQLite, mirroring ``test_adaptation_concurrency.py``).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.adaptation_uow import SqlAlchemyAdaptationUnitOfWork, adaptation_uow_factory
from lib.db.models.adaptation import AdaptationHeadModel
from lib.db.repositories.adaptation import AdaptationRepository
from r2.adaptation.authority import AdaptationAuthorityService
from r2.adaptation.errors import (
    AdaptationAuthorityIntegrityError,
    AdaptationBlockingFindingUnresolvedError,
    AdaptationIdentityConflictError,
    AdaptationNotFoundError,
    AdaptationProfileMismatchError,
    AdaptationStaleDependencyError,
    AdaptationWaiverNotApplicableError,
)
from r2.adaptation.evaluation import ProfileEvaluationService, report_ref_of
from r2.adaptation.evidence import AdaptationEvidenceService
from r2.adaptation.hashing import compute_adaptation_hash
from r2.adaptation.profiles import _PACKS_DIR, _compute_policy_pack_digest
from r2.adaptation.screenplay_reader import ApprovedScreenplayReader
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
    ProfileWaiverCommand,
    ScreenplayAdmissionCommand,
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
_DEADLOCK_TIMEOUT_S = 10.0


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


@pytest.fixture
def screenplay_reader(session_factory: Factory) -> ApprovedScreenplayReader:
    return ApprovedScreenplayReader(adaptation_uow_factory(session_factory))


@pytest.fixture
def corrupt_admission_head(session_factory: Factory):
    async def _corrupt(*, screenplay_id: str, **updates: object) -> None:
        async with adaptation_uow_factory(session_factory)() as uow:
            await uow.session.execute(
                update(AdaptationHeadModel)
                .where(
                    AdaptationHeadModel.user_id == USER,
                    AdaptationHeadModel.project_name == PROJECT,
                    AdaptationHeadModel.family == AdaptationAuthorityFamily.SCREENPLAY_ADMISSION.value,
                    AdaptationHeadModel.head_key == screenplay_id,
                )
                .values(**updates)
            )
            await uow.commit()

    return _corrupt


async def _seed_admissible_proposal(
    adaptation_evidence_service: AdaptationEvidenceService,
    authority_service: AdaptationAuthorityService,
    evaluation_service: ProfileEvaluationService,
    *,
    branch_id: str = "branch-1",
    map_id: str = "map-1",
    screenplay_id: str = "sp-1",
    dramatic_text: str = "INT. ROOM - DAY\nSomething happens.",
    profile_ref: AdaptationProfileRef | None = None,
):
    """Branch -> map -> approved map -> screenplay proposal -> clean evaluation report.
    Returns ``(branch, map_approval_receipt, proposal, report)``."""
    profile_ref = profile_ref or _western_ref()
    branch = await adaptation_evidence_service.create_branch(
        _branch(branch_id=branch_id, profile_ref=profile_ref), user_id=USER, project_name=PROJECT
    )
    branch_ref = _branch_ref(branch)
    map_ = await adaptation_evidence_service.append_map(
        _map(adaptation_map_id=map_id, branch_ref=branch_ref), user_id=USER, project_name=PROJECT
    )
    map_approve = MapApprovalCommand(
        user_id=USER,
        project_name=PROJECT,
        decision_id=f"d-map-{map_id}",
        branch_id=branch_id,
        map_ref=_map_ref(map_),
        profile_ref=profile_ref,
        relied_report_refs=[],
        expected_predecessor_id=None,
        action=AdaptationDecisionAction.APPROVE,
    )
    map_receipt = await authority_service.decide_map(map_approve, authenticated_principal=_PRINCIPAL)

    proposal = await adaptation_evidence_service.append_screenplay(
        _screenplay(
            screenplay_id=screenplay_id, branch_ref=branch_ref, map_ref=_map_ref(map_), dramatic_text=dramatic_text
        ),
        user_id=USER,
        project_name=PROJECT,
    )
    report = await evaluation_service.evaluate(
        artifact_ref=_screenplay_ref(proposal), profile_ref=profile_ref, user_id=USER, project_name=PROJECT
    )
    return branch, map_receipt, proposal, report


def _admit_command(
    *,
    decision_id: str = "d-admit-1",
    branch_id: str = "branch-1",
    proposal: ScreenplayArtifactV2,
    profile_ref: AdaptationProfileRef,
    effective_map_approval_ref: DecisionRef,
    report_refs: list[DecisionRef],
    waiver_refs: list[DecisionRef] | None = None,
    expected_predecessor_id: str | None = None,
    action: AdaptationDecisionAction = AdaptationDecisionAction.ADMIT,
    admitted_screenplay: ScreenplayArtifactV2 | None = None,
) -> ScreenplayAdmissionCommand:
    admitted = admitted_screenplay or proposal.model_copy(
        update={
            "version": proposal.version + 1,
            "approval_status": CreativeApprovalStatus.APPROVED,
            "locked_for_direction": True,
            "content_hash": "pending",
        }
    )
    if admitted_screenplay is None:
        admitted = admitted.model_copy(update={"content_hash": compute_adaptation_hash(admitted)})
    return ScreenplayAdmissionCommand(
        user_id=USER,
        project_name=PROJECT,
        decision_id=decision_id,
        branch_id=branch_id,
        proposal_ref=_screenplay_ref(proposal),
        admitted_screenplay=admitted,
        profile_ref=profile_ref,
        effective_map_approval_ref=effective_map_approval_ref,
        report_refs=report_refs,
        waiver_refs=waiver_refs or [],
        expected_predecessor_id=expected_predecessor_id,
        action=action,
    )


# --- happy path: admit, reader resolves, exact retry -----------------------------------


async def test_admit_a_clean_proposal_succeeds_and_reader_resolves_it(
    authority_service: AdaptationAuthorityService,
    adaptation_evidence_service: AdaptationEvidenceService,
    evaluation_service: ProfileEvaluationService,
    screenplay_reader: ApprovedScreenplayReader,
) -> None:
    branch, map_receipt, proposal, report = await _seed_admissible_proposal(
        adaptation_evidence_service, authority_service, evaluation_service
    )
    assert report.findings == []
    command = _admit_command(
        proposal=proposal,
        profile_ref=branch.profile_ref,
        effective_map_approval_ref=map_receipt.decision_ref,
        report_refs=[report_ref_of(report)],
    )
    receipt = await authority_service.admit_screenplay_for_direction(command, authenticated_principal=_PRINCIPAL)
    assert receipt.outcome == "RECORDED"
    assert receipt.current_at_return is True

    admitted_ref = ArtifactVersionRef(
        artifact_id=command.admitted_screenplay.screenplay_id,
        version=command.admitted_screenplay.version,
        content_hash=command.admitted_screenplay.content_hash,
    )
    resolved = await screenplay_reader.get_exact_admitted(
        user_id=USER, project_name=PROJECT, screenplay_ref=admitted_ref, admission_ref=receipt.decision_ref
    )
    assert resolved.approval_status == CreativeApprovalStatus.APPROVED
    assert resolved.locked_for_direction is True
    assert resolved.version == proposal.version + 1


async def test_admit_exact_retry_returns_the_same_receipt(
    authority_service: AdaptationAuthorityService,
    adaptation_evidence_service: AdaptationEvidenceService,
    evaluation_service: ProfileEvaluationService,
) -> None:
    branch, map_receipt, proposal, report = await _seed_admissible_proposal(
        adaptation_evidence_service, authority_service, evaluation_service
    )
    command = _admit_command(
        proposal=proposal,
        profile_ref=branch.profile_ref,
        effective_map_approval_ref=map_receipt.decision_ref,
        report_refs=[report_ref_of(report)],
    )
    first = await authority_service.admit_screenplay_for_direction(command, authenticated_principal=_PRINCIPAL)
    second = await authority_service.admit_screenplay_for_direction(command, authenticated_principal=_PRINCIPAL)
    assert first.decision_ref == second.decision_ref
    assert second.outcome == "EXACT_RETRY"
    assert second.current_at_return is True


async def test_admit_rejects_a_reused_id_with_a_different_command(
    authority_service: AdaptationAuthorityService,
    adaptation_evidence_service: AdaptationEvidenceService,
    evaluation_service: ProfileEvaluationService,
) -> None:
    branch, map_receipt, proposal, report = await _seed_admissible_proposal(
        adaptation_evidence_service, authority_service, evaluation_service
    )
    first = _admit_command(
        proposal=proposal,
        profile_ref=branch.profile_ref,
        effective_map_approval_ref=map_receipt.decision_ref,
        report_refs=[report_ref_of(report)],
    )
    await authority_service.admit_screenplay_for_direction(first, authenticated_principal=_PRINCIPAL)

    conflicting = _admit_command(
        proposal=proposal,
        profile_ref=branch.profile_ref,
        effective_map_approval_ref=map_receipt.decision_ref,
        report_refs=[report_ref_of(report)],
        action=AdaptationDecisionAction.REVOKE,
    )
    with pytest.raises(AdaptationIdentityConflictError):
        await authority_service.admit_screenplay_for_direction(conflicting, authenticated_principal=_PRINCIPAL)


# --- missing / stale map approval --------------------------------------------------------


async def test_admit_rejects_a_missing_map_approval(
    authority_service: AdaptationAuthorityService,
    adaptation_evidence_service: AdaptationEvidenceService,
    evaluation_service: ProfileEvaluationService,
) -> None:
    branch, _map_receipt, proposal, report = await _seed_admissible_proposal(
        adaptation_evidence_service, authority_service, evaluation_service
    )
    dangling = DecisionRef(decision_id="d-map-nonexistent", decision_digest="sha256:" + "ff" * 32)
    command = _admit_command(
        proposal=proposal,
        profile_ref=branch.profile_ref,
        effective_map_approval_ref=dangling,
        report_refs=[report_ref_of(report)],
    )
    with pytest.raises(AdaptationNotFoundError):
        await authority_service.admit_screenplay_for_direction(command, authenticated_principal=_PRINCIPAL)


async def test_admit_rejects_a_stale_superseded_map_approval(
    authority_service: AdaptationAuthorityService,
    adaptation_evidence_service: AdaptationEvidenceService,
    evaluation_service: ProfileEvaluationService,
) -> None:
    branch, map_receipt, proposal, report = await _seed_admissible_proposal(
        adaptation_evidence_service, authority_service, evaluation_service
    )
    map_b = await adaptation_evidence_service.append_map(
        _map(adaptation_map_id="map-2", branch_ref=_branch_ref(branch)), user_id=USER, project_name=PROJECT
    )
    supersede = MapApprovalCommand(
        user_id=USER,
        project_name=PROJECT,
        decision_id="d-map-2",
        branch_id="branch-1",
        map_ref=_map_ref(map_b),
        profile_ref=branch.profile_ref,
        relied_report_refs=[],
        expected_predecessor_id=map_receipt.decision_ref.decision_id,
        action=AdaptationDecisionAction.APPROVE,
    )
    await authority_service.decide_map(supersede, authenticated_principal=_PRINCIPAL)

    command = _admit_command(
        proposal=proposal,
        profile_ref=branch.profile_ref,
        effective_map_approval_ref=map_receipt.decision_ref,
        report_refs=[report_ref_of(report)],
    )
    with pytest.raises(AdaptationAuthorityIntegrityError):
        await authority_service.admit_screenplay_for_direction(command, authenticated_principal=_PRINCIPAL)


# --- blocking report / invalid waiver ---------------------------------------------------


async def test_admit_rejects_an_unwaived_blocking_finding(
    authority_service: AdaptationAuthorityService,
    adaptation_evidence_service: AdaptationEvidenceService,
    evaluation_service: ProfileEvaluationService,
) -> None:
    branch, map_receipt, proposal, report = await _seed_admissible_proposal(
        adaptation_evidence_service,
        authority_service,
        evaluation_service,
        dramatic_text="Something happens.\nMore happens.",
    )
    assert len(report.findings) == 1
    command = _admit_command(
        proposal=proposal,
        profile_ref=branch.profile_ref,
        effective_map_approval_ref=map_receipt.decision_ref,
        report_refs=[report_ref_of(report)],
    )
    with pytest.raises(AdaptationBlockingFindingUnresolvedError):
        await authority_service.admit_screenplay_for_direction(command, authenticated_principal=_PRINCIPAL)


async def test_admit_succeeds_when_the_blocking_finding_is_waived(
    authority_service: AdaptationAuthorityService,
    adaptation_evidence_service: AdaptationEvidenceService,
    evaluation_service: ProfileEvaluationService,
) -> None:
    branch, map_receipt, proposal, report = await _seed_admissible_proposal(
        adaptation_evidence_service,
        authority_service,
        evaluation_service,
        dramatic_text="Something happens.\nMore happens.",
    )
    finding = report.findings[0]
    waive = ProfileWaiverCommand(
        user_id=USER,
        project_name=PROJECT,
        decision_id="d-waive-1",
        branch_id="branch-1",
        artifact_ref=_screenplay_ref(proposal),
        profile_ref=branch.profile_ref,
        report_ref=report_ref_of(report),
        finding_ids=[finding.finding_id],
        rule_versions=[finding.rule_version],
        rationale="acceptable for this cut",
        expected_predecessor_id=None,
        action=AdaptationDecisionAction.WAIVE,
    )
    waiver_receipt = await authority_service.decide_waiver(waive, authenticated_principal=_PRINCIPAL)

    command = _admit_command(
        proposal=proposal,
        profile_ref=branch.profile_ref,
        effective_map_approval_ref=map_receipt.decision_ref,
        report_refs=[report_ref_of(report)],
        waiver_refs=[waiver_receipt.decision_ref],
    )
    receipt = await authority_service.admit_screenplay_for_direction(command, authenticated_principal=_PRINCIPAL)
    assert receipt.outcome == "RECORDED"


async def test_admit_rejects_an_invalid_waiver_reference(
    authority_service: AdaptationAuthorityService,
    adaptation_evidence_service: AdaptationEvidenceService,
    evaluation_service: ProfileEvaluationService,
) -> None:
    branch, map_receipt, proposal, report = await _seed_admissible_proposal(
        adaptation_evidence_service,
        authority_service,
        evaluation_service,
        dramatic_text="Something happens.\nMore happens.",
    )
    dangling_waiver = DecisionRef(decision_id="d-waive-nonexistent", decision_digest="sha256:" + "ff" * 32)
    command = _admit_command(
        proposal=proposal,
        profile_ref=branch.profile_ref,
        effective_map_approval_ref=map_receipt.decision_ref,
        report_refs=[report_ref_of(report)],
        waiver_refs=[dangling_waiver],
    )
    with pytest.raises(AdaptationWaiverNotApplicableError):
        await authority_service.admit_screenplay_for_direction(command, authenticated_principal=_PRINCIPAL)


# --- edit between evaluation and admission -----------------------------------------------


async def test_admit_rejects_an_admitted_screenplay_that_edits_content(
    authority_service: AdaptationAuthorityService,
    adaptation_evidence_service: AdaptationEvidenceService,
    evaluation_service: ProfileEvaluationService,
) -> None:
    branch, map_receipt, proposal, report = await _seed_admissible_proposal(
        adaptation_evidence_service, authority_service, evaluation_service
    )
    tampered = proposal.model_copy(
        update={
            "version": proposal.version + 1,
            "approval_status": CreativeApprovalStatus.APPROVED,
            "locked_for_direction": True,
            "scenes": [proposal.scenes[0].model_copy(update={"dramatic_text": "INT. ROOM - DAY\nA different scene."})],
            "content_hash": "pending",
        }
    )
    tampered = tampered.model_copy(update={"content_hash": compute_adaptation_hash(tampered)})
    command = _admit_command(
        proposal=proposal,
        profile_ref=branch.profile_ref,
        effective_map_approval_ref=map_receipt.decision_ref,
        report_refs=[report_ref_of(report)],
        admitted_screenplay=tampered,
    )
    with pytest.raises(AdaptationStaleDependencyError):
        await authority_service.admit_screenplay_for_direction(command, authenticated_principal=_PRINCIPAL)


# --- cross-profile refs -------------------------------------------------------------------


async def test_admit_rejects_a_cross_profile_report(
    authority_service: AdaptationAuthorityService,
    adaptation_evidence_service: AdaptationEvidenceService,
    evaluation_service: ProfileEvaluationService,
) -> None:
    branch, map_receipt, proposal, report = await _seed_admissible_proposal(
        adaptation_evidence_service, authority_service, evaluation_service
    )
    other_profile = AdaptationProfileRef(
        profile_id=AdaptationProfileId.CN_SHORT_DRAMA_SHUANGWEN,
        profile_version=branch.profile_ref.profile_version,
        policy_pack_digest=branch.profile_ref.policy_pack_digest,
    )
    command = _admit_command(
        proposal=proposal,
        profile_ref=other_profile,
        effective_map_approval_ref=map_receipt.decision_ref,
        report_refs=[report_ref_of(report)],
    )
    with pytest.raises(AdaptationProfileMismatchError):
        await authority_service.admit_screenplay_for_direction(command, authenticated_principal=_PRINCIPAL)


# --- FK-valid corrupted-head integrity guards ---------------------------------------------


async def test_admit_rejects_an_effective_pointer_at_a_revoke_decision(
    authority_service: AdaptationAuthorityService,
    adaptation_evidence_service: AdaptationEvidenceService,
    evaluation_service: ProfileEvaluationService,
    corrupt_admission_head,
) -> None:
    branch, map_receipt, proposal, report = await _seed_admissible_proposal(
        adaptation_evidence_service, authority_service, evaluation_service
    )
    admit = _admit_command(
        proposal=proposal,
        profile_ref=branch.profile_ref,
        effective_map_approval_ref=map_receipt.decision_ref,
        report_refs=[report_ref_of(report)],
    )
    await authority_service.admit_screenplay_for_direction(admit, authenticated_principal=_PRINCIPAL)

    revoke = _admit_command(
        decision_id="d-admit-2",
        proposal=proposal,
        profile_ref=branch.profile_ref,
        effective_map_approval_ref=map_receipt.decision_ref,
        report_refs=[report_ref_of(report)],
        expected_predecessor_id="d-admit-1",
        action=AdaptationDecisionAction.REVOKE,
    )
    await authority_service.admit_screenplay_for_direction(revoke, authenticated_principal=_PRINCIPAL)

    await corrupt_admission_head(screenplay_id="sp-1", effective_decision_id="d-admit-2")

    next_command = _admit_command(
        decision_id="d-admit-3",
        proposal=proposal,
        profile_ref=branch.profile_ref,
        effective_map_approval_ref=map_receipt.decision_ref,
        report_refs=[report_ref_of(report)],
        expected_predecessor_id="d-admit-2",
        action=AdaptationDecisionAction.REVOKE,
    )
    with pytest.raises(AdaptationAuthorityIntegrityError):
        await authority_service.admit_screenplay_for_direction(next_command, authenticated_principal=_PRINCIPAL)


async def test_admit_rejects_a_selected_artifact_that_disagrees_with_the_fold(
    authority_service: AdaptationAuthorityService,
    adaptation_evidence_service: AdaptationEvidenceService,
    evaluation_service: ProfileEvaluationService,
    corrupt_admission_head,
) -> None:
    branch, map_receipt, proposal, report = await _seed_admissible_proposal(
        adaptation_evidence_service, authority_service, evaluation_service
    )
    admit = _admit_command(
        proposal=proposal,
        profile_ref=branch.profile_ref,
        effective_map_approval_ref=map_receipt.decision_ref,
        report_refs=[report_ref_of(report)],
    )
    await authority_service.admit_screenplay_for_direction(admit, authenticated_principal=_PRINCIPAL)

    await corrupt_admission_head(
        screenplay_id="sp-1", selected_artifact_id="sp-nonexistent", selected_artifact_version=99
    )

    next_command = _admit_command(
        decision_id="d-admit-2",
        proposal=proposal,
        profile_ref=branch.profile_ref,
        effective_map_approval_ref=map_receipt.decision_ref,
        report_refs=[report_ref_of(report)],
        expected_predecessor_id="d-admit-1",
        action=AdaptationDecisionAction.REVOKE,
    )
    with pytest.raises(AdaptationAuthorityIntegrityError):
        await authority_service.admit_screenplay_for_direction(next_command, authenticated_principal=_PRINCIPAL)


# --- concurrency (PostgreSQL only) ---------------------------------------------------------


class _BarrierBeforeHeadLockRepository(AdaptationRepository):
    def __init__(self, session: AsyncSession, barrier: asyncio.Barrier) -> None:
        super().__init__(session)
        self._barrier = barrier

    async def prepare_or_lock_head(self, *, user_id: str, project_name: str, family, head_key: str):
        if family == AdaptationAuthorityFamily.SCREENPLAY_ADMISSION:
            await self._barrier.wait()
        return await super().prepare_or_lock_head(
            user_id=user_id, project_name=project_name, family=family, head_key=head_key
        )


class _BarrierBeforeHeadLockUnitOfWork(SqlAlchemyAdaptationUnitOfWork):
    def __init__(self, session_factory: Factory, barrier: asyncio.Barrier) -> None:
        super().__init__(session_factory)
        self._barrier = barrier

    async def __aenter__(self) -> _BarrierBeforeHeadLockUnitOfWork:
        await super().__aenter__()
        self.repository = _BarrierBeforeHeadLockRepository(self.session, self._barrier)
        return self


async def _run_capturing(coro):
    try:
        return await coro
    except Exception as exc:
        return exc


async def test_two_concurrent_admissions_of_the_same_proposal_yield_one_winner(
    concurrent_session_factory: Factory,
) -> None:
    async with concurrent_session_factory() as probe:
        if probe.bind.dialect.name == "sqlite":
            pytest.skip("concurrency races need real row-level locking (PostgreSQL only)")

    evidence = AdaptationEvidenceService(adaptation_uow_factory(concurrent_session_factory))
    authority = AdaptationAuthorityService(adaptation_uow_factory(concurrent_session_factory), FakeAuthority())
    evaluation = ProfileEvaluationService(adaptation_uow_factory(concurrent_session_factory))
    branch, map_receipt, proposal, report = await _seed_admissible_proposal(evidence, authority, evaluation)

    barrier = asyncio.Barrier(2)
    racing = AdaptationAuthorityService(
        lambda: _BarrierBeforeHeadLockUnitOfWork(concurrent_session_factory, barrier), FakeAuthority()
    )

    async def run(decision_id: str):
        command = _admit_command(
            decision_id=decision_id,
            proposal=proposal,
            profile_ref=branch.profile_ref,
            effective_map_approval_ref=map_receipt.decision_ref,
            report_refs=[report_ref_of(report)],
        )
        return await racing.admit_screenplay_for_direction(command, authenticated_principal=_PRINCIPAL)

    a, b = await asyncio.wait_for(
        asyncio.gather(_run_capturing(run("d-race-a")), _run_capturing(run("d-race-b"))), timeout=_DEADLOCK_TIMEOUT_S
    )
    outcomes = sorted(type(x).__name__ for x in (a, b))
    assert outcomes == ["AdaptationDecisionReceipt", "AdaptationStaleHeadError"]

    async with adaptation_uow_factory(concurrent_session_factory)() as uow:
        decisions = await uow.repository.list_decisions_for_locked_head(
            user_id=USER,
            project_name=PROJECT,
            family=AdaptationAuthorityFamily.SCREENPLAY_ADMISSION,
            head_key=proposal.screenplay_id,
        )
        assert len(decisions) == 1
