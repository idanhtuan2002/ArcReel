"""The composed master authority on a real database (ADR-0096)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.host_hardening import CandidateObjectModel, MasterHeadVersionModel
from lib.db.repositories.host_hardening import MasterAuthorityRepository
from r2.host_hardening.master_authority import (
    CandidateObjectConflictError,
    FileMasterProjection,
    MasterDivergedError,
    m7_candidate_id,
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


async def _promote(
    factory: Factory,
    project_dir: Path,
    version_file: Path,
    *,
    generation_id: str,
    command: str,
    approval: str = "APR-1",
):
    async with factory() as session:
        return await composition.master_authority_unit(session).promote_staged(
            user_id=USER,
            project_name=PROJECT,
            project_dir=project_dir,
            artifact_key=KEY,
            generation_candidate_id=generation_id,
            version_file=version_file,
            approval_record=approval,
            command_id=command,
        )


async def _count(factory: Factory, model) -> int:
    async with factory() as session:
        return int((await session.execute(select(func.count()).select_from(model))).scalar_one())


async def test_a_staged_version_becomes_the_master_head(session_factory: Factory, tmp_path: Path) -> None:
    version = _video(tmp_path / "videos" / "versions" / "S01_v1.mp4", "one")

    head = await _promote(session_factory, tmp_path, version, generation_id="CAND-S01-V1", command="op-1")

    assert (head.master_version, head.candidate_id) == (1, m7_candidate_id(KEY, "CAND-S01-V1"))
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

    assert (head.master_version, head.candidate_id) == (2, m7_candidate_id(KEY, "CAND-S01-V2"))


async def test_changed_bytes_under_a_registered_candidate_write_nothing(
    session_factory: Factory, tmp_path: Path
) -> None:
    version = _video(tmp_path / "videos" / "versions" / "S01_v1.mp4", "one")
    await _promote(session_factory, tmp_path, version, generation_id="CAND-S01-V1", command="op-1")
    _video(version, "tampered")

    with pytest.raises(CandidateObjectConflictError):
        await _promote(session_factory, tmp_path, version, generation_id="CAND-S01-V1", command="op-2")

    assert await _count(session_factory, MasterHeadVersionModel) == 1


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
                projection=FileMasterProjection(lambda _project, key: projected.get(key)),
                database_keys=await authorities.list_current_keys(user_id=USER, project_name=PROJECT),
                projected_keys=projected,
            )

    await verify({KEY: "CAND-S01-V1"})
    await verify({})  # projection not yet written: no opinion, not a divergence
    with pytest.raises(MasterDivergedError):
        await verify({KEY: "CAND-S01-V9"})
    with pytest.raises(MasterDivergedError):
        await verify({KEY: "CAND-S01-V1", "episode_video:1:S02": "CAND-S02-V1"})
