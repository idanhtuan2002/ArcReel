"""The M8-D observation repository on a real database (plan 2026-10-14 D1)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.learning import LearningObservationModel
from lib.db.repositories.learning import LearningObservationRepository
from r2.advanced_creative.errors import CommandConflictError, ObservationConflictError, ObservationNotFoundError
from r2.contracts.advanced_creative import LearningObservation
from r2.learning.observations import ObservationInvalidError
from tests.unit.r2.learning.test_observations import T0, obs

type Factory = async_sessionmaker[AsyncSession]

USER = "default"
PROJECT = "demo"


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now


async def _ingest(
    factory: Factory,
    observation: LearningObservation,
    command: str,
    *,
    clock: _Clock | None = None,
    project_name: str = PROJECT,
) -> LearningObservation:
    async with factory() as session:
        stored = await LearningObservationRepository(session, clock=clock).ingest(
            user_id=USER, project_name=project_name, observation=observation, command_id=command
        )
        await session.commit()
        return stored


async def _count(factory: Factory) -> int:
    async with factory() as session:
        return int((await session.execute(select(func.count()).select_from(LearningObservationModel))).scalar_one())


async def _repo_call(factory: Factory, method: str, **kwargs):
    async with factory() as session:
        return await getattr(LearningObservationRepository(session), method)(user_id=USER, **kwargs)


async def _skip_unless_postgres(factory: Factory) -> None:
    async with factory() as probe:
        if probe.get_bind().dialect.name != "postgresql":
            pytest.skip("concurrent admission needs PostgreSQL row locks")


async def test_ingest_stamps_server_time_and_replays_exactly(session_factory: Factory) -> None:
    clock = _Clock(T0 + timedelta(days=3))
    stored = await _ingest(session_factory, obs(), "cmd-1", clock=clock)
    assert stored.ingested_at == T0 + timedelta(days=3)

    clock.now = T0 + timedelta(days=4)
    assert await _ingest(session_factory, obs(), "cmd-1", clock=clock) == stored
    # The same observation under a new command id is the same fact, not a second row.
    assert await _ingest(session_factory, obs(ingested_at=T0), "cmd-2", clock=clock) == stored
    assert await _count(session_factory) == 1
    assert await _repo_call(session_factory, "get", project_name=PROJECT, observation_id="o1") == stored


async def test_divergent_duplicates_and_reused_commands_are_conflicts(session_factory: Factory) -> None:
    await _ingest(session_factory, obs(), "cmd-1")

    with pytest.raises(CommandConflictError):
        await _ingest(session_factory, obs("o9", source_record_id="video-9"), "cmd-1")
    with pytest.raises(ObservationConflictError, match="observation id"):
        await _ingest(session_factory, obs(metric_value=Decimal("999")), "cmd-2")
    with pytest.raises(ObservationConflictError, match="correction"):
        await _ingest(session_factory, obs("o2", metric_value=Decimal("999")), "cmd-3")
    assert await _count(session_factory) == 1


async def test_corrections_append_a_linear_chain_and_never_rewrite(session_factory: Factory) -> None:
    clock = _Clock(T0 + timedelta(days=2))
    original = await _ingest(session_factory, obs(), "cmd-1", clock=clock)
    clock.now = T0 + timedelta(days=3)
    first = await _ingest(
        session_factory, obs("o2", correction_of="o1", metric_value=Decimal("130")), "cmd-2", clock=clock
    )
    clock.now = T0 + timedelta(days=5)
    second = await _ingest(
        session_factory,
        obs("o3", correction_of="o2", metric_value=None, missing_reason="DELETED"),
        "cmd-3",
        clock=clock,
    )

    assert await _repo_call(session_factory, "chain", project_name=PROJECT, observation_id="o2") == (
        original,
        first,
        second,
    )
    assert await _repo_call(session_factory, "get", project_name=PROJECT, observation_id="o1") == original
    # A branch from a non-tip record is refused; the caller must correct the current tip.
    with pytest.raises(ObservationConflictError, match="current tip"):
        await _ingest(session_factory, obs("o4", correction_of="o1", metric_value=Decimal("1")), "cmd-4")
    with pytest.raises(ObservationNotFoundError):
        await _ingest(session_factory, obs("o5", correction_of="nope"), "cmd-5")
    with pytest.raises(ObservationInvalidError, match="identity"):
        await _ingest(session_factory, obs("o6", correction_of="o3", metric_name="likes"), "cmd-6")
    assert await _count(session_factory) == 3


async def test_reads_as_of_a_cutoff_ignore_later_corrections(session_factory: Factory) -> None:
    clock = _Clock(T0 + timedelta(days=2))
    original = await _ingest(session_factory, obs(), "cmd-1", clock=clock)
    clock.now = T0 + timedelta(days=5)
    corrected = await _ingest(
        session_factory, obs("o2", correction_of="o1", metric_value=Decimal("130")), "cmd-2", clock=clock
    )
    other = await _ingest(
        session_factory, obs("y1", source_family="internal.usage", source_record_id="call-1"), "cmd-3", clock=clock
    )

    def as_of(days: int, **kwargs):
        return _repo_call(
            session_factory, "list_as_of", project_name=PROJECT, cutoff=T0 + timedelta(days=days), **kwargs
        )

    assert await as_of(1) == ()
    assert await as_of(3) == (original,)
    assert await as_of(5) == (corrected,)
    latest = await _repo_call(session_factory, "watermark", project_name=PROJECT)
    assert latest == other.ingested_at > corrected.ingested_at
    full = await _repo_call(session_factory, "list_as_of", project_name=PROJECT, cutoff=latest)
    assert sorted(full, key=lambda item: item.observation_id) == [corrected, other]
    usage = await _repo_call(
        session_factory, "list_as_of", project_name=PROJECT, cutoff=latest, source_family="internal.usage"
    )
    assert usage == (other,)
    # A cutoff past the latest admission could still gain records, so it is refused.
    with pytest.raises(ObservationInvalidError, match="watermark"):
        await as_of(6)


async def test_scope_isolates_projects_and_lineage_must_match(session_factory: Factory) -> None:
    await _ingest(session_factory, obs(), "cmd-1")
    foreign = obs(lineage=obs().lineage.model_copy(update={"project_name": "other"}))

    with pytest.raises(ObservationInvalidError, match="another project"):
        await _ingest(session_factory, obs(), "cmd-2", project_name="other")
    stored = await _ingest(session_factory, foreign, "cmd-1", project_name="other")

    assert stored.lineage.project_name == "other"
    assert await _repo_call(session_factory, "get", project_name="third", observation_id="o1") is None
    assert await _repo_call(session_factory, "chain", project_name="third", observation_id="o1") == ()
    with pytest.raises(ObservationNotFoundError):
        await _ingest(
            session_factory,
            obs("o2", correction_of="o1", lineage=obs().lineage.model_copy(update={"project_name": "third"})),
            "cmd-9",
            project_name="third",
        )


async def test_concurrent_corrections_of_one_tip_have_one_winner(session_factory: Factory) -> None:
    await _skip_unless_postgres(session_factory)
    await _ingest(session_factory, obs(), "cmd-1")

    results = await asyncio.gather(
        _ingest(session_factory, obs("a", correction_of="o1", metric_value=Decimal("1")), "cmd-a"),
        _ingest(session_factory, obs("b", correction_of="o1", metric_value=Decimal("2")), "cmd-b"),
        return_exceptions=True,
    )

    assert sum(isinstance(result, LearningObservation) for result in results) == 1
    assert sum(isinstance(result, ObservationConflictError) for result in results) == 1
    assert await _count(session_factory) == 2


async def test_concurrent_originals_of_one_identity_have_one_winner(session_factory: Factory) -> None:
    await _skip_unless_postgres(session_factory)

    results = await asyncio.gather(
        _ingest(session_factory, obs("a", metric_value=Decimal("1")), "cmd-a"),
        _ingest(session_factory, obs("b", metric_value=Decimal("2")), "cmd-b"),
        _ingest(session_factory, obs("a", metric_value=Decimal("1")), "cmd-c"),
        return_exceptions=True,
    )

    assert sum(isinstance(result, ObservationConflictError) for result in results) == 1
    assert await _count(session_factory) == 1


async def test_adapted_platform_rows_ingest_and_correct_through_the_repository(session_factory: Factory) -> None:
    from datetime import date

    from r2.learning.adapters import observe_youtube_days

    day = date(2026, 11, 3)
    clock = _Clock(T0 + timedelta(days=40))

    def views(rows, retrieved_at):
        observed = observe_youtube_days(
            video_id="abc",
            requested_days=(day,),
            rows=rows,
            status="PUBLIC",
            lineage=obs().lineage,
            retrieved_at=retrieved_at,
        )
        return next(item for item in observed if item.metric_name == "views")

    pending = views((), clock.now)
    stored = await _ingest(session_factory, pending, "yt-1", clock=clock)
    assert stored.missing_reason == "NOT_YET_AVAILABLE"
    assert await _ingest(session_factory, views((), clock.now), "yt-1b", clock=clock) == stored

    clock.now = T0 + timedelta(days=42)
    arrived = views(
        ({"day": "2026-11-03", "views": 40, "estimatedMinutesWatched": 70, "averageViewDuration": 120},), clock.now
    )
    with pytest.raises(ObservationConflictError, match="correction"):
        await _ingest(session_factory, arrived, "yt-2", clock=clock)
    corrected = await _ingest(
        session_factory, arrived.model_copy(update={"correction_of": stored.observation_id}), "yt-3", clock=clock
    )

    def as_of(days: int):
        return _repo_call(session_factory, "list_as_of", project_name=PROJECT, cutoff=T0 + timedelta(days=days))

    assert await as_of(41) == (stored,)
    assert await as_of(42) == (corrected,)
    assert corrected.metric_value == Decimal(40)


async def test_a_replayed_command_id_is_reserved_for_its_request(session_factory: Factory) -> None:
    await _ingest(session_factory, obs(), "cmd-1")
    assert (await _ingest(session_factory, obs(), "cmd-2")).observation_id == "o1"

    with pytest.raises(CommandConflictError):
        await _ingest(session_factory, obs("o9", source_record_id="video-9"), "cmd-2")
    assert await _count(session_factory) == 1


async def test_admission_time_increases_within_a_scope_when_the_clock_steps_back(session_factory: Factory) -> None:
    clock = _Clock(T0 + timedelta(days=10))
    original = await _ingest(session_factory, obs(), "cmd-1", clock=clock)
    pinned = await _repo_call(session_factory, "list_as_of", project_name=PROJECT, cutoff=original.ingested_at)

    clock.now = T0 + timedelta(days=9)
    corrected = await _ingest(
        session_factory, obs("o2", correction_of="o1", metric_value=Decimal("5")), "cmd-2", clock=clock
    )
    other = await _ingest(session_factory, obs("y1", source_record_id="video-2"), "cmd-3", clock=clock)

    assert original.ingested_at < corrected.ingested_at < other.ingested_at
    # Evidence read at the earlier watermark does not move.
    assert await _repo_call(session_factory, "list_as_of", project_name=PROJECT, cutoff=original.ingested_at) == pinned
    assert await _repo_call(session_factory, "watermark", project_name=PROJECT) == other.ingested_at


async def test_values_beyond_digest_precision_are_refused(session_factory: Factory) -> None:
    with pytest.raises(ObservationInvalidError, match="significant digits"):
        await _ingest(session_factory, obs(metric_value=Decimal("1.00000000000000000000000000001")), "cmd-1")
    assert await _count(session_factory) == 0


async def test_identical_concurrent_corrections_replay_instead_of_conflicting(session_factory: Factory) -> None:
    await _skip_unless_postgres(session_factory)
    await _ingest(session_factory, obs(), "cmd-1")
    correction = obs("o2", correction_of="o1", metric_value=Decimal("7"))

    results = await asyncio.gather(
        _ingest(session_factory, correction, "cmd-a"),
        _ingest(session_factory, correction, "cmd-b"),
        return_exceptions=True,
    )

    assert all(isinstance(result, LearningObservation) for result in results), results
    assert results[0] == results[1]
    assert await _count(session_factory) == 2
