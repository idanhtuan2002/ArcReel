"""Review custody reconstructs only one complete scoped frame review."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic import command
from lib.db.models.spatial_review import SpatialReviewDeliveryModel
from lib.db.models.user import User
from lib.db.repositories.spatial_review import SpatialReviewIntegrityError, SpatialReviewRepository
from r2.contracts.review_evidence import ReviewSnapshotV1


def _snapshot(now: datetime, user_id: str) -> ReviewSnapshotV1:
    fixture = Path(__file__).resolve().parents[4] / "fixtures/r2/m8c_location_binding_v1_vectors.json"
    cases = {case["name"]: case for case in json.loads(fixture.read_text())["cases"]}
    envelope = cases["binding_envelope"]["body"]
    claims = envelope["ordered_claims"]
    return ReviewSnapshotV1.model_validate(
        {
            "session_id": "a" * 32,
            "user_id": user_id,
            "project_name": "demo",
            "principal": "human:reviewer-1",
            "scene_ref": envelope["scene_ref"],
            "target_ref": envelope["target_ref"],
            "binding_id": envelope["binding_id"],
            "binding_version": 1,
            "envelope_digest": cases["binding_envelope"]["digest"],
            "core_digest": cases["binding_core"]["digest"],
            "frames": [
                {
                    "role": role,
                    "receipt_id": claim["receipt_id"],
                    "receipt_digest": claim["receipt_digest"],
                    "png_digest": "sha256:" + digit * 64,
                }
                for role, claim, digit in zip(("MASTER", "REVERSE"), claims, ("1", "2"), strict=True)
            ],
            "created_at": now - timedelta(seconds=2),
            "expires_at": now + timedelta(minutes=8),
        }
    )


@pytest.fixture
def migrated_db(alembic_cfg: tuple[Config, Path], monkeypatch: pytest.MonkeyPatch) -> str:
    cfg, db_path = alembic_cfg
    external = os.environ.get("ARCREEL_REVIEW_TEST_DATABASE_URL")
    if external is not None:
        assert external.startswith("postgresql+asyncpg://")
        assert "@127.0.0.1:" in external
        assert external.endswith("/arcreel_m8c_review_test")
        monkeypatch.setenv("DATABASE_URL", external)
    command.upgrade(cfg, "head")
    return external or f"sqlite+aiosqlite:///{db_path}"


@pytest.mark.asyncio
async def test_review_repository_requires_two_exact_acknowledgments_and_detects_tampering(
    migrated_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(migrated_db)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    user_id = "review-" + uuid4().hex[:16]
    snapshot = _snapshot(datetime.now(UTC), user_id)
    scope = {"user_id": user_id, "project_name": "demo", "principal": "human:reviewer-1", "session_id": "a" * 32}
    try:
        async with factory.begin() as session:
            session.add(User(id=user_id, username=user_id))
            await session.flush()
            repo = SpatialReviewRepository(session)
            await repo.create_session(snapshot)
            with pytest.raises(SpatialReviewIntegrityError):
                await repo.read_complete(**scope)
            for role, attempt in (("MASTER", "attempt-1"), ("REVERSE", "attempt-2")):
                await repo.record_delivery_attempt(**scope, attempt_id=attempt, role=role)
            with pytest.raises(SpatialReviewIntegrityError):
                await repo.read_complete(**scope)
            with pytest.raises(SpatialReviewIntegrityError):
                await repo.record_acknowledgment(
                    **scope,
                    attempt_id="attempt-1",
                    role="REVERSE",
                    png_digest="sha256:" + "1" * 64,
                    decoded=True,
                )
            for role, attempt, digit in (("MASTER", "attempt-1", "1"), ("REVERSE", "attempt-2", "2")):
                await repo.record_acknowledgment(
                    **scope, attempt_id=attempt, role=role, png_digest="sha256:" + digit * 64, decoded=True
                )
            evidence, digest = await repo.read_complete(**scope)
            assert evidence.snapshot.session_id == snapshot.session_id
            assert digest.startswith("sha256:")

            async def at_expiry() -> datetime:
                return snapshot.expires_at

            with monkeypatch.context() as patcher:
                patcher.setattr(repo, "_now", at_expiry)
                with pytest.raises(SpatialReviewIntegrityError):
                    await repo.consume_session(
                        **scope, expected_evidence_digest=digest, command_digest="sha256:" + "a" * 64
                    )
            with pytest.raises(SpatialReviewIntegrityError):
                await repo.consume_session(
                    **scope, expected_evidence_digest="sha256:" + "f" * 64, command_digest="sha256:" + "a" * 64
                )
            consumed = await repo.consume_session(
                **scope, expected_evidence_digest=digest, command_digest="sha256:" + "a" * 64
            )
            assert consumed.snapshot.session_id == snapshot.session_id
            with pytest.raises(SpatialReviewIntegrityError):
                await repo.consume_session(
                    **scope, expected_evidence_digest=digest, command_digest="sha256:" + "b" * 64
                )
            with pytest.raises(SpatialReviewIntegrityError):
                await repo.read_complete(**(scope | {"project_name": "foreign"}))

        async with factory.begin() as session:
            await session.execute(
                sa.update(SpatialReviewDeliveryModel)
                .where(
                    SpatialReviewDeliveryModel.user_id == user_id,
                    SpatialReviewDeliveryModel.project_name == "demo",
                    SpatialReviewDeliveryModel.role == "MASTER",
                )
                .values(recorded_at=snapshot.expires_at + timedelta(minutes=1))
            )
        async with factory.begin() as session:
            with pytest.raises(SpatialReviewIntegrityError):
                await SpatialReviewRepository(session).read_complete(**scope)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_review_consumers_serialize_on_same_session(migrated_db: str) -> None:
    if not migrated_db.startswith("postgresql+asyncpg://"):
        pytest.skip("requires PostgreSQL row-lock observation")
    engine = create_async_engine(migrated_db)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    user_id = "review-" + uuid4().hex[:16]
    snapshot = _snapshot(datetime.now(UTC), user_id)
    scope = {"user_id": user_id, "project_name": "demo", "principal": "human:reviewer-1", "session_id": "a" * 32}
    holder = factory()
    contender = factory()
    try:
        async with factory.begin() as session:
            session.add(User(id=user_id, username=user_id))
            await session.flush()
            repo = SpatialReviewRepository(session)
            await repo.create_session(snapshot)
            for role, attempt, digit in (("MASTER", "attempt-1", "1"), ("REVERSE", "attempt-2", "2")):
                await repo.record_delivery_attempt(**scope, attempt_id=attempt, role=role)
                await repo.record_acknowledgment(
                    **scope, attempt_id=attempt, role=role, png_digest="sha256:" + digit * 64, decoded=True
                )
            _, evidence_digest = await repo.read_complete(**scope)

        await holder.begin()
        holder_pid = await holder.scalar(sa.text("SELECT pg_backend_pid()"))
        await SpatialReviewRepository(holder).consume_session(
            **scope, expected_evidence_digest=evidence_digest, command_digest="sha256:" + "a" * 64
        )
        await contender.begin()
        contender_pid = await contender.scalar(sa.text("SELECT pg_backend_pid()"))
        loser = asyncio.create_task(
            SpatialReviewRepository(contender).consume_session(
                **scope, expected_evidence_digest=evidence_digest, command_digest="sha256:" + "b" * 64
            )
        )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 3
        blockers: list[int] = []
        while loop.time() < deadline and holder_pid not in blockers and not loser.done():
            async with factory() as observer:
                blockers = await observer.scalar(sa.text("SELECT pg_blocking_pids(:pid)"), {"pid": contender_pid}) or []
            await asyncio.sleep(0.03)
        assert holder_pid in blockers
        assert not loser.done()
        await holder.commit()
        with pytest.raises(SpatialReviewIntegrityError):
            await loser
        await contender.rollback()
    finally:
        await holder.close()
        await contender.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_long_transaction_cannot_consume_after_real_expiry(migrated_db: str) -> None:
    if not migrated_db.startswith("postgresql+asyncpg://"):
        pytest.skip("requires PostgreSQL transaction-clock behavior")
    engine = create_async_engine(migrated_db)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    user_id = "review-" + uuid4().hex[:16]
    now = datetime.now(UTC)
    snapshot = _snapshot(now, user_id).model_copy(update={"expires_at": now + timedelta(seconds=2)})
    scope = {"user_id": user_id, "project_name": "demo", "principal": "human:reviewer-1", "session_id": "a" * 32}
    try:
        async with factory.begin() as session:
            session.add(User(id=user_id, username=user_id))
            await session.flush()
            repo = SpatialReviewRepository(session)
            await repo.create_session(snapshot)
            for role, attempt, digit in (("MASTER", "attempt-1", "1"), ("REVERSE", "attempt-2", "2")):
                await repo.record_delivery_attempt(**scope, attempt_id=attempt, role=role)
                await repo.record_acknowledgment(
                    **scope, attempt_id=attempt, role=role, png_digest="sha256:" + digit * 64, decoded=True
                )
            _, evidence_digest = await repo.read_complete(**scope)
        async with factory.begin() as session:
            await session.scalar(sa.text("SELECT CURRENT_TIMESTAMP"))
            await asyncio.sleep(2.2)
            with pytest.raises(SpatialReviewIntegrityError):
                await SpatialReviewRepository(session).consume_session(
                    **scope, expected_evidence_digest=evidence_digest, command_digest="sha256:" + "c" * 64
                )
    finally:
        await engine.dispose()
