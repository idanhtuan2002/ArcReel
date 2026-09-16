"""Integration coverage for ``ProfileEvaluationService.evaluate`` (plan Task 11).

Attempt-before-work (stale artifact/policy fail before any evaluator call), atomic
successful report bundle (report + sidecar commit together), deterministic report
digest (exact retry with no duplicate write), evaluator-input failure (no partial
write), and cross-profile sidecars for the same evaluated artifact coexisting without
collision — over a real ``AdaptationRepository``/``SqlAlchemyAdaptationUnitOfWork``
against the dialect-sensitive ``session_factory`` fixture.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.adaptation_uow import adaptation_uow_factory
from r2.adaptation.errors import (
    AdaptationNotFoundError,
    AdaptationPolicyDigestMismatchError,
    AdaptationStaleDependencyError,
)
from r2.adaptation.evaluation import ProfileEvaluationService
from r2.adaptation.evidence import AdaptationEvidenceService
from r2.adaptation.hashing import compute_adaptation_hash, compute_profile_evaluation_report_digest
from r2.adaptation.profiles import _PACKS_DIR, _compute_policy_pack_digest
from r2.adaptation.shuangwen_profile import ShuangwenSourceScope
from r2.contracts.adaptation import (
    AdaptationBranchV2,
    AdaptationMapEntry,
    AdaptationMapV2,
    AdaptationOperation,
    AdaptationPolicy,
    AdaptationProfileId,
    AdaptationProfileRef,
    ArtifactVersionRef,
    ScreenplayArtifactV2,
    ScreenplayScene,
)
from r2.contracts.content_basis import ContentBasis
from r2.contracts.enums import ContentBasisType, CreativeApprovalStatus

USER = "u1"
PROJECT = "project-a"

type Factory = async_sessionmaker[AsyncSession]

_CANON_HASH = "sha256:" + "a1" * 32
_PRINCIPAL = "human:anhtuan"

_WELL_FORMED_CHAPTER_3 = (
    "第3章\n"
    "【本章时间】黄昏\n【本章地点】旧仓库\n【本章人物】阿May、阿强\n【本章起因】阿强上门催债\n"
    "【欲望】阿May想保住铺子\n【阻碍】手头现钱不够\n【局面变化】阿强放话限期收账\n"
    "【人物选择】阿May决定当面对质\n【冲突层】外部\n【情绪手法】对话推进\n【章末问题】阿May能否凑齐欠款\n"
    "【信息增量】揭示阿强背后有人指使\n【主题回响】呼应全书信任主题\n"
    "【恨】阿May被当众羞辱，铺子被贴上封条，围观人群指指点点\n"
    "【爽】阿May翻出真账本，当众对上假账，数字对不上\n"
    "【急】距离阿强设的三天限期只剩最后一夜，阿May必须找到人证\n"
    "【盼】阿May只差一张公社的证明信就能翻案\n"
    "【爽型】揭穿假账"
)


def _western_ref() -> AdaptationProfileRef:
    raw = json.loads((_PACKS_DIR / "western_generic_v1.json").read_bytes())
    return AdaptationProfileRef(
        profile_id=AdaptationProfileId.WESTERN_GENERIC,
        profile_version="v1",
        policy_pack_digest=_compute_policy_pack_digest(raw),
    )


def _shuangwen_ref() -> AdaptationProfileRef:
    raw = json.loads((_PACKS_DIR / "cn_short_drama_shuangwen_v1.json").read_bytes())
    return AdaptationProfileRef(
        profile_id=AdaptationProfileId.CN_SHORT_DRAMA_SHUANGWEN,
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


async def _seed_screenplay(
    adaptation_evidence_service: AdaptationEvidenceService,
    *,
    branch_id: str,
    map_id: str,
    screenplay_id: str,
    profile_ref: AdaptationProfileRef,
    dramatic_text: str = "INT. ROOM - DAY\nSomething happens.",
) -> ScreenplayArtifactV2:
    branch = await adaptation_evidence_service.create_branch(
        _branch(branch_id=branch_id, profile_ref=profile_ref), user_id=USER, project_name=PROJECT
    )
    branch_ref = _branch_ref(branch)
    map_ = await adaptation_evidence_service.append_map(
        _map(adaptation_map_id=map_id, branch_ref=branch_ref), user_id=USER, project_name=PROJECT
    )
    return await adaptation_evidence_service.append_screenplay(
        _screenplay(
            screenplay_id=screenplay_id, branch_ref=branch_ref, map_ref=_map_ref(map_), dramatic_text=dramatic_text
        ),
        user_id=USER,
        project_name=PROJECT,
    )


# --- happy path: atomic bundle, deterministic digest, idempotent retry ----------------


async def test_evaluate_persists_a_report_and_its_sidecar_together(
    adaptation_evidence_service: AdaptationEvidenceService,
    evaluation_service: ProfileEvaluationService,
    session_factory: Factory,
) -> None:
    profile_ref = _western_ref()
    screenplay = await _seed_screenplay(
        adaptation_evidence_service, branch_id="branch-1", map_id="map-1", screenplay_id="sp-1", profile_ref=profile_ref
    )

    report = await evaluation_service.evaluate(
        artifact_ref=_screenplay_ref(screenplay), profile_ref=profile_ref, user_id=USER, project_name=PROJECT
    )

    assert report.findings == []
    assert report.artifact_hash == screenplay.content_hash
    assert report.report_digest == compute_profile_evaluation_report_digest(report)

    async with adaptation_uow_factory(session_factory)() as uow:
        stored_report = await uow.repository.get_exact_report(
            report_digest=report.report_digest, project_name=PROJECT, user_id=USER
        )
        assert stored_report == report
        stored_sidecar = await uow.repository.get_exact_sidecar(
            sidecar_id=report.sidecar_ref.artifact_id,
            version=report.sidecar_ref.version,
            project_name=PROJECT,
            user_id=USER,
        )
        assert stored_sidecar is not None
        assert stored_sidecar.content_hash == report.sidecar_ref.content_hash == report.sidecar_digest


async def test_evaluate_is_an_idempotent_exact_retry_for_identical_content(
    adaptation_evidence_service: AdaptationEvidenceService, evaluation_service: ProfileEvaluationService
) -> None:
    profile_ref = _western_ref()
    screenplay = await _seed_screenplay(
        adaptation_evidence_service, branch_id="branch-1", map_id="map-1", screenplay_id="sp-1", profile_ref=profile_ref
    )
    artifact_ref = _screenplay_ref(screenplay)

    first = await evaluation_service.evaluate(
        artifact_ref=artifact_ref, profile_ref=profile_ref, user_id=USER, project_name=PROJECT
    )
    second = await evaluation_service.evaluate(
        artifact_ref=artifact_ref, profile_ref=profile_ref, user_id=USER, project_name=PROJECT
    )
    assert first == second
    assert first.report_digest == second.report_digest


# --- attempt-before-work: stale artifact / stale policy fail closed, no evaluator call -


async def test_evaluate_rejects_a_missing_screenplay(evaluation_service: ProfileEvaluationService) -> None:
    dangling_ref = ArtifactVersionRef(artifact_id="sp-nonexistent", version=1, content_hash="sha256:" + "d4" * 32)
    with pytest.raises(AdaptationNotFoundError):
        await evaluation_service.evaluate(
            artifact_ref=dangling_ref, profile_ref=_western_ref(), user_id=USER, project_name=PROJECT
        )


async def test_evaluate_rejects_a_stale_artifact_content_hash(
    adaptation_evidence_service: AdaptationEvidenceService, evaluation_service: ProfileEvaluationService
) -> None:
    profile_ref = _western_ref()
    screenplay = await _seed_screenplay(
        adaptation_evidence_service, branch_id="branch-1", map_id="map-1", screenplay_id="sp-1", profile_ref=profile_ref
    )
    stale_ref = ArtifactVersionRef(
        artifact_id=screenplay.screenplay_id, version=screenplay.version, content_hash="sha256:" + "e5" * 32
    )
    with pytest.raises(AdaptationStaleDependencyError):
        await evaluation_service.evaluate(
            artifact_ref=stale_ref, profile_ref=profile_ref, user_id=USER, project_name=PROJECT
        )


async def test_evaluate_rejects_a_stale_policy_digest(
    adaptation_evidence_service: AdaptationEvidenceService, evaluation_service: ProfileEvaluationService
) -> None:
    profile_ref = _western_ref()
    screenplay = await _seed_screenplay(
        adaptation_evidence_service, branch_id="branch-1", map_id="map-1", screenplay_id="sp-1", profile_ref=profile_ref
    )
    stale_profile = AdaptationProfileRef(
        profile_id=profile_ref.profile_id,
        profile_version=profile_ref.profile_version,
        policy_pack_digest="sha256:" + "00" * 32,
    )
    with pytest.raises(AdaptationPolicyDigestMismatchError):
        await evaluation_service.evaluate(
            artifact_ref=_screenplay_ref(screenplay), profile_ref=stale_profile, user_id=USER, project_name=PROJECT
        )


# --- evaluator-input failure: no partial write ----------------------------------------


async def test_evaluate_western_rejects_a_source_scope_and_writes_nothing(
    adaptation_evidence_service: AdaptationEvidenceService,
    evaluation_service: ProfileEvaluationService,
    session_factory: Factory,
) -> None:
    profile_ref = _western_ref()
    screenplay = await _seed_screenplay(
        adaptation_evidence_service, branch_id="branch-1", map_id="map-1", screenplay_id="sp-1", profile_ref=profile_ref
    )
    with pytest.raises(ValueError, match="source_scope"):
        await evaluation_service.evaluate(
            artifact_ref=_screenplay_ref(screenplay),
            profile_ref=profile_ref,
            user_id=USER,
            project_name=PROJECT,
            source_scope=ShuangwenSourceScope(chapter_start=1, chapter_end=1, source_refs=["novel-1"]),
        )
    async with adaptation_uow_factory(session_factory)() as uow:
        sidecar_id = f"{screenplay.screenplay_id}:{profile_ref.profile_id.value}"
        assert (
            await uow.repository.get_exact_sidecar(sidecar_id=sidecar_id, version=1, project_name=PROJECT, user_id=USER)
            is None
        )


async def test_evaluate_shuangwen_requires_a_source_scope(
    adaptation_evidence_service: AdaptationEvidenceService, evaluation_service: ProfileEvaluationService
) -> None:
    profile_ref = _shuangwen_ref()
    screenplay = await _seed_screenplay(
        adaptation_evidence_service,
        branch_id="branch-2",
        map_id="map-2",
        screenplay_id="sp-2",
        profile_ref=profile_ref,
        dramatic_text=_WELL_FORMED_CHAPTER_3,
    )
    with pytest.raises(ValueError, match="source_scope"):
        await evaluation_service.evaluate(
            artifact_ref=_screenplay_ref(screenplay), profile_ref=profile_ref, user_id=USER, project_name=PROJECT
        )


# --- cross-profile sidecars coexist without collision -----------------------------------


async def test_evaluating_the_same_artifact_under_two_profiles_does_not_collide(
    adaptation_evidence_service: AdaptationEvidenceService, evaluation_service: ProfileEvaluationService
) -> None:
    western_ref = _western_ref()
    shuangwen_ref = _shuangwen_ref()
    screenplay = await _seed_screenplay(
        adaptation_evidence_service,
        branch_id="branch-3",
        map_id="map-3",
        screenplay_id="sp-3",
        profile_ref=western_ref,
        dramatic_text=_WELL_FORMED_CHAPTER_3,
    )
    artifact_ref = _screenplay_ref(screenplay)

    western_report = await evaluation_service.evaluate(
        artifact_ref=artifact_ref, profile_ref=western_ref, user_id=USER, project_name=PROJECT
    )
    shuangwen_report = await evaluation_service.evaluate(
        artifact_ref=artifact_ref,
        profile_ref=shuangwen_ref,
        user_id=USER,
        project_name=PROJECT,
        source_scope=ShuangwenSourceScope(chapter_start=3, chapter_end=3, source_refs=["novel-src-1"]),
    )

    assert western_report.report_digest != shuangwen_report.report_digest
    assert western_report.sidecar_ref.artifact_id != shuangwen_report.sidecar_ref.artifact_id

    fetched_western = await evaluation_service.get_exact_report(
        report_digest=western_report.report_digest, project_name=PROJECT, user_id=USER
    )
    fetched_shuangwen = await evaluation_service.get_exact_report(
        report_digest=shuangwen_report.report_digest, project_name=PROJECT, user_id=USER
    )
    assert fetched_western == western_report
    assert fetched_shuangwen == shuangwen_report
