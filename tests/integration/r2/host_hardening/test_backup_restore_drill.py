"""M7-D Task D3: the clean-target restore drill (spec section 8, H6).

Seeds a representative cross-section of the durable ID chain (candidate
objects, a promoted master head, and its durable project event) plus real
media bytes into a disposable source, creates a backup set, *destroys the
source* (drops the database, deletes the media root), restores into a
genuinely empty disposable target, and proves the restored data is both
byte-identical (verify_restored_backup_set) and resolvable through the same
repository reads the product uses (ADR-0089 P0 item 5's own bar: "selected
projects and masters remain resolvable and playable"). RPO/RTO are measured
wall-clock durations from this exact run, not assumed constants.

Scope note (see docs/r2/evidence/R2_M7_D_RECOVERY_VERIFIED.json): this seeds
representative rows directly through the same repositories the product uses,
not the full M3/M6 Golden A/B fixture pipeline -- pg_dump/pg_restore operate
on the whole database regardless of which tables are populated, so this
drill's own coverage claim is about the backup/restore mechanism and the
durable-ID read paths, not about exercising M3/M6's fixture generators.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from lib.db.repositories.host_hardening import CandidateObjectRepository, MasterAuthorityRepository
from r2.contracts.host_hardening import MasterHeadSnapshot, VerifiedCandidateObject
from r2.host_hardening.backup import create_backup_set, restore_backup_set, verify_restored_backup_set

pytestmark = pytest.mark.uses_db

USER = "u1"
PROJECT = "demo"
ARTIFACT_KEY = "videos/E1S01"
NOW = datetime.now(UTC)


def _pg_admin_url() -> str | None:
    url = os.environ.get("DATABASE_URL")
    if url and url.startswith("postgresql+asyncpg://"):
        return url
    return None


def _url_with_database(url: str, database: str) -> str:
    return f"{url.rsplit('/', 1)[0]}/{database}"


async def _create_database(admin_url: str, name: str) -> None:
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        await engine.dispose()


async def _drop_database(admin_url: str, name: str) -> None:
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": name},
            )
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    finally:
        await engine.dispose()


def _run_alembic_upgrade(url: str) -> None:
    from alembic.config import Config

    from alembic import command

    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        cfg = Config()
        cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[4] / "alembic"))
        command.upgrade(cfg, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


async def _init_schema(url: str) -> None:
    await asyncio.to_thread(_run_alembic_upgrade, url)
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO users (id, username, role, is_active, created_at, updated_at) "
                    "VALUES (:id, :username, 'user', true, NOW(), NOW()) ON CONFLICT (id) DO NOTHING"
                ),
                {"id": USER, "username": USER},
            )
    finally:
        await engine.dispose()


def _session_factory(url: str) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(create_async_engine(url), expire_on_commit=False)


@pytest.fixture
async def disposable_source_and_target(tmp_path: Path) -> AsyncIterator[dict[str, object]]:
    admin_url = _pg_admin_url()
    if admin_url is None:
        pytest.skip("restore drill needs real PostgreSQL (DATABASE_URL)")

    suffix = uuid.uuid4().hex[:12]
    source_name = f"m7d_drill_src_{suffix}"
    target_name = f"m7d_drill_tgt_{suffix}"
    source_url = _url_with_database(admin_url, source_name)
    target_url = _url_with_database(admin_url, target_name)

    await _create_database(admin_url, source_name)
    await _create_database(admin_url, target_name)
    await _init_schema(source_url)

    context = {
        "admin_url": admin_url,
        "source_name": source_name,
        "target_name": target_name,
        "source_url": source_url,
        "target_url": target_url,
        "source_media": tmp_path / "source-media",
        "target_media": tmp_path / "target-media",
        "backup_dir": tmp_path / "backup",
    }
    context["source_media"].mkdir()
    try:
        yield context
    finally:
        await _drop_database(admin_url, source_name)
        await _drop_database(admin_url, target_name)


async def test_full_restore_drill_recovers_a_destroyed_source(
    disposable_source_and_target: dict[str, object],
) -> None:
    source_url = disposable_source_and_target["source_url"]
    target_url = disposable_source_and_target["target_url"]
    source_media: Path = disposable_source_and_target["source_media"]  # type: ignore[assignment]
    target_media: Path = disposable_source_and_target["target_media"]  # type: ignore[assignment]
    backup_dir: Path = disposable_source_and_target["backup_dir"]  # type: ignore[assignment]
    assert isinstance(source_url, str)
    assert isinstance(target_url, str)

    source_factory = _session_factory(source_url)

    # --- seed a representative cross-section: two candidate objects, one
    # promoted master head, and its durable project event -- through the
    # exact repositories the product uses, with real media bytes on disk.
    candidates = []
    for i in (1, 2):
        object_ref = str(source_media / PROJECT / "videos" / f"cand-{i}.mp4")
        content = f"real video bytes for candidate {i}".encode()
        Path(object_ref).parent.mkdir(parents=True, exist_ok=True)
        Path(object_ref).write_bytes(content)  # noqa: ASYNC240 -- test fixture setup

        candidate = VerifiedCandidateObject(
            candidate_id=f"cand-{i}",
            project_name=PROJECT,
            artifact_key=ARTIFACT_KEY,
            object_ref=object_ref,
            byte_size=len(content),
            content_digest="sha256:" + hashlib.sha256(content).hexdigest(),
            media_probe_digest="sha256:probe-" + str(i),
        )
        candidates.append(candidate)
        async with source_factory() as session:
            await CandidateObjectRepository(session).insert(
                user_id=USER, project_name=PROJECT, candidate=candidate, created_at=NOW
            )
            await session.commit()

    async with source_factory() as session:
        authorities = MasterAuthorityRepository(session)
        snapshot = MasterHeadSnapshot(
            artifact_key=ARTIFACT_KEY,
            master_version=1,
            candidate_id="cand-1",
            object_ref=candidates[0].object_ref,
            content_digest=candidates[0].content_digest,
            approval_record="approval:drill",
        )
        await authorities.insert_head_version(
            user_id=USER, project_name=PROJECT, master_head_version_id="mhv-drill-1", snapshot=snapshot, promoted_at=NOW
        )
        await authorities.append_promoted_event(user_id=USER, project_name=PROJECT, snapshot=snapshot)
        await session.commit()

    last_write_at = time.monotonic()

    # --- create the backup set from the same live source.
    async with source_factory() as session:
        manifest = await create_backup_set(
            session=session,
            user_id=USER,
            project_name=PROJECT,
            backup_set_id="bset-drill",
            database_url=source_url,
            media_root=source_media,
            backup_dir=backup_dir,
            source_deployment_id="drill-local",
            release_git_sha="deadbeef",
            release_image_digest="sha256:image",
            configuration={"drill": True},
            now=NOW,
        )
    backup_created_at = time.monotonic()
    measured_rpo_seconds = round(backup_created_at - last_write_at, 3)

    assert manifest.state.value == "COMPLETE"
    assert len(manifest.media) == 2

    # --- destroy the source for real: drop the database, delete the media root.
    admin_url = disposable_source_and_target["admin_url"]
    source_name = disposable_source_and_target["source_name"]
    assert isinstance(admin_url, str)
    assert isinstance(source_name, str)
    await _drop_database(admin_url, source_name)
    shutil.rmtree(source_media)
    assert not source_media.exists()  # noqa: ASYNC240 -- single existence check

    # --- restore into the genuinely empty target and measure RTO.
    restore_started_at = time.monotonic()
    target_factory = _session_factory(target_url)
    async with target_factory() as target_session:
        await restore_backup_set(
            manifest=manifest,
            backup_dir=backup_dir,
            target_database_url=target_url,
            target_session=target_session,
            target_media_root=target_media,
        )

    async with target_factory() as target_session:
        verdict = await verify_restored_backup_set(
            manifest=manifest, session=target_session, media_root=target_media, now=NOW
        )
    restore_finished_at = time.monotonic()
    measured_rto_seconds = round(restore_finished_at - restore_started_at, 3)

    assert verdict.accepted, verdict.reason_codes
    assert verdict.checked_media_count == 2
    assert verdict.checked_master_count == 1

    # --- prove the restored data is resolvable through real product reads,
    # not just byte-identical on disk.
    async with target_factory() as target_session:
        restored_candidate = await CandidateObjectRepository(target_session).get_exact(
            user_id=USER, project_name=PROJECT, candidate_id="cand-1"
        )
        restored_head = (
            await target_session.execute(
                text(
                    "SELECT candidate_id, approval_record FROM master_head_versions "
                    "WHERE user_id = :u AND project_name = :p AND artifact_key = :a"
                ),
                {"u": USER, "p": PROJECT, "a": ARTIFACT_KEY},
            )
        ).one()
    assert restored_candidate is not None
    assert restored_candidate.content_digest == candidates[0].content_digest
    assert restored_head.candidate_id == "cand-1"
    assert restored_head.approval_record == "approval:drill"

    for restored in (
        target_media / PROJECT / "videos" / "cand-1.mp4",
        target_media / PROJECT / "videos" / "cand-2.mp4",
    ):
        assert restored.is_file()

    # A same-machine, same-process drill with no artificial delay: both
    # numbers should be small and non-negative, never assumed to be zero.
    assert measured_rpo_seconds >= 0
    assert measured_rto_seconds >= 0
