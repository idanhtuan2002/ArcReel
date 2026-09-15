"""Integration coverage for the scoped M6 adaptation evidence adapter and UoW."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.adaptation_uow import adaptation_uow_factory
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

_NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)

USER = "u1"
OTHER_USER = "conformance"
PROJECT = "project-a"

type Factory = async_sessionmaker[AsyncSession]

_CANON_REF = ArtifactVersionRef(artifact_id="canon-1", version=1, content_hash="sha256:" + "a" * 64)
_PROFILE_REF = AdaptationProfileRef(
    profile_id=AdaptationProfileId.WESTERN_GENERIC, profile_version="1", policy_pack_digest="sha256:" + "b" * 64
)


def _branch(*, branch_id: str = "branch-1", version: int = 1) -> AdaptationBranchV2:
    return AdaptationBranchV2(
        branch_id=branch_id,
        schema_version="r2-adaptation-branch-v2",
        version=version,
        parent_branch_id=None,
        parent_canon_version=_CANON_REF,
        medium="short-drama",
        adaptation_policy=AdaptationPolicy.FAITHFUL,
        overlay_version=1,
        profile_ref=_PROFILE_REF,
        created_at=_NOW,
        created_by="showrunner-1",
    )


def _branch_ref(branch: AdaptationBranchV2, *, content_hash: str = "sha256:" + "c" * 64) -> ArtifactVersionRef:
    return ArtifactVersionRef(artifact_id=branch.branch_id, version=branch.version, content_hash=content_hash)


def _map(*, adaptation_map_id: str = "map-1", version: int = 1, branch_ref: ArtifactVersionRef) -> AdaptationMapV2:
    return AdaptationMapV2(
        adaptation_map_id=adaptation_map_id,
        schema_version="r2-adaptation-map-v2",
        version=version,
        adaptation_branch_ref=branch_ref,
        entries=[
            AdaptationMapEntry(
                entry_id="entry-1",
                source_refs=["src-1"],
                target_refs=["tgt-1"],
                operation=AdaptationOperation.PRESERVE,
                rationale="kept verbatim",
                fidelity_risk="low",
                approval_status=CreativeApprovalStatus.PROPOSED,
            )
        ],
        content_hash="sha256:" + "d" * 64,
    )


def _map_ref(map_: AdaptationMapV2, *, content_hash: str = "sha256:" + "e" * 64) -> ArtifactVersionRef:
    return ArtifactVersionRef(artifact_id=map_.adaptation_map_id, version=map_.version, content_hash=content_hash)


def _screenplay(
    *,
    screenplay_id: str = "sp-1",
    version: int = 1,
    branch_ref: ArtifactVersionRef,
    map_ref: ArtifactVersionRef,
) -> ScreenplayArtifactV2:
    return ScreenplayArtifactV2(
        screenplay_id=screenplay_id,
        schema_version="r2-screenplay-artifact-v2",
        version=version,
        adaptation_branch_ref=branch_ref,
        content_basis=ContentBasis(basis_type=ContentBasisType.ADAPTATION, basis_version="1", refs=["r1"]),
        scenes=[
            ScreenplayScene(
                scene_id="sc-1",
                purpose="open",
                duration_target=30.0,
                location_ref="loc-1",
                character_refs=["hero"],
                source_mapping_refs=["entry-1"],
                dramatic_text="The hero wakes.",
            )
        ],
        characters=["hero"],
        source_mapping_refs=["entry-1"],
        approval_status=CreativeApprovalStatus.PROPOSED,
        locked_for_direction=False,
        content_hash="sha256:" + "f" * 64,
        adaptation_map_ref=map_ref,
    )


async def test_branch_round_trips_exactly(session_factory: Factory) -> None:
    branch = _branch()
    async with adaptation_uow_factory(session_factory)() as uow:
        await uow.repository.insert_branch(branch, user_id=USER, project_name=PROJECT)
        await uow.commit()

    async with adaptation_uow_factory(session_factory)() as uow:
        fetched = await uow.repository.get_exact_branch(
            branch_id=branch.branch_id, version=branch.version, project_name=PROJECT, user_id=USER
        )
    assert fetched == branch


async def test_unknown_branch_and_cross_scope_branch_both_resolve_to_none(session_factory: Factory) -> None:
    branch = _branch()
    async with adaptation_uow_factory(session_factory)() as uow:
        await uow.repository.insert_branch(branch, user_id=USER, project_name=PROJECT)
        await uow.commit()

    async with adaptation_uow_factory(session_factory)() as uow:
        assert (
            await uow.repository.get_exact_branch(
                branch_id="does-not-exist", version=1, project_name=PROJECT, user_id=USER
            )
            is None
        )
        assert (
            await uow.repository.get_exact_branch(
                branch_id=branch.branch_id, version=branch.version, project_name=PROJECT, user_id=OTHER_USER
            )
            is None
        )


async def test_a_second_version_of_the_same_branch_is_a_legal_append(session_factory: Factory) -> None:
    v1 = _branch(version=1)
    v2 = _branch(version=2)
    async with adaptation_uow_factory(session_factory)() as uow:
        await uow.repository.insert_branch(v1, user_id=USER, project_name=PROJECT)
        await uow.repository.insert_branch(v2, user_id=USER, project_name=PROJECT)
        await uow.commit()

    async with adaptation_uow_factory(session_factory)() as uow:
        latest = await uow.repository.get_latest_branch_version(
            branch_id=v1.branch_id, project_name=PROJECT, user_id=USER
        )
    assert latest == v2


@pytest.mark.uses_db
async def test_duplicate_id_and_version_is_a_global_identity_conflict_across_tenants(session_factory: Factory) -> None:
    # The primary key is (branch_id, version) alone — no user_id component — so a
    # second tenant claiming the same tuple is a real, global collision, not just a
    # same-tenant duplicate. Marked uses_db: on SQLite's per-test in-memory schema
    # there is only ever one tenant's data to collide with anyway, but the assertion
    # (a bare PK collision, tenant-independent) is the same on both dialects.
    branch = _branch()
    async with adaptation_uow_factory(session_factory)() as uow:
        await uow.repository.insert_branch(branch, user_id=USER, project_name=PROJECT)
        await uow.commit()

    async with adaptation_uow_factory(session_factory)() as uow:
        with pytest.raises(IntegrityError):
            await uow.repository.insert_branch(branch, user_id=OTHER_USER, project_name="other-project")


async def test_map_round_trips_with_its_entries_and_profile_refs(session_factory: Factory) -> None:
    branch = _branch()
    async with adaptation_uow_factory(session_factory)() as uow:
        await uow.repository.insert_branch(branch, user_id=USER, project_name=PROJECT)
        await uow.commit()

    map_ = _map(branch_ref=_branch_ref(branch))
    async with adaptation_uow_factory(session_factory)() as uow:
        await uow.repository.insert_map(map_, user_id=USER, project_name=PROJECT)
        await uow.commit()

    async with adaptation_uow_factory(session_factory)() as uow:
        fetched = await uow.repository.get_exact_map(
            adaptation_map_id=map_.adaptation_map_id, version=map_.version, project_name=PROJECT, user_id=USER
        )
    assert fetched == map_


async def test_map_referencing_an_unknown_branch_version_is_rejected(session_factory: Factory) -> None:
    async with session_factory() as probe:
        if probe.bind.dialect.name == "sqlite":
            pytest.skip("the SQLite test engine runs with foreign keys disabled")

    branch = _branch()
    async with adaptation_uow_factory(session_factory)() as uow:
        await uow.repository.insert_branch(branch, user_id=USER, project_name=PROJECT)
        await uow.commit()

    bad_ref = ArtifactVersionRef(artifact_id=branch.branch_id, version=99, content_hash="sha256:" + "0" * 64)
    map_ = _map(branch_ref=bad_ref)
    async with adaptation_uow_factory(session_factory)() as uow:
        with pytest.raises(IntegrityError):
            await uow.repository.insert_map(map_, user_id=USER, project_name=PROJECT)


async def test_screenplay_round_trips_with_its_scenes_and_profile_refs(session_factory: Factory) -> None:
    branch = _branch()
    async with adaptation_uow_factory(session_factory)() as uow:
        await uow.repository.insert_branch(branch, user_id=USER, project_name=PROJECT)
        await uow.commit()

    map_ = _map(branch_ref=_branch_ref(branch))
    async with adaptation_uow_factory(session_factory)() as uow:
        await uow.repository.insert_map(map_, user_id=USER, project_name=PROJECT)
        await uow.commit()

    screenplay = _screenplay(branch_ref=_branch_ref(branch), map_ref=_map_ref(map_))
    async with adaptation_uow_factory(session_factory)() as uow:
        await uow.repository.insert_screenplay(screenplay, user_id=USER, project_name=PROJECT)
        await uow.commit()

    async with adaptation_uow_factory(session_factory)() as uow:
        fetched = await uow.repository.get_exact_screenplay(
            screenplay_id=screenplay.screenplay_id,
            version=screenplay.version,
            project_name=PROJECT,
            user_id=USER,
        )
    assert fetched == screenplay
