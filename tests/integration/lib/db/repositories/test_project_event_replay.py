"""ProjectEventRepository: durable replay over the M7-A project_events table
(M7-C Task C1). The write side already exists per authority
(ExecutionAttemptRepository, MasterAuthorityRepository); this proves the read
side allows duplicates but never gaps, and stays scoped per project."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.host_hardening import MasterAuthorityRepository, ProjectEventRepository
from r2.contracts.host_hardening import MasterHeadSnapshot, ProjectEventType

type Factory = async_sessionmaker[AsyncSession]

USER = "u1"
PROJECT = "demo"
OTHER_PROJECT = "other"
ARTIFACT_KEY = "videos/E1S01"
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


async def _promote_a_version(session: AsyncSession, *, project_name: str, master_version: int) -> None:
    authorities = MasterAuthorityRepository(session)
    await authorities.insert_head_version(
        user_id=USER,
        project_name=project_name,
        master_head_version_id=f"mhv-{project_name}-{master_version}",
        snapshot=MasterHeadSnapshot(
            artifact_key=ARTIFACT_KEY,
            master_version=master_version,
            candidate_id=f"cand-{master_version}",
            object_ref=f"/data/{project_name}/videos/cand-{master_version}.mp4",
            content_digest=f"sha256:cand-{master_version}",
            approval_record="approval",
        ),
        promoted_at=NOW,
    )
    await authorities.append_promoted_event(
        user_id=USER,
        project_name=project_name,
        snapshot=MasterHeadSnapshot(
            artifact_key=ARTIFACT_KEY,
            master_version=master_version,
            candidate_id=f"cand-{master_version}",
            object_ref=f"/data/{project_name}/videos/cand-{master_version}.mp4",
            content_digest=f"sha256:cand-{master_version}",
            approval_record="approval",
        ),
    )


async def test_high_watermark_is_zero_with_no_events(session_factory: Factory) -> None:
    async with session_factory() as session:
        watermark = await ProjectEventRepository(session).high_watermark(user_id=USER, project_name=PROJECT)
    assert watermark == 0


async def test_replay_after_none_returns_every_event_in_order(session_factory: Factory) -> None:
    async with session_factory() as session:
        await _promote_a_version(session, project_name=PROJECT, master_version=1)
        await _promote_a_version(session, project_name=PROJECT, master_version=2)
        await session.commit()

    async with session_factory() as session:
        events = await ProjectEventRepository(session).replay_after(
            user_id=USER, project_name=PROJECT, cursor=None, limit=100
        )

    assert [e.event_type for e in events] == [ProjectEventType.MASTER_PROMOTED, ProjectEventType.MASTER_PROMOTED]
    assert events[0].event_id < events[1].event_id
    assert events[1].public_payload["master_version"] == 2


async def test_replay_after_a_cursor_skips_already_seen_events(session_factory: Factory) -> None:
    async with session_factory() as session:
        await _promote_a_version(session, project_name=PROJECT, master_version=1)
        await session.commit()

    async with session_factory() as session:
        first_batch = await ProjectEventRepository(session).replay_after(
            user_id=USER, project_name=PROJECT, cursor=None, limit=100
        )
    watermark = first_batch[-1].event_id

    async with session_factory() as session:
        await _promote_a_version(session, project_name=PROJECT, master_version=2)
        await session.commit()

    async with session_factory() as session:
        second_batch = await ProjectEventRepository(session).replay_after(
            user_id=USER, project_name=PROJECT, cursor=watermark, limit=100
        )

    assert len(second_batch) == 1
    assert second_batch[0].public_payload["master_version"] == 2


async def test_replay_after_the_current_watermark_returns_nothing_new(session_factory: Factory) -> None:
    async with session_factory() as session:
        await _promote_a_version(session, project_name=PROJECT, master_version=1)
        await session.commit()

    async with session_factory() as session:
        repo = ProjectEventRepository(session)
        watermark = await repo.high_watermark(user_id=USER, project_name=PROJECT)
        events = await repo.replay_after(user_id=USER, project_name=PROJECT, cursor=watermark, limit=100)

    assert events == []


async def test_replay_is_scoped_to_the_exact_project(session_factory: Factory) -> None:
    async with session_factory() as session:
        await _promote_a_version(session, project_name=PROJECT, master_version=1)
        await _promote_a_version(session, project_name=OTHER_PROJECT, master_version=1)
        await session.commit()

    async with session_factory() as session:
        events = await ProjectEventRepository(session).replay_after(
            user_id=USER, project_name=PROJECT, cursor=None, limit=100
        )

    assert len(events) == 1
    assert events[0].project_name == PROJECT


async def test_replay_after_respects_the_limit(session_factory: Factory) -> None:
    async with session_factory() as session:
        await _promote_a_version(session, project_name=PROJECT, master_version=1)
        await _promote_a_version(session, project_name=PROJECT, master_version=2)
        await session.commit()

    async with session_factory() as session:
        events = await ProjectEventRepository(session).replay_after(
            user_id=USER, project_name=PROJECT, cursor=None, limit=1
        )

    assert len(events) == 1
    assert events[0].public_payload["master_version"] == 1
