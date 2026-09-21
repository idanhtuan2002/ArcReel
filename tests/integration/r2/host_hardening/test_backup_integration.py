"""Real PostgreSQL + real filesystem coverage for M7-D's backup/restore engine
(spec section 8, H6): a full create -> restore -> verify round trip and every
named fault mode (missing/corrupt media, incomplete copy, changed schema,
GC race, path escape, source/target alias, non-empty restore target).

Requires two independent PostgreSQL databases on the same server (one plays
"source", one plays "target"): pg_dump/pg_restore operate at the database
level, and a real restore drill needs a genuinely separate, genuinely empty
target -- a per-test schema within one shared database (this suite's usual
``session_factory`` fixture) cannot stand in for that.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from lib.db.repositories.host_hardening import (
    ActiveAttemptReferenceCheckImpl,
    BackupSetRepository,
    CandidateObjectRepository,
    MasterHeadReferenceCheckImpl,
    PromotionReceiptRepository,
)
from r2.contracts.host_hardening import VerifiedCandidateObject
from r2.host_hardening.backup import (
    InconsistentRecoveryPointError,
    MediaIntegrityError,
    NonEmptyRestoreTargetError,
    PathEscapesMediaRootError,
    SourceTargetAliasError,
    create_backup_set,
    restore_backup_set,
    verify_restored_backup_set,
)
from r2.host_hardening.retention import CandidateRetentionPolicy, delete_candidate_if_permitted

pytestmark = pytest.mark.uses_db

USER = "u1"
PROJECT = "demo"
ARTIFACT_KEY = "videos/E1S01"
NOW = datetime(2026, 9, 21, tzinfo=UTC)


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
    """Real ``alembic upgrade head`` -- a plain ``create_all`` schema has no
    ``alembic_version`` table, and ``create_backup_set`` reads that table for
    real (a backup manifest must record the real schema identity, not a faked
    one), so this suite's source/target databases need the genuine migration
    history, not the usual per-test ``create_all`` shortcut."""
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


@pytest.fixture
async def two_databases() -> AsyncIterator[tuple[str, str]]:
    admin_url = _pg_admin_url()
    if admin_url is None:
        pytest.skip("backup/restore drill needs real PostgreSQL (DATABASE_URL)")

    suffix = uuid.uuid4().hex[:12]
    source_name = f"m7d_src_{suffix}"
    target_name = f"m7d_tgt_{suffix}"
    source_url = _url_with_database(admin_url, source_name)
    target_url = _url_with_database(admin_url, target_name)

    await _create_database(admin_url, source_name)
    await _create_database(admin_url, target_name)
    await _init_schema(source_url)
    # The target starts genuinely empty (no schema) -- that emptiness is
    # exactly what restore_backup_set's non-empty-target guard proves.
    try:
        yield source_url, target_url
    finally:
        await _drop_database(admin_url, source_name)
        await _drop_database(admin_url, target_name)


def _session_factory(url: str) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(url)
    return async_sessionmaker(engine, expire_on_commit=False)


def _object_ref_under(media_root: Path, candidate_id: str) -> str:
    """A real absolute path rooted under ``media_root`` -- ``object_ref`` is a real
    filesystem path in production, so it must actually resolve under the media
    root a test declares, not a fixed fake path unrelated to ``tmp_path``."""
    return str(media_root / PROJECT / "videos" / f"{candidate_id}.mp4")


def _candidate(candidate_id: str, *, media_root: Path, **overrides: object) -> VerifiedCandidateObject:
    defaults: dict[str, object] = {
        "candidate_id": candidate_id,
        "project_name": PROJECT,
        "artifact_key": ARTIFACT_KEY,
        "object_ref": _object_ref_under(media_root, candidate_id),
        "byte_size": 1024,
        "content_digest": "sha256:" + candidate_id,
        "media_probe_digest": "sha256:probe-" + candidate_id,
    }
    defaults.update(overrides)
    return VerifiedCandidateObject(**defaults)


def _seed_media_file(object_ref: str, content: bytes) -> tuple[int, str]:
    path = Path(object_ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return len(content), "sha256:" + hashlib.sha256(content).hexdigest()


async def _seed_one_candidate(
    session_factory: async_sessionmaker[AsyncSession], media_root: Path, candidate_id: str, content: bytes
) -> VerifiedCandidateObject:
    object_ref = _object_ref_under(media_root, candidate_id)
    byte_size, digest = _seed_media_file(object_ref, content)
    candidate = _candidate(
        candidate_id, media_root=media_root, object_ref=object_ref, byte_size=byte_size, content_digest=digest
    )
    async with session_factory() as session:
        await CandidateObjectRepository(session).insert(
            user_id=USER, project_name=PROJECT, candidate=candidate, created_at=NOW
        )
        await session.commit()
    return candidate


async def test_create_restore_verify_round_trip_accepts(two_databases: tuple[str, str], tmp_path: Path) -> None:
    source_url, target_url = two_databases
    source_media = tmp_path / "source-media"
    source_media.mkdir()
    backup_dir = tmp_path / "backup"
    target_media = tmp_path / "target-media"

    source_factory = _session_factory(source_url)
    await _seed_one_candidate(source_factory, source_media, "cand-1", b"video bytes one")
    await _seed_one_candidate(source_factory, source_media, "cand-2", b"video bytes two, longer")

    async with source_factory() as session:
        manifest = await create_backup_set(
            session=session,
            user_id=USER,
            project_name=PROJECT,
            backup_set_id="bset-1",
            database_url=source_url,
            media_root=source_media,
            backup_dir=backup_dir,
            source_deployment_id="dev-local",
            release_git_sha="deadbeef",
            release_image_digest="sha256:image",
            configuration={"env": "test"},
            now=NOW,
        )
        await session.commit()

    assert manifest.state.value == "COMPLETE"
    assert len(manifest.media) == 2
    assert "postgres" not in manifest.database_backup_ref  # never a DSN, only a filename

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

    assert verdict.accepted, verdict.reason_codes
    assert verdict.checked_media_count == 2
    assert verdict.reason_codes == ()


async def test_manifest_never_carries_the_source_credential(two_databases: tuple[str, str], tmp_path: Path) -> None:
    source_url, _target_url = two_databases
    source_media = tmp_path / "source-media"
    source_media.mkdir()
    backup_dir = tmp_path / "backup"
    source_factory = _session_factory(source_url)
    await _seed_one_candidate(source_factory, source_media, "cand-1", b"secret-adjacent bytes")

    async with source_factory() as session:
        manifest = await create_backup_set(
            session=session,
            user_id=USER,
            project_name=PROJECT,
            backup_set_id="bset-secret",
            database_url=source_url,
            media_root=source_media,
            backup_dir=backup_dir,
            source_deployment_id="dev-local",
            release_git_sha="deadbeef",
            release_image_digest="sha256:image",
            configuration={"env": "test"},
            now=NOW,
        )

    dumped = manifest.model_dump_json()
    assert source_url not in dumped
    for secret_fragment in ("postgres:postgres", "@localhost"):
        assert secret_fragment not in dumped


async def test_missing_media_file_rejects_the_backup_set(two_databases: tuple[str, str], tmp_path: Path) -> None:
    source_url, _target_url = two_databases
    source_media = tmp_path / "source-media"
    source_media.mkdir()
    backup_dir = tmp_path / "backup"
    source_factory = _session_factory(source_url)

    candidate = _candidate("cand-missing", media_root=source_media)
    async with source_factory() as session:
        await CandidateObjectRepository(session).insert(
            user_id=USER, project_name=PROJECT, candidate=candidate, created_at=NOW
        )
        await session.commit()
    # Deliberately never write the file at object_ref.

    async with source_factory() as session:
        with pytest.raises(MediaIntegrityError):
            await create_backup_set(
                session=session,
                user_id=USER,
                project_name=PROJECT,
                backup_set_id="bset-missing",
                database_url=source_url,
                media_root=source_media,
                backup_dir=backup_dir,
                source_deployment_id="dev-local",
                release_git_sha="deadbeef",
                release_image_digest="sha256:image",
                configuration={},
                now=NOW,
            )
        await session.commit()

    async with source_factory() as session:
        row = (
            await session.execute(text("SELECT state FROM backup_sets WHERE backup_set_id = 'bset-missing'"))
        ).scalar_one()
    assert row == "REJECTED"


async def test_corrupt_media_digest_rejects_the_backup_set(two_databases: tuple[str, str], tmp_path: Path) -> None:
    source_url, _target_url = two_databases
    source_media = tmp_path / "source-media"
    source_media.mkdir()
    backup_dir = tmp_path / "backup"
    source_factory = _session_factory(source_url)

    object_ref = _object_ref_under(source_media, "cand-corrupt")
    path = Path(object_ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"real bytes")  # noqa: ASYNC240 -- single local-file write in test setup
    candidate = _candidate(
        "cand-corrupt",
        media_root=source_media,
        object_ref=object_ref,
        byte_size=len(b"real bytes"),
        content_digest="sha256:not-the-real-digest",
    )
    async with source_factory() as session:
        await CandidateObjectRepository(session).insert(
            user_id=USER, project_name=PROJECT, candidate=candidate, created_at=NOW
        )
        await session.commit()

    async with source_factory() as session:
        with pytest.raises(MediaIntegrityError):
            await create_backup_set(
                session=session,
                user_id=USER,
                project_name=PROJECT,
                backup_set_id="bset-corrupt",
                database_url=source_url,
                media_root=source_media,
                backup_dir=backup_dir,
                source_deployment_id="dev-local",
                release_git_sha="deadbeef",
                release_image_digest="sha256:image",
                configuration={},
                now=NOW,
            )


async def test_a_candidate_added_mid_backup_is_treated_as_an_inconsistent_recovery_point(
    two_databases: tuple[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_url, _target_url = two_databases
    source_media = tmp_path / "source-media"
    source_media.mkdir()
    backup_dir = tmp_path / "backup"
    source_factory = _session_factory(source_url)
    await _seed_one_candidate(source_factory, source_media, "cand-1", b"bytes")

    import r2.host_hardening.backup as backup_module

    real_run_subprocess = backup_module._run_subprocess

    async def _sneaky_insert_then_dump(argv: list[str]) -> None:
        async with source_factory() as sneaky_session:
            await CandidateObjectRepository(sneaky_session).insert(
                user_id=USER,
                project_name=PROJECT,
                candidate=_candidate("cand-snuck-in", media_root=source_media),
                created_at=NOW,
            )
            await sneaky_session.commit()
        await real_run_subprocess(argv)

    monkeypatch.setattr(backup_module, "_run_subprocess", _sneaky_insert_then_dump)

    async with source_factory() as session:
        with pytest.raises(InconsistentRecoveryPointError):
            await create_backup_set(
                session=session,
                user_id=USER,
                project_name=PROJECT,
                backup_set_id="bset-race",
                database_url=source_url,
                media_root=source_media,
                backup_dir=backup_dir,
                source_deployment_id="dev-local",
                release_git_sha="deadbeef",
                release_image_digest="sha256:image",
                configuration={},
                now=NOW,
            )


async def test_source_target_alias_is_refused_before_any_write(two_databases: tuple[str, str], tmp_path: Path) -> None:
    source_url, _target_url = two_databases
    media_root = tmp_path / "media"
    media_root.mkdir()
    source_factory = _session_factory(source_url)

    async with source_factory() as session:
        with pytest.raises(SourceTargetAliasError):
            await create_backup_set(
                session=session,
                user_id=USER,
                project_name=PROJECT,
                backup_set_id="bset-alias",
                database_url=source_url,
                media_root=media_root,
                backup_dir=media_root,  # deliberately aliases the live media root
                source_deployment_id="dev-local",
                release_git_sha="deadbeef",
                release_image_digest="sha256:image",
                configuration={},
                now=NOW,
            )


async def test_path_escaping_media_root_is_refused(two_databases: tuple[str, str], tmp_path: Path) -> None:
    source_url, _target_url = two_databases
    media_root = tmp_path / "media"
    media_root.mkdir()
    backup_dir = tmp_path / "backup"
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"escaped bytes")

    candidate = _candidate(
        "cand-escape", media_root=media_root, object_ref=str(outside), byte_size=len(b"escaped bytes")
    )
    source_factory = _session_factory(source_url)
    async with source_factory() as session:
        await CandidateObjectRepository(session).insert(
            user_id=USER, project_name=PROJECT, candidate=candidate, created_at=NOW
        )
        await session.commit()

    async with source_factory() as session:
        with pytest.raises(PathEscapesMediaRootError):
            await create_backup_set(
                session=session,
                user_id=USER,
                project_name=PROJECT,
                backup_set_id="bset-escape",
                database_url=source_url,
                media_root=media_root,
                backup_dir=backup_dir,
                source_deployment_id="dev-local",
                release_git_sha="deadbeef",
                release_image_digest="sha256:image",
                configuration={},
                now=NOW,
            )


async def test_restore_refuses_a_non_empty_target_database(two_databases: tuple[str, str], tmp_path: Path) -> None:
    source_url, target_url = two_databases
    source_media = tmp_path / "source-media"
    source_media.mkdir()
    backup_dir = tmp_path / "backup"
    target_media = tmp_path / "target-media"
    source_factory = _session_factory(source_url)
    await _seed_one_candidate(source_factory, source_media, "cand-1", b"bytes")

    async with source_factory() as session:
        manifest = await create_backup_set(
            session=session,
            user_id=USER,
            project_name=PROJECT,
            backup_set_id="bset-nonempty-db",
            database_url=source_url,
            media_root=source_media,
            backup_dir=backup_dir,
            source_deployment_id="dev-local",
            release_git_sha="deadbeef",
            release_image_digest="sha256:image",
            configuration={},
            now=NOW,
        )

    await _init_schema(target_url)  # target already has tables -- not empty
    target_factory = _session_factory(target_url)
    async with target_factory() as target_session:
        with pytest.raises(NonEmptyRestoreTargetError):
            await restore_backup_set(
                manifest=manifest,
                backup_dir=backup_dir,
                target_database_url=target_url,
                target_session=target_session,
                target_media_root=target_media,
            )


async def test_restore_refuses_a_non_empty_target_media_root(two_databases: tuple[str, str], tmp_path: Path) -> None:
    source_url, target_url = two_databases
    source_media = tmp_path / "source-media"
    source_media.mkdir()
    backup_dir = tmp_path / "backup"
    target_media = tmp_path / "target-media"
    target_media.mkdir()
    (target_media / "leftover.mp4").write_bytes(b"pre-existing")
    source_factory = _session_factory(source_url)
    await _seed_one_candidate(source_factory, source_media, "cand-1", b"bytes")

    async with source_factory() as session:
        manifest = await create_backup_set(
            session=session,
            user_id=USER,
            project_name=PROJECT,
            backup_set_id="bset-nonempty-media",
            database_url=source_url,
            media_root=source_media,
            backup_dir=backup_dir,
            source_deployment_id="dev-local",
            release_git_sha="deadbeef",
            release_image_digest="sha256:image",
            configuration={},
            now=NOW,
        )

    target_factory = _session_factory(target_url)
    async with target_factory() as target_session:
        with pytest.raises(NonEmptyRestoreTargetError):
            await restore_backup_set(
                manifest=manifest,
                backup_dir=backup_dir,
                target_database_url=target_url,
                target_session=target_session,
                target_media_root=target_media,
            )


async def test_verify_flags_a_changed_schema_head(two_databases: tuple[str, str], tmp_path: Path) -> None:
    source_url, target_url = two_databases
    source_media = tmp_path / "source-media"
    source_media.mkdir()
    backup_dir = tmp_path / "backup"
    target_media = tmp_path / "target-media"
    source_factory = _session_factory(source_url)
    await _seed_one_candidate(source_factory, source_media, "cand-1", b"bytes")

    async with source_factory() as session:
        real_manifest = await create_backup_set(
            session=session,
            user_id=USER,
            project_name=PROJECT,
            backup_set_id="bset-schema",
            database_url=source_url,
            media_root=source_media,
            backup_dir=backup_dir,
            source_deployment_id="dev-local",
            release_git_sha="deadbeef",
            release_image_digest="sha256:image",
            configuration={},
            now=NOW,
        )

    target_factory = _session_factory(target_url)
    async with target_factory() as target_session:
        await restore_backup_set(
            manifest=real_manifest,
            backup_dir=backup_dir,
            target_database_url=target_url,
            target_session=target_session,
            target_media_root=target_media,
        )

    stale_manifest = real_manifest.model_copy(update={"alembic_head": "some-other-head-entirely"})
    async with target_factory() as target_session:
        verdict = await verify_restored_backup_set(
            manifest=stale_manifest, session=target_session, media_root=target_media, now=NOW
        )

    assert not verdict.accepted
    assert any(code.startswith("SCHEMA_MISMATCH:") for code in verdict.reason_codes)


async def test_verify_flags_media_that_went_missing_or_corrupt_after_restore(
    two_databases: tuple[str, str], tmp_path: Path
) -> None:
    source_url, target_url = two_databases
    source_media = tmp_path / "source-media"
    source_media.mkdir()
    backup_dir = tmp_path / "backup"
    target_media = tmp_path / "target-media"
    source_factory = _session_factory(source_url)
    await _seed_one_candidate(source_factory, source_media, "cand-1", b"bytes-one")
    await _seed_one_candidate(source_factory, source_media, "cand-2", b"bytes-two")

    async with source_factory() as session:
        manifest = await create_backup_set(
            session=session,
            user_id=USER,
            project_name=PROJECT,
            backup_set_id="bset-post-restore-damage",
            database_url=source_url,
            media_root=source_media,
            backup_dir=backup_dir,
            source_deployment_id="dev-local",
            release_git_sha="deadbeef",
            release_image_digest="sha256:image",
            configuration={},
            now=NOW,
        )

    target_factory = _session_factory(target_url)
    async with target_factory() as target_session:
        await restore_backup_set(
            manifest=manifest,
            backup_dir=backup_dir,
            target_database_url=target_url,
            target_session=target_session,
            target_media_root=target_media,
        )

    # Simulate transit/restore-time damage: delete one restored file, truncate another.
    restored_paths = sorted(target_media.rglob("*.mp4"))
    assert len(restored_paths) == 2
    restored_paths[0].unlink()
    restored_paths[1].write_bytes(b"x")

    async with target_factory() as target_session:
        verdict = await verify_restored_backup_set(
            manifest=manifest, session=target_session, media_root=target_media, now=NOW
        )

    assert not verdict.accepted
    assert verdict.checked_media_count == 2
    assert any(code.startswith("MEDIA_MISSING:") for code in verdict.reason_codes)
    assert any(code.startswith(("MEDIA_SIZE_MISMATCH:", "MEDIA_DIGEST_MISMATCH:")) for code in verdict.reason_codes)


async def test_a_preparing_backup_set_blocks_candidate_deletion(two_databases: tuple[str, str], tmp_path: Path) -> None:
    source_url, _target_url = two_databases
    source_media = tmp_path / "source-media"
    source_media.mkdir()
    source_factory = _session_factory(source_url)
    candidate = await _seed_one_candidate(source_factory, source_media, "cand-protected", b"bytes")

    async with source_factory() as session:
        repo = BackupSetRepository(session)
        await repo.insert(user_id=USER, project_name=PROJECT, backup_set_id="bset-gc", state="PREPARING", now=NOW)
        await repo.add_media_ref(backup_set_id="bset-gc", candidate_id=candidate.candidate_id)
        await session.commit()

    async with source_factory() as session:
        policy = CandidateRetentionPolicy(
            master_head=MasterHeadReferenceCheckImpl(session),
            active_attempt=ActiveAttemptReferenceCheckImpl(),
            retained_receipt=PromotionReceiptRepository(session),
            incomplete_backup=BackupSetRepository(session),
        )
        deleted = await delete_candidate_if_permitted(
            policy=policy,
            user_id=USER,
            project_name=PROJECT,
            candidate_id=candidate.candidate_id,
            object_ref=Path(candidate.object_ref),
        )

    assert deleted is False
    assert Path(candidate.object_ref).exists()  # noqa: ASYNC240 -- single local-file existence check
