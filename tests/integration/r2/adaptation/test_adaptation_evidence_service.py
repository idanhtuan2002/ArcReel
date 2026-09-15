"""Integration coverage for ``AdaptationEvidenceService`` (plan Task 6).

Branch genesis and subsequent versions, map/screenplay append, exact-retry idempotence,
identity conflicts, stale-parent rejection, cross-scope isolation and failure-before-
commit atomicity — over a real ``AdaptationRepository``/``SqlAlchemyAdaptationUnitOfWork``
against the dialect-sensitive ``session_factory`` fixture (SQLite in this suite;
PostgreSQL is exercised by the isolated repository/migration tests from Task 5).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.adaptation_uow import SqlAlchemyAdaptationUnitOfWork, adaptation_uow_factory
from r2.adaptation.errors import (
    AdaptationIdentityConflictError,
    AdaptationNotFoundError,
    AdaptationProfileMismatchError,
    AdaptationStaleDependencyError,
    AdaptationStaleHeadError,
)
from r2.adaptation.evidence import AdaptationEvidenceService
from r2.adaptation.hashing import compute_adaptation_hash
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
_OTHER_USER = "u2"

type Factory = async_sessionmaker[AsyncSession]

_CANON_HASH = "sha256:" + "a1" * 32
_UNVERIFIED_BRANCH_HASH = "sha256:" + "b2" * 32


def _branch(
    *,
    branch_id: str = "branch-1",
    version: int = 1,
    parent_branch_id: str | None = None,
    profile_id: AdaptationProfileId = AdaptationProfileId.WESTERN_GENERIC,
    profile_version: str = "v1",
    policy_pack_digest: str = "sha256:" + "c3" * 32,
    parent_canon_version: int = 1,
    overlay_version: int = 1,
    adaptation_policy: AdaptationPolicy = AdaptationPolicy.FAITHFUL,
) -> AdaptationBranchV2:
    return AdaptationBranchV2(
        branch_id=branch_id,
        schema_version="r2-adaptation-branch-v2",
        version=version,
        parent_branch_id=parent_branch_id,
        parent_canon_version=ArtifactVersionRef(
            artifact_id="canon-1", version=parent_canon_version, content_hash=_CANON_HASH
        ),
        medium="SHORT_FORM_VIDEO",
        adaptation_policy=adaptation_policy,
        overlay_version=overlay_version,
        profile_ref=AdaptationProfileRef(
            profile_id=profile_id, profile_version=profile_version, policy_pack_digest=policy_pack_digest
        ),
        created_at=datetime.now(UTC),
        created_by="human:anhtuan",
    )


def _branch_ref(branch: AdaptationBranchV2, *, content_hash: str = _UNVERIFIED_BRANCH_HASH) -> ArtifactVersionRef:
    return ArtifactVersionRef(artifact_id=branch.branch_id, version=branch.version, content_hash=content_hash)


def _map(*, adaptation_map_id: str = "map-1", version: int = 1, branch_ref: ArtifactVersionRef) -> AdaptationMapV2:
    entry = AdaptationMapEntry(
        entry_id="entry-1",
        source_refs=["src-1"],
        target_refs=["tgt-1"],
        operation=AdaptationOperation.PRESERVE,
        rationale="keep the scene",
        fidelity_risk="low",
        approval_status=CreativeApprovalStatus.DRAFT,
    )
    draft = AdaptationMapV2(
        adaptation_map_id=adaptation_map_id,
        schema_version="r2-adaptation-map-v2",
        version=version,
        adaptation_branch_ref=branch_ref,
        entries=[entry],
        profile_analysis_refs=[],
        content_hash="pending",
    )
    return draft.model_copy(update={"content_hash": compute_adaptation_hash(draft)})


def _map_ref(map_: AdaptationMapV2) -> ArtifactVersionRef:
    return ArtifactVersionRef(artifact_id=map_.adaptation_map_id, version=map_.version, content_hash=map_.content_hash)


def _screenplay(
    *,
    screenplay_id: str = "screenplay-1",
    version: int = 1,
    branch_ref: ArtifactVersionRef,
    map_ref: ArtifactVersionRef,
) -> ScreenplayArtifactV2:
    scene = ScreenplayScene(
        scene_id="scene-1",
        purpose="open",
        duration_target=30.0,
        location_ref=None,
        character_refs=["char-1"],
        source_mapping_refs=["entry-1"],
        dramatic_text="INT. ROOM - DAY",
    )
    draft = ScreenplayArtifactV2(
        screenplay_id=screenplay_id,
        schema_version="r2-screenplay-artifact-v2",
        version=version,
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


@pytest.fixture
def adaptation_evidence_service(session_factory: Factory) -> AdaptationEvidenceService:
    return AdaptationEvidenceService(adaptation_uow_factory(session_factory))


class InjectedFault(RuntimeError):
    pass


class _FaultOnCommitUnitOfWork(SqlAlchemyAdaptationUnitOfWork):
    """Flushes normally, then fails the commit — the transaction never reaches the DB."""

    async def commit(self) -> None:
        raise InjectedFault("injected fault before commit")


@pytest.fixture
def adaptation_fault_on_commit_service(session_factory: Factory) -> AdaptationEvidenceService:
    return AdaptationEvidenceService(lambda: _FaultOnCommitUnitOfWork(session_factory))


# --- branch genesis and version transitions -----------------------------------------


async def test_create_branch_genesis_persists_and_reads_back(
    adaptation_evidence_service: AdaptationEvidenceService,
) -> None:
    branch = _branch()
    recorded = await adaptation_evidence_service.create_branch(branch, user_id=USER, project_name=PROJECT)
    assert recorded == branch
    fetched = await adaptation_evidence_service.get_exact_branch(
        branch_id=branch.branch_id, version=1, project_name=PROJECT, user_id=USER
    )
    assert fetched == branch


async def test_create_branch_genesis_must_start_at_version_1(
    adaptation_evidence_service: AdaptationEvidenceService,
) -> None:
    branch = _branch(version=2)
    with pytest.raises(AdaptationStaleHeadError):
        await adaptation_evidence_service.create_branch(branch, user_id=USER, project_name=PROJECT)


async def test_create_branch_advances_to_the_next_sequential_version(
    adaptation_evidence_service: AdaptationEvidenceService,
) -> None:
    genesis = _branch()
    await adaptation_evidence_service.create_branch(genesis, user_id=USER, project_name=PROJECT)
    next_version = _branch(version=2)
    recorded = await adaptation_evidence_service.create_branch(next_version, user_id=USER, project_name=PROJECT)
    assert recorded.version == 2


async def test_create_branch_rejects_a_non_sequential_version(
    adaptation_evidence_service: AdaptationEvidenceService,
) -> None:
    await adaptation_evidence_service.create_branch(_branch(), user_id=USER, project_name=PROJECT)
    skip_version = _branch(version=3)
    with pytest.raises(AdaptationStaleHeadError):
        await adaptation_evidence_service.create_branch(skip_version, user_id=USER, project_name=PROJECT)


async def test_create_branch_rejects_a_mid_lineage_profile_change(
    adaptation_evidence_service: AdaptationEvidenceService,
) -> None:
    await adaptation_evidence_service.create_branch(_branch(), user_id=USER, project_name=PROJECT)
    changed_profile = _branch(version=2, profile_id=AdaptationProfileId.CN_SHORT_DRAMA_SHUANGWEN)
    with pytest.raises(AdaptationProfileMismatchError):
        await adaptation_evidence_service.create_branch(changed_profile, user_id=USER, project_name=PROJECT)


async def test_create_branch_rejects_a_missing_parent_branch(
    adaptation_evidence_service: AdaptationEvidenceService,
) -> None:
    orphan = _branch(branch_id="branch-orphan", parent_branch_id="branch-nonexistent")
    with pytest.raises(AdaptationNotFoundError):
        await adaptation_evidence_service.create_branch(orphan, user_id=USER, project_name=PROJECT)


async def test_create_branch_exact_retry_returns_the_original_and_writes_nothing(
    adaptation_evidence_service: AdaptationEvidenceService,
) -> None:
    branch = _branch()
    first = await adaptation_evidence_service.create_branch(branch, user_id=USER, project_name=PROJECT)
    second = await adaptation_evidence_service.create_branch(branch, user_id=USER, project_name=PROJECT)
    assert first == second == branch


async def test_create_branch_identity_conflict_on_a_different_tuple_at_the_same_version(
    adaptation_evidence_service: AdaptationEvidenceService,
) -> None:
    await adaptation_evidence_service.create_branch(_branch(), user_id=USER, project_name=PROJECT)
    conflicting = _branch().model_copy(update={"medium": "FEATURE_FILM"})
    with pytest.raises(AdaptationIdentityConflictError):
        await adaptation_evidence_service.create_branch(conflicting, user_id=USER, project_name=PROJECT)


# --- map append -----------------------------------------------------------------------


async def test_append_map_persists_and_reads_back(adaptation_evidence_service: AdaptationEvidenceService) -> None:
    branch = await adaptation_evidence_service.create_branch(_branch(), user_id=USER, project_name=PROJECT)
    map_ = _map(branch_ref=_branch_ref(branch))
    recorded = await adaptation_evidence_service.append_map(map_, user_id=USER, project_name=PROJECT)
    assert recorded == map_
    fetched = await adaptation_evidence_service.get_exact_map(
        adaptation_map_id=map_.adaptation_map_id, version=1, project_name=PROJECT, user_id=USER
    )
    assert fetched == map_


async def test_append_map_rejects_a_missing_branch(adaptation_evidence_service: AdaptationEvidenceService) -> None:
    dangling_ref = ArtifactVersionRef(artifact_id="branch-nonexistent", version=1, content_hash=_UNVERIFIED_BRANCH_HASH)
    with pytest.raises(AdaptationNotFoundError):
        await adaptation_evidence_service.append_map(_map(branch_ref=dangling_ref), user_id=USER, project_name=PROJECT)


async def test_append_map_exact_retry_returns_the_original(
    adaptation_evidence_service: AdaptationEvidenceService,
) -> None:
    branch = await adaptation_evidence_service.create_branch(_branch(), user_id=USER, project_name=PROJECT)
    map_ = _map(branch_ref=_branch_ref(branch))
    first = await adaptation_evidence_service.append_map(map_, user_id=USER, project_name=PROJECT)
    second = await adaptation_evidence_service.append_map(map_, user_id=USER, project_name=PROJECT)
    assert first == second == map_


async def test_append_map_identity_conflict_on_a_different_tuple_at_the_same_version(
    adaptation_evidence_service: AdaptationEvidenceService,
) -> None:
    branch = await adaptation_evidence_service.create_branch(_branch(), user_id=USER, project_name=PROJECT)
    branch_ref = _branch_ref(branch)
    await adaptation_evidence_service.append_map(_map(branch_ref=branch_ref), user_id=USER, project_name=PROJECT)
    other_entry = AdaptationMapEntry(
        entry_id="entry-2",
        source_refs=["src-2"],
        target_refs=["tgt-2"],
        operation=AdaptationOperation.OMIT,
        rationale="cut for pacing",
        fidelity_risk="medium",
        approval_status=CreativeApprovalStatus.DRAFT,
    )
    draft = AdaptationMapV2(
        adaptation_map_id="map-1",
        schema_version="r2-adaptation-map-v2",
        version=1,
        adaptation_branch_ref=branch_ref,
        entries=[other_entry],
        profile_analysis_refs=[],
        content_hash="pending",
    )
    conflicting = draft.model_copy(update={"content_hash": compute_adaptation_hash(draft)})
    with pytest.raises(AdaptationIdentityConflictError):
        await adaptation_evidence_service.append_map(conflicting, user_id=USER, project_name=PROJECT)


# --- screenplay append -------------------------------------------------------------------


async def test_append_screenplay_persists_and_reads_back(
    adaptation_evidence_service: AdaptationEvidenceService,
) -> None:
    branch = await adaptation_evidence_service.create_branch(_branch(), user_id=USER, project_name=PROJECT)
    branch_ref = _branch_ref(branch)
    map_ = await adaptation_evidence_service.append_map(_map(branch_ref=branch_ref), user_id=USER, project_name=PROJECT)
    screenplay = _screenplay(branch_ref=branch_ref, map_ref=_map_ref(map_))
    recorded = await adaptation_evidence_service.append_screenplay(screenplay, user_id=USER, project_name=PROJECT)
    assert recorded == screenplay
    fetched = await adaptation_evidence_service.get_exact_screenplay(
        screenplay_id=screenplay.screenplay_id, version=1, project_name=PROJECT, user_id=USER
    )
    assert fetched == screenplay


async def test_append_screenplay_rejects_a_missing_branch(
    adaptation_evidence_service: AdaptationEvidenceService,
) -> None:
    branch = await adaptation_evidence_service.create_branch(_branch(), user_id=USER, project_name=PROJECT)
    map_ = await adaptation_evidence_service.append_map(
        _map(branch_ref=_branch_ref(branch)), user_id=USER, project_name=PROJECT
    )
    dangling_branch_ref = ArtifactVersionRef(
        artifact_id="branch-nonexistent", version=1, content_hash=_UNVERIFIED_BRANCH_HASH
    )
    screenplay = _screenplay(branch_ref=dangling_branch_ref, map_ref=_map_ref(map_))
    with pytest.raises(AdaptationNotFoundError):
        await adaptation_evidence_service.append_screenplay(screenplay, user_id=USER, project_name=PROJECT)


async def test_append_screenplay_rejects_a_missing_map(adaptation_evidence_service: AdaptationEvidenceService) -> None:
    branch = await adaptation_evidence_service.create_branch(_branch(), user_id=USER, project_name=PROJECT)
    branch_ref = _branch_ref(branch)
    dangling_map_ref = ArtifactVersionRef(artifact_id="map-nonexistent", version=1, content_hash="sha256:" + "d4" * 32)
    screenplay = _screenplay(branch_ref=branch_ref, map_ref=dangling_map_ref)
    with pytest.raises(AdaptationNotFoundError):
        await adaptation_evidence_service.append_screenplay(screenplay, user_id=USER, project_name=PROJECT)


async def test_append_screenplay_rejects_a_stale_map_content_hash(
    adaptation_evidence_service: AdaptationEvidenceService,
) -> None:
    branch = await adaptation_evidence_service.create_branch(_branch(), user_id=USER, project_name=PROJECT)
    branch_ref = _branch_ref(branch)
    map_ = await adaptation_evidence_service.append_map(_map(branch_ref=branch_ref), user_id=USER, project_name=PROJECT)
    stale_map_ref = ArtifactVersionRef(
        artifact_id=map_.adaptation_map_id, version=map_.version, content_hash="sha256:" + "e5" * 32
    )
    screenplay = _screenplay(branch_ref=branch_ref, map_ref=stale_map_ref)
    with pytest.raises(AdaptationStaleDependencyError):
        await adaptation_evidence_service.append_screenplay(screenplay, user_id=USER, project_name=PROJECT)


async def test_append_screenplay_rejects_a_branch_ref_that_disagrees_with_its_maps_branch(
    adaptation_evidence_service: AdaptationEvidenceService,
) -> None:
    branch_a = await adaptation_evidence_service.create_branch(
        _branch(branch_id="branch-a"), user_id=USER, project_name=PROJECT
    )
    branch_b = await adaptation_evidence_service.create_branch(
        _branch(branch_id="branch-b"), user_id=USER, project_name=PROJECT
    )
    map_ = await adaptation_evidence_service.append_map(
        _map(branch_ref=_branch_ref(branch_a)), user_id=USER, project_name=PROJECT
    )
    screenplay = _screenplay(branch_ref=_branch_ref(branch_b), map_ref=_map_ref(map_))
    with pytest.raises(AdaptationStaleDependencyError):
        await adaptation_evidence_service.append_screenplay(screenplay, user_id=USER, project_name=PROJECT)


async def test_append_screenplay_exact_retry_returns_the_original(
    adaptation_evidence_service: AdaptationEvidenceService,
) -> None:
    branch = await adaptation_evidence_service.create_branch(_branch(), user_id=USER, project_name=PROJECT)
    branch_ref = _branch_ref(branch)
    map_ = await adaptation_evidence_service.append_map(_map(branch_ref=branch_ref), user_id=USER, project_name=PROJECT)
    screenplay = _screenplay(branch_ref=branch_ref, map_ref=_map_ref(map_))
    first = await adaptation_evidence_service.append_screenplay(screenplay, user_id=USER, project_name=PROJECT)
    second = await adaptation_evidence_service.append_screenplay(screenplay, user_id=USER, project_name=PROJECT)
    assert first == second == screenplay


async def test_append_screenplay_identity_conflict_on_a_different_tuple_at_the_same_version(
    adaptation_evidence_service: AdaptationEvidenceService,
) -> None:
    branch = await adaptation_evidence_service.create_branch(_branch(), user_id=USER, project_name=PROJECT)
    branch_ref = _branch_ref(branch)
    map_ = await adaptation_evidence_service.append_map(_map(branch_ref=branch_ref), user_id=USER, project_name=PROJECT)
    map_ref = _map_ref(map_)
    await adaptation_evidence_service.append_screenplay(
        _screenplay(branch_ref=branch_ref, map_ref=map_ref), user_id=USER, project_name=PROJECT
    )
    conflicting = _screenplay(branch_ref=branch_ref, map_ref=map_ref).model_copy(
        update={"characters": ["char-1", "char-2"]}
    )
    with pytest.raises(AdaptationIdentityConflictError):
        await adaptation_evidence_service.append_screenplay(conflicting, user_id=USER, project_name=PROJECT)


# --- cross-scope isolation ---------------------------------------------------------------


async def test_a_branch_recorded_for_one_user_does_not_resolve_for_another(
    adaptation_evidence_service: AdaptationEvidenceService,
) -> None:
    branch = await adaptation_evidence_service.create_branch(_branch(), user_id=USER, project_name=PROJECT)
    dangling_ref = _branch_ref(branch)
    with pytest.raises(AdaptationNotFoundError):
        await adaptation_evidence_service.append_map(
            _map(branch_ref=dangling_ref), user_id=_OTHER_USER, project_name=PROJECT
        )


async def test_a_branch_recorded_for_one_project_does_not_resolve_for_another(
    adaptation_evidence_service: AdaptationEvidenceService,
) -> None:
    branch = await adaptation_evidence_service.create_branch(_branch(), user_id=USER, project_name=PROJECT)
    dangling_ref = _branch_ref(branch)
    with pytest.raises(AdaptationNotFoundError):
        await adaptation_evidence_service.append_map(
            _map(branch_ref=dangling_ref), user_id=USER, project_name="project-b"
        )


# --- failure-before-commit atomicity ------------------------------------------------------


async def test_a_failure_before_commit_leaves_no_branch_row(
    adaptation_evidence_service: AdaptationEvidenceService,
    adaptation_fault_on_commit_service: AdaptationEvidenceService,
) -> None:
    branch = _branch()
    with pytest.raises(InjectedFault):
        await adaptation_fault_on_commit_service.create_branch(branch, user_id=USER, project_name=PROJECT)
    fetched = await adaptation_evidence_service.get_exact_branch(
        branch_id=branch.branch_id, version=1, project_name=PROJECT, user_id=USER
    )
    assert fetched is None


async def test_a_failure_before_commit_leaves_no_map_row(
    adaptation_evidence_service: AdaptationEvidenceService,
    adaptation_fault_on_commit_service: AdaptationEvidenceService,
) -> None:
    branch = await adaptation_evidence_service.create_branch(_branch(), user_id=USER, project_name=PROJECT)
    map_ = _map(branch_ref=_branch_ref(branch))
    with pytest.raises(InjectedFault):
        await adaptation_fault_on_commit_service.append_map(map_, user_id=USER, project_name=PROJECT)
    fetched = await adaptation_evidence_service.get_exact_map(
        adaptation_map_id=map_.adaptation_map_id, version=1, project_name=PROJECT, user_id=USER
    )
    assert fetched is None
