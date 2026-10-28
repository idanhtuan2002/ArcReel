"""Run-closure repository: PostgreSQL-only authority, receipt replay, head CAS and body integrity."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.user import User
from lib.db.repositories.quality_runs import QualityRunRepository, RunCommandKey
from r2.quality.errors import CommandReplayConflictError, RequiredEvidenceMissingError, StaleHeadError
from tests.unit.r2.quality.test_runs import admitted, close, profile

type Factory = async_sessionmaker[AsyncSession]
NOW = datetime(2026, 10, 28, tzinfo=UTC)


def key(command_id: str = "seal-1") -> RunCommandKey:
    return RunCommandKey("owner", "project", "actor", "COMPLETE_RUN", command_id)


def sealed(run_id_suffix: str = "ff"):
    revision = profile()
    run = close(
        revision,
        admitted(revision, "TECHNICAL", "technical-required", "technical"),
        admitted(revision, "NARRATIVE", "review-required", "human"),
    )
    return run.model_copy(update={"run_id": "0199f00d-0000-7000-8000-0000000000" + run_id_suffix})


@pytest.fixture
async def runs_factory(session_factory: Factory) -> Factory:
    async with session_factory() as session:
        if session.get_bind().dialect.name != "postgresql":
            pytest.skip("run custody requires real PostgreSQL")
        async with session.begin():
            session.add(User(id="owner", username="owner"))
    return session_factory


async def test_sqlite_is_never_run_authority(file_session_factory: Factory) -> None:
    async with file_session_factory() as session, session.begin():
        with pytest.raises(RequiredEvidenceMissingError):
            await QualityRunRepository(session).lock_command(key())


async def test_sealed_run_receipt_replays_and_a_changed_body_conflicts(runs_factory: Factory) -> None:
    run = sealed()
    async with runs_factory() as session, session.begin():
        repository = QualityRunRepository(session)
        await repository.lock_command(key())
        digest = await repository.append_run(key(), "sha256:" + "1" * 64, run, expected_run_id=None, sealed_at=NOW)
    async with runs_factory() as session:
        repository = QualityRunRepository(session)
        receipt = await repository.receipt(key(), "sha256:" + "1" * 64)
        assert receipt is not None
        assert (receipt.result_ref, receipt.result_digest) == (run.run_id, digest)
        with pytest.raises(CommandReplayConflictError):
            await repository.receipt(key(), "sha256:" + "2" * 64)
        assert await repository.run(user_id="owner", project_name="project", run_id=run.run_id) == run
        assert (
            await repository.head(
                user_id="owner", project_name="project", subject_digest=run.subject_digest, profile_id=run.profile_id
            )
            == run.run_id
        )


async def test_head_advances_only_from_the_expected_run(runs_factory: Factory) -> None:
    first, second, third = sealed("01"), sealed("02"), sealed("03")
    async with runs_factory() as session, session.begin():
        await QualityRunRepository(session).append_run(
            key("a"), "sha256:" + "1" * 64, first, expected_run_id=None, sealed_at=NOW
        )
    with pytest.raises(StaleHeadError):
        async with runs_factory() as session, session.begin():
            await QualityRunRepository(session).append_run(
                key("b"), "sha256:" + "2" * 64, second, expected_run_id=None, sealed_at=NOW
            )
    async with runs_factory() as session, session.begin():
        await QualityRunRepository(session).append_run(
            key("c"), "sha256:" + "3" * 64, third, expected_run_id=first.run_id, sealed_at=NOW
        )
    async with runs_factory() as session:
        repository = QualityRunRepository(session)
        assert await repository.run(user_id="owner", project_name="project", run_id=second.run_id) is None
        assert (
            await repository.head(
                user_id="owner",
                project_name="project",
                subject_digest=third.subject_digest,
                profile_id=third.profile_id,
            )
            == third.run_id
        )


async def test_corrupted_run_body_or_digest_refuses_reads(runs_factory: Factory) -> None:
    run = sealed()
    async with runs_factory() as session, session.begin():
        await QualityRunRepository(session).append_run(
            key(), "sha256:" + "1" * 64, run, expected_run_id=None, sealed_at=NOW
        )
    for statement in (
        "UPDATE m10_quality_runs SET run_digest = 'sha256:' || repeat('0', 64)",
        "UPDATE m10_quality_runs SET run_json = jsonb_set(run_json::jsonb, '{execution_refs}', '[]')::json",
    ):
        async with runs_factory() as session, session.begin():
            await session.execute(sa.text("SET LOCAL session_replication_role = replica"))
            savepoint = await session.begin_nested()
            await session.execute(sa.text(statement))
            with pytest.raises(RequiredEvidenceMissingError):
                await QualityRunRepository(session).run(user_id="owner", project_name="project", run_id=run.run_id)
            await savepoint.rollback()
