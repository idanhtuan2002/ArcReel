"""The composed master authority on a real database (ADR-0096)."""

from __future__ import annotations

import asyncio
import hashlib
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.candidate_store import CandidateStoreError, prepare_candidate
from lib.db.models.host_hardening import CandidateObjectModel, MasterHeadVersionModel
from lib.db.repositories.host_hardening import CandidateObjectRepository, MasterAuthorityRepository
from r2.contracts.host_hardening import CandidateIdentity
from r2.host_hardening.master_authority import (
    CandidateObjectConflictError,
    FileMasterProjection,
    MasterDivergedError,
    m7_candidate_id,
    resolve_m7_candidate_id,
    scoped_m7_candidate_id,
    stream_probe_digest,
    verify_project_masters,
)
from r2.host_hardening.promotion import PromotionReceiptReplayMismatchError
from server.services import master_authority as composition

type Factory = async_sessionmaker[AsyncSession]

USER = "default"
PROJECT = "demo"
KEY = "episode_video:1:S01"


def _video(path: Path, tag: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            *("ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x36:d=0.2"),
            *("-metadata", f"comment={tag}", "-y", str(path)),
        ],
        check=True,
    )
    return path


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


async def _promote(
    factory: Factory,
    project_dir: Path,
    version_file: Path,
    *,
    generation_id: str,
    command: str,
    approval: str = "APR-1",
    expected_digest: str | None = None,
):
    expected = expected_digest or _digest(version_file)
    async with factory() as session:
        return await composition.master_authority_unit(session).promote_staged(
            user_id=USER,
            project_name=PROJECT,
            project_dir=project_dir,
            artifact_key=KEY,
            generation_candidate_id=generation_id,
            version_file=version_file,
            expected_content_digest=expected,
            approval_record=approval,
            command_id=command,
        )


async def _count(factory: Factory, model) -> int:
    async with factory() as session:
        return int((await session.execute(select(func.count()).select_from(model))).scalar_one())


async def test_a_staged_version_becomes_the_master_head(session_factory: Factory, tmp_path: Path) -> None:
    version = _video(tmp_path / "videos" / "versions" / "S01_v1.mp4", "one")

    head = await _promote(session_factory, tmp_path, version, generation_id="CAND-S01-V1", command="op-1")

    assert (head.master_version, head.candidate_id) == (1, scoped_m7_candidate_id(USER, PROJECT, KEY, "CAND-S01-V1"))
    assert head.object_ref == str(version)
    async with session_factory() as session:
        current = await MasterAuthorityRepository(session).get_current(
            user_id=USER, project_name=PROJECT, artifact_key=KEY
        )
    assert current == head


async def test_an_exact_retry_replays_without_a_new_version(session_factory: Factory, tmp_path: Path) -> None:
    version = _video(tmp_path / "videos" / "versions" / "S01_v1.mp4", "one")
    first = await _promote(session_factory, tmp_path, version, generation_id="CAND-S01-V1", command="op-1")

    again = await _promote(session_factory, tmp_path, version, generation_id="CAND-S01-V1", command="op-1")

    assert again == first
    assert await _count(session_factory, MasterHeadVersionModel) == 1
    assert await _count(session_factory, CandidateObjectModel) == 1


async def test_a_reused_command_for_another_approval_is_refused(session_factory: Factory, tmp_path: Path) -> None:
    version = _video(tmp_path / "videos" / "versions" / "S01_v1.mp4", "one")
    await _promote(session_factory, tmp_path, version, generation_id="CAND-S01-V1", command="op-1")

    with pytest.raises(PromotionReceiptReplayMismatchError):
        await _promote(
            session_factory, tmp_path, version, generation_id="CAND-S01-V1", command="op-1", approval="APR-other"
        )


async def test_a_later_approval_advances_the_head(session_factory: Factory, tmp_path: Path) -> None:
    first = _video(tmp_path / "videos" / "versions" / "S01_v1.mp4", "one")
    second = _video(tmp_path / "videos" / "versions" / "S01_v2.mp4", "two")
    await _promote(session_factory, tmp_path, first, generation_id="CAND-S01-V1", command="op-1")

    head = await _promote(session_factory, tmp_path, second, generation_id="CAND-S01-V2", command="op-2")

    assert (head.master_version, head.candidate_id) == (2, scoped_m7_candidate_id(USER, PROJECT, KEY, "CAND-S01-V2"))


async def test_changed_bytes_under_a_registered_candidate_write_nothing(
    session_factory: Factory, tmp_path: Path
) -> None:
    version = _video(tmp_path / "videos" / "versions" / "S01_v1.mp4", "one")
    await _promote(session_factory, tmp_path, version, generation_id="CAND-S01-V1", command="op-1")
    _video(version, "tampered")

    with pytest.raises(CandidateObjectConflictError):
        await _promote(session_factory, tmp_path, version, generation_id="CAND-S01-V1", command="op-2")

    assert await _count(session_factory, MasterHeadVersionModel) == 1


async def test_bytes_changed_after_staging_are_refused_before_the_first_registration(
    session_factory: Factory, tmp_path: Path
) -> None:
    version = _video(tmp_path / "videos" / "versions" / "S01_v1.mp4", "one")
    staged = _digest(version)
    _video(version, "tampered")

    with pytest.raises(CandidateStoreError):
        await _promote(
            session_factory, tmp_path, version, generation_id="CAND-S01-V1", command="op-1", expected_digest=staged
        )

    assert await _count(session_factory, MasterHeadVersionModel) == 0
    assert await _count(session_factory, CandidateObjectModel) == 0


async def test_verify_accepts_a_matching_projection_and_refuses_a_divergent_one(
    session_factory: Factory, tmp_path: Path
) -> None:
    version = _video(tmp_path / "videos" / "versions" / "S01_v1.mp4", "one")
    await _promote(session_factory, tmp_path, version, generation_id="CAND-S01-V1", command="op-1")

    async def verify(projected: dict[str, str]) -> None:
        async with session_factory() as session:
            authorities = MasterAuthorityRepository(session)
            await verify_project_masters(
                user_id=USER,
                project_name=PROJECT,
                authorities=authorities,
                projection=FileMasterProjection(
                    lambda _project, key: projected.get(key), candidates=CandidateObjectRepository(session)
                ),
                database_keys=await authorities.list_current_keys(user_id=USER, project_name=PROJECT),
                projected_keys=projected,
            )

    await verify({KEY: "CAND-S01-V1"})
    with pytest.raises(MasterDivergedError):
        await verify({})  # a database head without its projection is unfinished or refused
    with pytest.raises(MasterDivergedError):
        await verify({KEY: "CAND-S01-V9"})
    with pytest.raises(MasterDivergedError):
        await verify({KEY: "CAND-S01-V1", "episode_video:1:S02": "CAND-S02-V1"})


async def test_a_superseded_promotion_is_not_projected(session_factory: Factory, tmp_path: Path) -> None:
    first = _video(tmp_path / "videos" / "versions" / "S01_v1.mp4", "one")
    second = _video(tmp_path / "videos" / "versions" / "S01_v2.mp4", "two")
    await _promote(session_factory, tmp_path, first, generation_id="CAND-S01-V1", command="op-1")
    await _promote(session_factory, tmp_path, second, generation_id="CAND-S01-V2", command="op-2")
    projected: list[str] = []

    async def project(name: str) -> str:
        projected.append(name)
        return name

    async def project_as(generation_id: str) -> str:
        async with session_factory() as session:
            return await composition.project_if_current(
                session,
                user_id=USER,
                project_name=PROJECT,
                artifact_key=KEY,
                candidate_id=scoped_m7_candidate_id(USER, PROJECT, KEY, generation_id),
                project=lambda: project(generation_id),
            )

    with pytest.raises(composition.MasterSupersededError):
        await project_as("CAND-S01-V1")
    assert await project_as("CAND-S01-V2") == "CAND-S01-V2"
    assert projected == ["CAND-S01-V2"]


async def test_a_projection_holds_the_artifact_until_it_commits(session_factory: Factory, tmp_path: Path) -> None:
    async with session_factory() as probe:
        if probe.get_bind().dialect.name != "postgresql":
            pytest.skip("row-level write locks between sessions need PostgreSQL")
    version = _video(tmp_path / "videos" / "versions" / "S01_v1.mp4", "one")
    await _promote(session_factory, tmp_path, version, generation_id="CAND-S01-V1", command="op-1")
    candidate = scoped_m7_candidate_id(USER, PROJECT, KEY, "CAND-S01-V1")
    release = asyncio.Event()
    started = asyncio.Event()
    order: list[str] = []

    async def slow() -> None:
        order.append("first-start")
        started.set()
        await release.wait()
        order.append("first-end")

    async def fast() -> None:
        order.append("second")

    async def project(body) -> None:
        async with session_factory() as session:
            await composition.project_if_current(
                session, user_id=USER, project_name=PROJECT, artifact_key=KEY, candidate_id=candidate, project=body
            )

    first = asyncio.create_task(project(slow))
    await started.wait()
    second = asyncio.create_task(project(fast))
    await asyncio.sleep(0.3)
    assert order == ["first-start"]
    release.set()
    await asyncio.gather(first, second)

    assert order == ["first-start", "first-end", "second"]


async def test_a_registered_candidate_is_promoted_in_the_callers_transaction(
    session_factory: Factory, tmp_path: Path
) -> None:
    from lib.db.repositories.host_hardening import CandidateObjectRepository, PromotionReceiptRepository
    from r2.host_hardening.master_authority import MasterAuthorityUnit

    first = _video(tmp_path / "videos" / "versions" / "S01_v1.mp4", "one")
    second = _video(tmp_path / "videos" / "versions" / "S01_v2.mp4", "two")
    await _promote(session_factory, tmp_path, first, generation_id="CAND-S01-V1", command="op-1")
    await _promote(session_factory, tmp_path, second, generation_id="CAND-S01-V2", command="op-2")
    first_id = scoped_m7_candidate_id(USER, PROJECT, KEY, "CAND-S01-V1")

    async def noop() -> None:
        return None

    async with session_factory() as session:
        unit = MasterAuthorityUnit(
            candidates=CandidateObjectRepository(session),
            authorities=MasterAuthorityRepository(session),
            receipts=PromotionReceiptRepository(session),
            commit=noop,
            clock=lambda: datetime.now(UTC),
        )
        head = await unit.promote_registered(
            user_id=USER,
            project_name=PROJECT,
            artifact_key=KEY,
            candidate_id=first_id,
            expected_master_version=2,
            approval_record="APR-back",
            command_id="op-3",
        )
        await session.rollback()

    assert (head.master_version, head.candidate_id) == (3, first_id)
    async with session_factory() as session:
        current = await MasterAuthorityRepository(session).get_current(
            user_id=USER, project_name=PROJECT, artifact_key=KEY
        )
    assert current is not None
    assert current.master_version == 2  # the caller rolled back; nothing was committed


async def test_verify_masters_ignores_slots_that_have_no_file_projection(
    session_factory: Factory, tmp_path: Path
) -> None:
    version = _video(tmp_path / "videos" / "versions" / "S01_v1.mp4", "one")
    await _promote(session_factory, tmp_path, version, generation_id="CAND-S01-V1", command="op-1")

    async with session_factory() as session:
        # KEY is not a manifest artifact key, so its head has no projection to compare.
        verified = await composition.verify_masters(session, user_id=USER, project_name=PROJECT, project_dir=tmp_path)

    assert verified == ()


async def _promote_in(factory: Factory, project: str, project_dir: Path, version_file: Path, *, generation_id: str):
    async with factory() as session:
        return await composition.master_authority_unit(session).promote_staged(
            user_id=USER,
            project_name=project,
            project_dir=project_dir,
            artifact_key=KEY,
            generation_candidate_id=generation_id,
            version_file=version_file,
            expected_content_digest=_digest(version_file),
            approval_record="APR-1",
            command_id=f"cmd-{project}",
        )


async def test_two_projects_of_one_user_promote_the_same_shot_and_generation_id(
    session_factory: Factory, tmp_path: Path
) -> None:
    first_dir, second_dir = tmp_path / "first", tmp_path / "second"
    first = await _promote_in(
        session_factory, "first", first_dir, _video(first_dir / "v1.mp4", "a"), generation_id="CAND-S01-V1"
    )
    second = await _promote_in(
        session_factory, "second", second_dir, _video(second_dir / "v1.mp4", "b"), generation_id="CAND-S01-V1"
    )

    assert first.candidate_id != second.candidate_id
    assert second.candidate_id == scoped_m7_candidate_id(USER, "second", KEY, "CAND-S01-V1")
    async with session_factory() as session:
        resolved = await resolve_m7_candidate_id(
            CandidateObjectRepository(session),
            user_id=USER,
            project_name="second",
            artifact_key=KEY,
            generation_candidate_id="CAND-S01-V1",
        )
    assert resolved == second.candidate_id


async def test_a_candidate_registered_under_the_legacy_id_keeps_it_in_its_own_project(
    session_factory: Factory, tmp_path: Path
) -> None:
    legacy = m7_candidate_id(KEY, "CAND-S01-V1")
    project_dir = tmp_path / "legacy"
    video = _video(project_dir / "v1.mp4", "legacy")
    async with session_factory() as session:
        await CandidateObjectRepository(session).insert(
            user_id=USER,
            project_name="legacy",
            candidate=prepare_candidate(
                identity=CandidateIdentity(
                    candidate_id=legacy,
                    user_id=USER,
                    project_name="legacy",
                    artifact_key=KEY,
                    expected_content_digest=_digest(video),
                ),
                source_file=video,
                final_path=video,
                media_root=project_dir,
                media_probe=stream_probe_digest,
            ),
            created_at=datetime.now(UTC),
        )
        await session.commit()

    head = await _promote_in(session_factory, "legacy", project_dir, video, generation_id="CAND-S01-V1")
    other_dir = tmp_path / "other"
    other = await _promote_in(
        session_factory, "other", other_dir, _video(other_dir / "v1.mp4", "other"), generation_id="CAND-S01-V1"
    )

    assert head.candidate_id == legacy
    assert other.candidate_id == scoped_m7_candidate_id(USER, "other", KEY, "CAND-S01-V1")
    async with session_factory() as session:
        scoped = FileMasterProjection(
            lambda _project, _key: "CAND-S01-V1", candidates=CandidateObjectRepository(session)
        )
        assert await scoped.get_selected_candidate_id(user_id=USER, project_name="legacy", artifact_key=KEY) == legacy
        assert await scoped.get_selected_candidate_id(user_id=USER, project_name="other", artifact_key=KEY) == (
            other.candidate_id
        )
