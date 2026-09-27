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

from lib.artifact_manifest import ArtifactKey, ArtifactManifestEntry, ProjectArtifactManifestAdapter
from r2.contracts.host_hardening import BackupSetState, GoldenProductResult, GoldenRestoreEvidence
from r2.host_hardening.deployment_backup import (
    DATA_ROOT,
    AttestationRejected,
    BackupIntegrityError,
    BackupSetNotRestorable,
    OfflineFenceViolation,
    ReleaseIdentity,
    RestoreTargetNotEmpty,
    UnsafeBackupPath,
    UnsupportedFileEntry,
    attest_deployment_restore,
    create_deployment_backup,
    libpq_url,
    manifest_digest,
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
            "VALUES ('Custom', 'openai', 'https://proxyuser:proxy-pass-7e21@custom.invalid/v1', $1, $2, $2) "
            "RETURNING id",
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
            "('anthropic_api_key', $1, $2), ('video_generate_audio', 'true', $2), "
            "('anthropic_base_url', 'https://a:set-pass-1@one.invalid and https://b:set-pass-2@two.invalid "
            "contact admin@example.invalid https://q.invalid/p?x=a@b', $2)",
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
    (data_root / "demo2").mkdir()
    (data_root / "demo2" / "project.json").write_text(json.dumps({"title": "Demo 2"}), encoding="utf-8")
    (project / "scripts").mkdir()
    (project / "scripts" / "episode_1.json").write_text("{}", encoding="utf-8")
    ProjectArtifactManifestAdapter(project).put_entry(
        ArtifactKey.episode_script(1),
        ArtifactManifestEntry(artifact_path="scripts/episode_1.json", basis_digest="sha256-v1:" + "a" * 64),
    )
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


RESTORE_TARGET = "drill-target-1"


def _golden(
    backup_dir: Path,
    *,
    names: tuple[str, ...] = ("demo", "demo2"),
    passed: bool = True,
    target: str = RESTORE_TARGET,
) -> GoldenRestoreEvidence:
    from r2.host_hardening.deployment_backup import read_manifest

    manifest = read_manifest(backup_dir)
    return GoldenRestoreEvidence(
        backup_set_id=manifest.backup_set_id,
        manifest_digest=manifest_digest(manifest),
        restore_target_id=target,
        passed=passed,
        products=tuple(
            GoldenProductResult(project_name=name, reviewed=True, export_digest="sha256:" + "e" * 64) for name in names
        ),
    )


async def _backup_restore_verify(
    source: tuple[str, Path], target_url: str, tmp_path: Path, *, backup_set_id: str
) -> tuple[Path, Path]:
    source_url, data_root = source
    backup_dir = tmp_path / "backup-set"
    await create_deployment_backup(
        backup_set_id=backup_set_id,
        database_url=source_url,
        roots={DATA_ROOT: data_root},
        backup_dir=backup_dir,
        identity=IDENTITY,
    )
    target_root = tmp_path / "restored-data"
    await restore_deployment_backup(
        backup_dir=backup_dir, target_database_url=target_url, target_roots={DATA_ROOT: target_root}
    )
    return backup_dir, target_root


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


async def _drop_and_recreate(url: str) -> None:
    name = url.rsplit("/", 1)[1]
    await _drop_database(name)
    await _admin_execute(f'CREATE DATABASE "{name}"')


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
    assert b"proxy-pass-7e21" not in _bytes_under(backup_dir)
    assert b"set-pass-1" not in _bytes_under(backup_dir)
    assert b"set-pass-2" not in _bytes_under(backup_dir)

    target_root = tmp_path / "restored-data"
    started = datetime.now(UTC)
    await restore_deployment_backup(
        backup_dir=backup_dir, target_database_url=target_url, target_roots={DATA_ROOT: target_root}
    )
    verdict = await verify_restored_deployment(
        backup_dir=backup_dir,
        target_database_url=target_url,
        target_roots={DATA_ROOT: target_root},
        restore_target_id=RESTORE_TARGET,
        target_release_git_sha=IDENTITY.release_git_sha,
        media_probe=_always_playable,
    )

    assert verdict.reason_codes == ()
    assert verdict.checks_passed
    assert read_state(backup_dir)["state"] == BackupSetState.COMPLETE.value
    assert verdict.probed_media_count == 1
    assert verdict.checked_reference_count >= 4
    assert manifest.configuration == {"profile": "drill"}

    attestation = attest_deployment_restore(
        backup_dir=backup_dir,
        golden_evidence=_golden(backup_dir),
        measured_rpo_seconds=0,
        measured_rto_seconds=int((datetime.now(UTC) - started).total_seconds()),
    )
    assert attestation.backup_set_id == "bs-1"
    assert read_state(backup_dir)["state"] == BackupSetState.VERIFIED.value
    conn = await asyncpg.connect(libpq_url(target_url))
    try:
        assert await conn.fetchval("SELECT request_id FROM tasks WHERE task_id = 'T-done'") == "req-seed-0001"
        assert await conn.fetchval("SELECT api_key FROM custom_provider") == ""
        assert await conn.fetchval("SELECT base_url FROM custom_provider") == "https://custom.invalid/v1"
        assert await conn.fetchval("SELECT count(*) FROM custom_provider_model") == 1
        assert await conn.fetchval("SELECT value FROM provider_config WHERE key = 'image_rpm'") == "12"
        assert await conn.fetchval("SELECT value FROM system_setting WHERE key = 'video_generate_audio'") == "true"
        assert await conn.fetchval("SELECT value FROM system_setting WHERE key = 'anthropic_base_url'") == (
            "https://one.invalid and https://two.invalid contact admin@example.invalid https://q.invalid/p?x=a@b"
        )
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


async def test_failed_verification_does_not_poison_the_set(
    source: tuple[str, Path], target_url: str, tmp_path: Path
) -> None:
    backup_dir, target_root = await _backup_restore_verify(source, target_url, tmp_path, backup_set_id="bs-3")
    (target_root / "demo" / "versions" / "characters" / "Hero_v1.png").unlink()

    verdict = await verify_restored_deployment(
        backup_dir=backup_dir,
        target_database_url=target_url,
        target_roots={DATA_ROOT: target_root},
        restore_target_id=RESTORE_TARGET,
        target_release_git_sha="f" * 40,
        media_probe=_always_playable,
    )

    assert not verdict.checks_passed
    assert "FILE_MISSING:data:demo/versions/characters/Hero_v1.png" in verdict.reason_codes
    assert "VERSION_FILE_MISSING:demo:characters/Hero/v1" in verdict.reason_codes
    assert "RELEASE_MISMATCH" in verdict.reason_codes
    assert read_state(backup_dir)["state"] == BackupSetState.COMPLETE.value
    with pytest.raises(AttestationRejected):
        attest_deployment_restore(
            backup_dir=backup_dir, golden_evidence=_golden(backup_dir), measured_rpo_seconds=0, measured_rto_seconds=1
        )
    assert read_state(backup_dir)["state"] == BackupSetState.COMPLETE.value
    # The set stays restorable into another clean target.
    await _drop_and_recreate(target_url)
    await restore_deployment_backup(
        backup_dir=backup_dir, target_database_url=target_url, target_roots={DATA_ROOT: tmp_path / "second-target"}
    )


async def test_verification_resolves_selected_versions_and_artifact_manifests(
    source: tuple[str, Path], target_url: str, tmp_path: Path
) -> None:
    backup_dir, target_root = await _backup_restore_verify(source, target_url, tmp_path, backup_set_id="bs-4")
    versions_file = target_root / "demo" / "versions" / "versions.json"
    history = json.loads(versions_file.read_text(encoding="utf-8"))
    history["characters"]["Hero"]["current_version"] = 7
    versions_file.write_text(json.dumps(history), encoding="utf-8")
    (target_root / "demo" / "scripts" / "episode_1.json").unlink()

    verdict = await verify_restored_deployment(
        backup_dir=backup_dir,
        target_database_url=target_url,
        target_roots={DATA_ROOT: target_root},
        restore_target_id=RESTORE_TARGET,
        target_release_git_sha=IDENTITY.release_git_sha,
        media_probe=_always_playable,
    )

    assert "CURRENT_VERSION_MISSING:demo:characters/Hero/v7" in verdict.reason_codes
    assert "ARTIFACT_FILE_MISSING:demo:scripts/episode_1.json" in verdict.reason_codes


async def test_attestation_requires_matching_passing_golden_evidence(
    source: tuple[str, Path], target_url: str, tmp_path: Path
) -> None:
    backup_dir, target_root = await _backup_restore_verify(source, target_url, tmp_path, backup_set_id="bs-5")
    with pytest.raises(AttestationRejected):
        attest_deployment_restore(
            backup_dir=backup_dir, golden_evidence=_golden(backup_dir), measured_rpo_seconds=0, measured_rto_seconds=1
        )
    await verify_restored_deployment(
        backup_dir=backup_dir,
        target_database_url=target_url,
        target_roots={DATA_ROOT: target_root},
        restore_target_id=RESTORE_TARGET,
        target_release_git_sha=IDENTITY.release_git_sha,
        media_probe=_always_playable,
    )

    for evidence in (
        _golden(backup_dir, names=("demo",)),
        _golden(backup_dir, names=("demo", "demo")),
        _golden(backup_dir, names=("demo", "not-a-project")),
        _golden(backup_dir, target="some-other-target"),
        _golden(backup_dir, passed=False),
        _golden(backup_dir).model_copy(update={"manifest_digest": "sha256:" + "0" * 64}),
    ):
        with pytest.raises(AttestationRejected):
            attest_deployment_restore(
                backup_dir=backup_dir, golden_evidence=evidence, measured_rpo_seconds=0, measured_rto_seconds=1
            )
        assert read_state(backup_dir)["state"] == BackupSetState.COMPLETE.value


def _tool_wrapper(tmp_path: Path, name: str, before_real_tool: str) -> str:
    """A pg_dump stand-in that records its argv and environment, runs a shell step, then the real tool."""
    wrapper = tmp_path / f"{name}.sh"
    wrapper.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" > "{tmp_path}/{name}.argv"\n'
        f'printf "%s" "${{PGPASSWORD:-}}" > "{tmp_path}/{name}.pgpassword"\n'
        f"{before_real_tool}\n"
        'exec pg_dump "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    return str(wrapper)


def _url_password(url: str) -> str:
    from urllib.parse import unquote, urlsplit

    return unquote(urlsplit(libpq_url(url)).password or "")


async def test_database_password_never_reaches_tool_argv(source: tuple[str, Path], tmp_path: Path) -> None:
    source_url, data_root = source
    password = _url_password(source_url)
    if not password:
        pytest.skip("DATABASE_URL carries no password")

    await create_deployment_backup(
        backup_set_id="bs-argv",
        database_url=source_url,
        roots={DATA_ROOT: data_root},
        backup_dir=tmp_path / "backup-set",
        identity=IDENTITY,
        pg_dump_path=_tool_wrapper(tmp_path, "dump", ":"),
    )

    assert password not in (tmp_path / "dump.argv").read_text(encoding="utf-8")
    assert (tmp_path / "dump.pgpassword").read_text(encoding="utf-8") == password


@pytest.mark.parametrize(
    ("change", "detail"),
    [
        ("sequence", "a sequence advanced"),
        ("row", "the database was written"),
        ("file", "data-root files changed"),
        ("truncate", "truncated, rewritten or altered"),
        ("alter", "truncated, rewritten or altered"),
    ],
)
async def test_capture_detects_changes_made_while_capturing(
    source: tuple[str, Path], tmp_path: Path, change: str, detail: str
) -> None:
    source_url, data_root = source
    target, env = __import__("r2.host_hardening.deployment_backup", fromlist=["x"]).libpq_command_target(source_url)
    password = env.get("PGPASSWORD", "")
    steps = {
        "sequence": f"PGPASSWORD='{password}' psql -q '{target}' -c \"SELECT nextval('api_calls_id_seq')\" >/dev/null",
        "row": (
            f"PGPASSWORD='{password}' psql -q '{target}' -c \"UPDATE system_setting SET value = 'false' "
            "WHERE key = 'video_generate_audio'\" >/dev/null"
        ),
        "file": f"echo changed > '{data_root}/demo/project.json'",
        "truncate": f"PGPASSWORD='{password}' psql -q '{target}' -c 'TRUNCATE api_keys' >/dev/null",
        "alter": f"PGPASSWORD='{password}' psql -q '{target}' -c 'ALTER TABLE api_keys ADD COLUMN probe int' >/dev/null",
    }
    backup_dir = tmp_path / "backup-set"

    with pytest.raises(OfflineFenceViolation, match=detail):
        await create_deployment_backup(
            backup_set_id=f"bs-{change}",
            database_url=source_url,
            roots={DATA_ROOT: data_root},
            backup_dir=backup_dir,
            identity=IDENTITY,
            pg_dump_path=_tool_wrapper(tmp_path, "dump", steps[change]),
        )

    assert read_state(backup_dir)["state"] == BackupSetState.REJECTED.value


async def test_credential_files_are_never_captured_in_any_root(source: tuple[str, Path], tmp_path: Path) -> None:
    source_url, data_root = source
    agent_root = tmp_path / "claude-data"
    agent_root.mkdir()
    (agent_root / ".credentials.json").write_text(json.dumps({"token": SECRET_CANARY}), encoding="utf-8")
    (agent_root / "projects").mkdir()
    (agent_root / "projects" / "session.jsonl").write_text("{}", encoding="utf-8")
    (data_root / "demo" / ".credentials.json").write_text(SECRET_CANARY, encoding="utf-8")

    manifest = await create_deployment_backup(
        backup_set_id="bs-creds",
        database_url=source_url,
        roots={DATA_ROOT: data_root, "claude_data": agent_root},
        backup_dir=tmp_path / "backup-set",
        identity=IDENTITY,
    )

    captured = {(entry.root, entry.path) for entry in manifest.files}
    assert ("claude_data", "projects/session.jsonl") in captured
    assert not any(path.endswith(".credentials.json") for _, path in captured)
    assert SECRET_CANARY.encode() not in _bytes_under(tmp_path / "backup-set")


async def test_a_verified_state_without_its_attestation_is_not_restorable(
    source: tuple[str, Path], target_url: str, tmp_path: Path
) -> None:
    backup_dir, _ = await _backup_restore_verify(source, target_url, tmp_path, backup_set_id="bs-6")
    state = json.loads((backup_dir / "state.json").read_text(encoding="utf-8"))
    state["state"] = BackupSetState.VERIFIED.value
    (backup_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(BackupIntegrityError):
        await restore_deployment_backup(
            backup_dir=backup_dir, target_database_url=target_url, target_roots={DATA_ROOT: tmp_path / "again"}
        )


async def test_verification_flags_a_current_record_without_a_file_and_projects_without_metadata(
    source: tuple[str, Path], target_url: str, tmp_path: Path
) -> None:
    backup_dir, target_root = await _backup_restore_verify(source, target_url, tmp_path, backup_set_id="bs-7")
    versions_file = target_root / "demo" / "versions" / "versions.json"
    history = json.loads(versions_file.read_text(encoding="utf-8"))
    del history["characters"]["Hero"]["versions"][0]["file"]
    versions_file.write_text(json.dumps(history), encoding="utf-8")
    (target_root / "demo" / "project.json").unlink()

    verdict = await verify_restored_deployment(
        backup_dir=backup_dir,
        target_database_url=target_url,
        target_roots={DATA_ROOT: target_root},
        restore_target_id=RESTORE_TARGET,
        target_release_git_sha=IDENTITY.release_git_sha,
        media_probe=_always_playable,
    )

    assert "CURRENT_VERSION_FILE_MISSING:demo:characters/Hero/v1" in verdict.reason_codes


async def test_an_unreachable_database_rejects_the_set(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    backup_dir = tmp_path / "backup-set"

    with pytest.raises(ConnectionRefusedError):
        await create_deployment_backup(
            backup_set_id="bs-down",
            database_url="postgresql://nobody:x@127.0.0.1:9/none",
            roots={DATA_ROOT: data_root},
            backup_dir=backup_dir,
            identity=IDENTITY,
        )

    assert read_state(backup_dir) | {"reason": "DATABASE_UNAVAILABLE"} == read_state(backup_dir)
    assert read_state(backup_dir)["state"] == BackupSetState.REJECTED.value


async def test_an_attested_target_cannot_be_reverified_and_attested_files_are_tamper_checked(
    source: tuple[str, Path], target_url: str, tmp_path: Path
) -> None:
    backup_dir, target_root = await _backup_restore_verify(source, target_url, tmp_path, backup_set_id="bs-8")

    async def _verify(target_id: str) -> None:
        await verify_restored_deployment(
            backup_dir=backup_dir,
            target_database_url=target_url,
            target_roots={DATA_ROOT: target_root},
            restore_target_id=target_id,
            target_release_git_sha=IDENTITY.release_git_sha,
            media_probe=_always_playable,
        )

    await _verify(RESTORE_TARGET)
    attest_deployment_restore(
        backup_dir=backup_dir, golden_evidence=_golden(backup_dir), measured_rpo_seconds=0, measured_rto_seconds=1
    )
    assert read_state(backup_dir)["state"] == BackupSetState.VERIFIED.value

    with pytest.raises(UnsafeBackupPath):
        await _verify(RESTORE_TARGET)
    with pytest.raises(UnsafeBackupPath):
        await _verify(RESTORE_TARGET.upper())
    with pytest.raises(AttestationRejected):
        attest_deployment_restore(
            backup_dir=backup_dir, golden_evidence=_golden(backup_dir), measured_rpo_seconds=0, measured_rto_seconds=1
        )
    await _verify("drill-target-2")
    assert (backup_dir / "verdicts" / "drill-target-2.json").is_file()

    verdict_file = backup_dir / "verdicts" / f"{RESTORE_TARGET}.json"
    original = verdict_file.read_text(encoding="utf-8")
    verdict = json.loads(original)
    verdict["checked_file_count"] += 1
    for tampered in (json.dumps(verdict), "{not json"):
        verdict_file.write_text(tampered, encoding="utf-8")
        with pytest.raises(BackupIntegrityError):
            await restore_deployment_backup(
                backup_dir=backup_dir, target_database_url=target_url, target_roots={DATA_ROOT: tmp_path / "again"}
            )


async def test_attesting_with_a_corrupt_verdict_is_rejected(
    source: tuple[str, Path], target_url: str, tmp_path: Path
) -> None:
    backup_dir, target_root = await _backup_restore_verify(source, target_url, tmp_path, backup_set_id="bs-9")
    await verify_restored_deployment(
        backup_dir=backup_dir,
        target_database_url=target_url,
        target_roots={DATA_ROOT: target_root},
        restore_target_id=RESTORE_TARGET,
        target_release_git_sha=IDENTITY.release_git_sha,
        media_probe=_always_playable,
    )
    verdict_file = backup_dir / "verdicts" / f"{RESTORE_TARGET}.json"
    verdict_file.write_text("{not json", encoding="utf-8")

    with pytest.raises(AttestationRejected):
        attest_deployment_restore(
            backup_dir=backup_dir, golden_evidence=_golden(backup_dir), measured_rpo_seconds=0, measured_rto_seconds=1
        )
    verdict_file.write_bytes(b"\xff\xfe not utf-8")
    with pytest.raises(AttestationRejected):
        attest_deployment_restore(
            backup_dir=backup_dir, golden_evidence=_golden(backup_dir), measured_rpo_seconds=0, measured_rto_seconds=1
        )
    assert read_state(backup_dir)["state"] == BackupSetState.COMPLETE.value


async def test_autovacuum_style_maintenance_during_capture_is_not_a_write(
    source: tuple[str, Path], tmp_path: Path
) -> None:
    source_url, data_root = source
    target, env = __import__("r2.host_hardening.deployment_backup", fromlist=["x"]).libpq_command_target(source_url)
    password = env.get("PGPASSWORD", "")
    maintenance = f"PGPASSWORD='{password}' psql -q '{target}' -c 'ANALYZE' -c 'VACUUM tasks' >/dev/null"

    manifest = await create_deployment_backup(
        backup_set_id="bs-analyze",
        database_url=source_url,
        roots={DATA_ROOT: data_root},
        backup_dir=tmp_path / "backup-set",
        identity=IDENTITY,
        pg_dump_path=_tool_wrapper(tmp_path, "dump", maintenance),
    )

    assert manifest.fence.write_counter_before == manifest.fence.write_counter_after
    assert read_state(tmp_path / "backup-set")["state"] == BackupSetState.COMPLETE.value


async def test_a_manifest_of_an_older_schema_version_is_not_restorable(
    source: tuple[str, Path], target_url: str, tmp_path: Path
) -> None:
    backup_dir, _ = await _backup_restore_verify(source, target_url, tmp_path, backup_set_id="bs-10")
    manifest_file = backup_dir / "manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest["schema_version"] = 1
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BackupSetNotRestorable):
        await restore_deployment_backup(
            backup_dir=backup_dir, target_database_url=target_url, target_roots={DATA_ROOT: tmp_path / "again"}
        )


async def test_an_unreadable_state_ledger_is_reported_as_an_integrity_error(
    source: tuple[str, Path], target_url: str, tmp_path: Path
) -> None:
    backup_dir, _ = await _backup_restore_verify(source, target_url, tmp_path, backup_set_id="bs-11")
    for corrupt in (b"\xff\xfe", b"{not json", b"[1, 2]"):
        (backup_dir / "state.json").write_bytes(corrupt)
        with pytest.raises(BackupIntegrityError):
            read_state(backup_dir)
