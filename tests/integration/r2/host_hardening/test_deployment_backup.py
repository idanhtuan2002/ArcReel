"""Whole-deployment backup under the offline fence (H6, ADR-0090), against real PostgreSQL.

Each test creates disposable source/target databases from ``DATABASE_URL``'s
server and disposable data roots under ``tmp_path``; no configured deployment
path or database is touched.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import pytest
from PIL import Image

from r2.contracts.host_hardening import BackupSetState
from r2.host_hardening.deployment_backup import (
    DATA_ROOT,
    BackupIntegrityError,
    OfflineFenceViolation,
    ReleaseIdentity,
    RestoreTargetNotEmpty,
    UnsupportedFileEntry,
    create_deployment_backup,
    libpq_url,
    read_state,
    restore_deployment_backup,
    verify_restored_deployment,
)

pytestmark = pytest.mark.uses_db

SECRET_CANARY = "sk-deployment-backup-canary-7e21"
IDENTITY = ReleaseIdentity(
    source_deployment_id="drill-source",
    release_git_sha="0" * 40,
    release_image_digest="sha256:" + "1" * 64,
    configuration={"profile": "drill"},
)


def _admin_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql+asyncpg://"):
        pytest.skip("requires DATABASE_URL pointing at a disposable PostgreSQL server")
    return url


def _with_database(url: str, database: str) -> str:
    return f"{url.rsplit('/', 1)[0]}/{database}"


async def _admin_execute(sql: str) -> None:
    conn = await asyncpg.connect(libpq_url(_admin_url()))
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


async def _create_database(name: str) -> str:
    await _admin_execute(f'CREATE DATABASE "{name}"')
    return _with_database(_admin_url(), name)


async def _drop_database(name: str) -> None:
    await _admin_execute(
        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{name}' AND pid <> pg_backend_pid()"
    )
    await _admin_execute(f'DROP DATABASE IF EXISTS "{name}"')


def _alembic_upgrade(url: str) -> None:
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


async def _seed_source(url: str, data_root: Path) -> None:
    await asyncio.to_thread(_alembic_upgrade, url)
    conn = await asyncpg.connect(libpq_url(url))
    try:
        now = datetime.now(UTC)
        await conn.execute(
            "INSERT INTO users (id, username, role, is_active, created_at, updated_at) "
            "VALUES ('u1', 'u1', 'user', true, $1, $1) ON CONFLICT (id) DO NOTHING",
            now,
        )
        await conn.execute(
            "INSERT INTO tasks (task_id, project_name, task_type, media_type, resource_id, status, source, "
            "queued_at, updated_at, user_id, request_id) VALUES "
            "('T-done', 'demo', 'image', 'image', 'Hero', 'succeeded', 'webui', $1, $1, 'u1', 'req-seed-0001')",
            now,
        )
        await conn.execute(
            "INSERT INTO provider_credential (provider, name, api_key, secret_key, is_active, created_at, updated_at) "
            "VALUES ('openai', 'main', $1, $1, true, $2, $2)",
            SECRET_CANARY,
            now,
        )
        provider_id = await conn.fetchval(
            "INSERT INTO custom_provider (display_name, discovery_format, base_url, api_key, created_at, updated_at) "
            "VALUES ('Custom', 'openai', 'https://custom.invalid/v1', $1, $2, $2) RETURNING id",
            SECRET_CANARY,
            now,
        )
        await conn.execute(
            "INSERT INTO custom_provider_model (provider_id, model_id, display_name, endpoint, is_default, "
            "is_enabled, created_at, updated_at) VALUES ($1, 'm1', 'Model 1', 'openai-images', true, true, $2, $2)",
            provider_id,
            now,
        )
        await conn.execute(
            "INSERT INTO provider_config (provider, key, value, is_secret, updated_at) VALUES "
            "('openai', 'api_key', $1, true, $2), ('openai', 'image_rpm', '12', false, $2)",
            SECRET_CANARY,
            now,
        )
        await conn.execute(
            "INSERT INTO system_setting (key, value, updated_at) VALUES "
            "('anthropic_api_key', $1, $2), ('video_generate_audio', 'true', $2)",
            SECRET_CANARY,
            now,
        )
        await conn.execute(
            "INSERT INTO agent_anthropic_credentials (user_id, preset_id, display_name, base_url, api_key, is_active, "
            "created_at, updated_at) VALUES ('u1', 'deepseek', 'DS', 'https://ds.invalid', $1, true, $2, $2)",
            SECRET_CANARY,
            now,
        )
        await conn.execute(
            "INSERT INTO assets (id, type, name, description, voice_style, image_path, created_at, updated_at) "
            "VALUES ('asset-1', 'character', 'Hero', '', '', '_global_assets/character/hero.png', $1, $1)",
            now,
        )
    finally:
        await conn.close()

    project = data_root / "demo"
    (project / "characters").mkdir(parents=True)
    (project / "versions" / "characters").mkdir(parents=True)
    Image.new("RGB", (8, 8), "red").save(project / "characters" / "Hero.png")
    Image.new("RGB", (8, 8), "red").save(project / "versions" / "characters" / "Hero_v1.png")
    (project / "project.json").write_text(json.dumps({"title": "Demo"}), encoding="utf-8")
    (project / "versions" / "versions.json").write_text(
        json.dumps(
            {
                "characters": {
                    "Hero": {
                        "current_version": 1,
                        "versions": [{"version": 1, "file": "versions/characters/Hero_v1.png", "task_id": "T-done"}],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (data_root / "_global_assets" / "character").mkdir(parents=True)
    Image.new("RGB", (8, 8), "blue").save(data_root / "_global_assets" / "character" / "hero.png")
    (data_root / ".system_config.json").write_text(json.dumps({"gemini_api_key": SECRET_CANARY}), encoding="utf-8")
    (data_root / "logs").mkdir()
    (data_root / "logs" / "app.log").write_text(f"leaked {SECRET_CANARY}", encoding="utf-8")


async def _always_playable(_path: Path) -> bool:
    return True


@pytest.fixture
async def source(tmp_path: Path) -> AsyncIterator[tuple[str, Path]]:
    name = f"h6_src_{uuid.uuid4().hex[:10]}"
    url = await _create_database(name)
    data_root = tmp_path / "source-data"
    data_root.mkdir()
    try:
        await _seed_source(url, data_root)
        yield url, data_root
    finally:
        await _drop_database(name)


@pytest.fixture
async def target_url() -> AsyncIterator[str]:
    name = f"h6_dst_{uuid.uuid4().hex[:10]}"
    url = await _create_database(name)
    try:
        yield url
    finally:
        await _drop_database(name)


def _bytes_under(root: Path) -> bytes:
    return b"".join(path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file())


async def test_round_trip_restores_a_verified_deployment_without_credentials(
    source: tuple[str, Path], target_url: str, tmp_path: Path
) -> None:
    source_url, data_root = source
    backup_dir = tmp_path / "backup-set"

    manifest = await create_deployment_backup(
        backup_set_id="bs-1",
        database_url=source_url,
        roots={DATA_ROOT: data_root},
        backup_dir=backup_dir,
        identity=IDENTITY,
    )

    assert read_state(backup_dir)["state"] == BackupSetState.COMPLETE.value
    captured = {entry.path for entry in manifest.files}
    assert "demo/project.json" in captured
    assert "_global_assets/character/hero.png" in captured
    assert ".system_config.json" not in captured
    assert not any(path.startswith("logs/") for path in captured)
    assert {t.table for t in manifest.sanitized_tables} >= {"provider_credential", "custom_provider"}
    assert SECRET_CANARY.encode() not in _bytes_under(backup_dir)

    target_root = tmp_path / "restored-data"
    started = datetime.now(UTC)
    await restore_deployment_backup(
        backup_dir=backup_dir, target_database_url=target_url, target_roots={DATA_ROOT: target_root}
    )
    verdict = await verify_restored_deployment(
        backup_dir=backup_dir,
        target_database_url=target_url,
        target_roots={DATA_ROOT: target_root},
        media_probe=_always_playable,
        measured_rto_seconds=int((datetime.now(UTC) - started).total_seconds()),
    )

    assert verdict.reason_codes == ()
    assert verdict.state is BackupSetState.VERIFIED
    assert read_state(backup_dir)["state"] == BackupSetState.VERIFIED.value
    assert verdict.probed_media_count == 1
    assert verdict.checked_reference_count >= 3
    conn = await asyncpg.connect(libpq_url(target_url))
    try:
        assert await conn.fetchval("SELECT request_id FROM tasks WHERE task_id = 'T-done'") == "req-seed-0001"
        assert await conn.fetchval("SELECT api_key FROM custom_provider") == ""
        assert await conn.fetchval("SELECT count(*) FROM custom_provider_model") == 1
        assert await conn.fetchval("SELECT value FROM provider_config WHERE key = 'image_rpm'") == "12"
        assert await conn.fetchval("SELECT value FROM system_setting WHERE key = 'video_generate_audio'") == "true"
        assert await conn.fetchval("SELECT api_key FROM provider_credential") is None
    finally:
        await conn.close()
    assert SECRET_CANARY.encode() not in _bytes_under(target_root)


async def test_capture_refuses_while_a_task_is_active(source: tuple[str, Path], tmp_path: Path) -> None:
    source_url, data_root = source
    conn = await asyncpg.connect(libpq_url(source_url))
    try:
        await conn.execute("UPDATE tasks SET status = 'queued' WHERE task_id = 'T-done'")
    finally:
        await conn.close()
    backup_dir = tmp_path / "backup-set"

    with pytest.raises(OfflineFenceViolation):
        await create_deployment_backup(
            backup_set_id="bs-active",
            database_url=source_url,
            roots={DATA_ROOT: data_root},
            backup_dir=backup_dir,
            identity=IDENTITY,
        )

    assert read_state(backup_dir) | {"reason": "OFFLINE_FENCE_VIOLATED"} == read_state(backup_dir)
    assert read_state(backup_dir)["state"] == BackupSetState.REJECTED.value


async def test_capture_refuses_while_another_client_is_connected(source: tuple[str, Path], tmp_path: Path) -> None:
    source_url, data_root = source
    app_session = await asyncpg.connect(libpq_url(source_url))
    try:
        with pytest.raises(OfflineFenceViolation):
            await create_deployment_backup(
                backup_set_id="bs-live",
                database_url=source_url,
                roots={DATA_ROOT: data_root},
                backup_dir=tmp_path / "backup-set",
                identity=IDENTITY,
            )
    finally:
        await app_session.close()


async def test_capture_refuses_links_and_special_files(source: tuple[str, Path], tmp_path: Path) -> None:
    source_url, data_root = source
    (data_root / "demo" / "escape").symlink_to(tmp_path)

    with pytest.raises(UnsupportedFileEntry):
        await create_deployment_backup(
            backup_set_id="bs-link",
            database_url=source_url,
            roots={DATA_ROOT: data_root},
            backup_dir=tmp_path / "backup-set",
            identity=IDENTITY,
        )


async def test_restore_refuses_an_altered_set_and_a_non_empty_target(
    source: tuple[str, Path], target_url: str, tmp_path: Path
) -> None:
    source_url, data_root = source
    backup_dir = tmp_path / "backup-set"
    manifest = await create_deployment_backup(
        backup_set_id="bs-2",
        database_url=source_url,
        roots={DATA_ROOT: data_root},
        backup_dir=backup_dir,
        identity=IDENTITY,
    )

    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "keep.txt").write_text("x", encoding="utf-8")
    with pytest.raises(RestoreTargetNotEmpty):
        await restore_deployment_backup(
            backup_dir=backup_dir, target_database_url=target_url, target_roots={DATA_ROOT: occupied}
        )

    captured = backup_dir / "files" / DATA_ROOT / manifest.files[0].path
    captured.write_bytes(captured.read_bytes() + b"tamper")
    with pytest.raises(BackupIntegrityError):
        await restore_deployment_backup(
            backup_dir=backup_dir, target_database_url=target_url, target_roots={DATA_ROOT: tmp_path / "fresh"}
        )


async def test_verification_rejects_a_restore_missing_a_selected_version(
    source: tuple[str, Path], target_url: str, tmp_path: Path
) -> None:
    source_url, data_root = source
    backup_dir = tmp_path / "backup-set"
    await create_deployment_backup(
        backup_set_id="bs-3",
        database_url=source_url,
        roots={DATA_ROOT: data_root},
        backup_dir=backup_dir,
        identity=IDENTITY,
    )
    target_root = tmp_path / "restored-data"
    await restore_deployment_backup(
        backup_dir=backup_dir, target_database_url=target_url, target_roots={DATA_ROOT: target_root}
    )
    (target_root / "demo" / "versions" / "characters" / "Hero_v1.png").unlink()

    verdict = await verify_restored_deployment(
        backup_dir=backup_dir,
        target_database_url=target_url,
        target_roots={DATA_ROOT: target_root},
        media_probe=_always_playable,
    )

    assert verdict.state is BackupSetState.REJECTED
    assert "FILE_MISSING:data:demo/versions/characters/Hero_v1.png" in verdict.reason_codes
    assert "VERSION_FILE_MISSING:demo:characters/Hero/v1" in verdict.reason_codes
    assert read_state(backup_dir)["state"] == BackupSetState.REJECTED.value
