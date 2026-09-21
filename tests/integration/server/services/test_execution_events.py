"""DurableEventStreamService: subscribe-before-drain ordering, live wake-up
via notify(), duplicate wake-up tolerance, and idle heartbeats."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.host_hardening import CandidateObjectRepository, MasterAuthorityRepository
from r2.contracts.host_hardening import MasterHeadSnapshot, VerifiedCandidateObject
from server.services.execution_events import DurableEventStreamService

type Factory = async_sessionmaker[AsyncSession]

USER = "u1"
PROJECT = "demo"
ARTIFACT_KEY = "videos/E1S01"
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


async def _promote_a_version(session_factory: Factory, *, master_version: int) -> None:
    async with session_factory() as session:
        await CandidateObjectRepository(session).insert(
            user_id=USER,
            project_name=PROJECT,
            candidate=VerifiedCandidateObject(
                candidate_id=f"cand-{master_version}",
                project_name=PROJECT,
                artifact_key=ARTIFACT_KEY,
                object_ref=f"/data/{PROJECT}/videos/cand-{master_version}.mp4",
                byte_size=1024,
                content_digest=f"sha256:cand-{master_version}",
                media_probe_digest=f"sha256:probe-cand-{master_version}",
            ),
            created_at=NOW,
        )
        authorities = MasterAuthorityRepository(session)
        snapshot = MasterHeadSnapshot(
            artifact_key=ARTIFACT_KEY,
            master_version=master_version,
            candidate_id=f"cand-{master_version}",
            object_ref=f"/data/{PROJECT}/videos/cand-{master_version}.mp4",
            content_digest=f"sha256:cand-{master_version}",
            approval_record="approval",
        )
        await authorities.insert_head_version(
            user_id=USER,
            project_name=PROJECT,
            master_head_version_id=f"mhv-{master_version}",
            snapshot=snapshot,
            promoted_at=NOW,
        )
        await authorities.append_promoted_event(user_id=USER, project_name=PROJECT, snapshot=snapshot)
        await session.commit()


async def test_stream_drains_existing_durable_events_before_waiting(session_factory: Factory) -> None:
    await _promote_a_version(session_factory, master_version=1)
    service = DurableEventStreamService(session_factory=session_factory)

    async with service.stream(user_id=USER, project_name=PROJECT, cursor=None, idle_timeout=5.0) as stream:
        first = await asyncio.wait_for(anext(stream), timeout=2.0)

    assert first is not None
    assert first.public_payload["master_version"] == 1


async def test_notify_wakes_the_stream_to_redrain_a_new_event(session_factory: Factory) -> None:
    await _promote_a_version(session_factory, master_version=1)
    service = DurableEventStreamService(session_factory=session_factory)

    async with service.stream(user_id=USER, project_name=PROJECT, cursor=None, idle_timeout=5.0) as stream:
        first = await asyncio.wait_for(anext(stream), timeout=2.0)
        assert first is not None
        assert first.public_payload["master_version"] == 1

        await _promote_a_version(session_factory, master_version=2)
        service.notify(user_id=USER, project_name=PROJECT)

        second = await asyncio.wait_for(anext(stream), timeout=2.0)
        assert second is not None
        assert second.public_payload["master_version"] == 2


async def test_a_duplicate_notify_costs_an_empty_redrain_not_a_repeat(session_factory: Factory) -> None:
    await _promote_a_version(session_factory, master_version=1)
    service = DurableEventStreamService(session_factory=session_factory)

    async with service.stream(user_id=USER, project_name=PROJECT, cursor=None, idle_timeout=0.2) as stream:
        first = await asyncio.wait_for(anext(stream), timeout=2.0)
        assert first is not None
        assert first.public_payload["master_version"] == 1

        # Two notifications for the one durable write already drained above.
        service.notify(user_id=USER, project_name=PROJECT)
        service.notify(user_id=USER, project_name=PROJECT)

        # Both wake-ups re-drain to nothing new; the next real item is the idle
        # heartbeat, not a repeat of event 1.
        second = await asyncio.wait_for(anext(stream), timeout=2.0)
        assert second is None


async def test_a_notify_that_lands_before_the_first_drain_is_not_missed(session_factory: Factory) -> None:
    # Subscribing happens before the initial drain (see DurableEventStreamService.stream's
    # docstring); notify() called immediately after entering the context manager, before
    # the consumer has pulled anything, must still be observed rather than swallowed.
    service = DurableEventStreamService(session_factory=session_factory)

    async with service.stream(user_id=USER, project_name=PROJECT, cursor=None, idle_timeout=5.0) as stream:
        await _promote_a_version(session_factory, master_version=1)
        service.notify(user_id=USER, project_name=PROJECT)

        first = await asyncio.wait_for(anext(stream), timeout=2.0)

    assert first is not None
    assert first.public_payload["master_version"] == 1


async def test_idle_timeout_yields_a_heartbeat_when_nothing_is_pending(session_factory: Factory) -> None:
    service = DurableEventStreamService(session_factory=session_factory)

    async with service.stream(user_id=USER, project_name=PROJECT, cursor=None, idle_timeout=0.05) as stream:
        item = await asyncio.wait_for(anext(stream), timeout=2.0)

    assert item is None


async def test_stream_only_replays_events_after_the_given_cursor(session_factory: Factory) -> None:
    await _promote_a_version(session_factory, master_version=1)
    await _promote_a_version(session_factory, master_version=2)
    service = DurableEventStreamService(session_factory=session_factory)

    async with service.stream(user_id=USER, project_name=PROJECT, cursor=None, idle_timeout=5.0) as stream:
        first = await asyncio.wait_for(anext(stream), timeout=2.0)
    assert first is not None
    watermark = first.event_id

    async with service.stream(
        user_id=USER, project_name=PROJECT, cursor=watermark, idle_timeout=0.05
    ) as resumed_stream:
        resumed_first = await asyncio.wait_for(anext(resumed_stream), timeout=2.0)

    assert resumed_first is not None
    assert resumed_first.public_payload["master_version"] == 2
