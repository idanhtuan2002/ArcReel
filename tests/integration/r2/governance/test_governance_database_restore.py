"""A real same-major dump/restore cannot revive ISSUE against retained REVOKE custody."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import uuid
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from lib.content_digest import canonical_json_bytes
from lib.db.models.governance_grant import ShowrunnerGrantEventModel, ShowrunnerGrantHeadModel
from r2.governance.grant_transition import GrantScopeV1
from r2.governance.operator_archive_reader import OperatorArchiveReader
from r2.host_hardening.deployment_backup import libpq_command_target
from server.services.governance_attestation import serve_governance_attestor
from server.services.governance_grants import GovernanceGrantImporter, ShowrunnerGrantUnavailableError
from server.services.governance_operator_archive import publish_candidate_archive
from server.services.governance_startup import GovernanceStartupUnavailable, verify_governance_public_startup
from tests.integration.r2.governance.test_activated_governance_startup import _configure_lifespan
from tests.integration.r2.governance.test_grant_importer import _event, _signed
from tests.integration.r2.host_hardening.test_deployment_backup import (
    _alembic_upgrade,
    _create_database,
    _drop_database,
)
from tests.unit.r2.governance.test_operator_archive_reader import _digest, _encoded, _put, _tree

pytestmark = pytest.mark.uses_db


async def _publish_head(root: Path, factory, sequence: int, event_digest: str) -> None:
    prior = OperatorArchiveReader(root, expected_uid=os.getuid()).read()
    old_body = json.loads(prior.checkpoint_raw)["body"]
    body = old_body | {
        "checkpoint_sequence": prior.snapshot.high_water.checkpoint_sequence + 1,
        "previous_checkpoint_digest": prior.snapshot.checkpoint.checkpoint_digest,
        "issued_at": f"2026-10-13T00:00:0{sequence}Z",
        "heads": [
            {
                "user_id": "u1",
                "project_name": "show-a",
                "principal": "reviewer-a",
                "head_sequence": sequence,
                "head_event_digest": event_digest,
            }
        ],
    }
    checkpoint_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    body_raw = canonical_json_bytes(body, allow_nan=False)
    checkpoint_raw = canonical_json_bytes(
        {"body": body, "signature": _encoded(checkpoint_key.sign(body_raw))}, allow_nan=False
    )
    high_water = json.loads(prior.high_water_raw) | {
        "checkpoint_sequence": body["checkpoint_sequence"],
        "checkpoint_body_digest": _digest(body_raw),
        "checkpoint_file_digest": _digest(checkpoint_raw),
        "previous_checkpoint_body_digest": body["previous_checkpoint_digest"],
        "previous_high_water_digest": _digest(prior.high_water_raw),
        "checkpoint_issued_at": body["issued_at"],
        "recorded_at": f"2026-10-13T00:00:1{sequence}Z",
    }
    await publish_candidate_archive(
        root,
        canonical_json_bytes(high_water, allow_nan=False),
        checkpoint_raw,
        session_factory=factory,
        expected_uid=os.getuid(),
    )


async def _tool(program: str, url: str, *args: str) -> None:
    target, extra_env = libpq_command_target(url)
    process = await asyncio.create_subprocess_exec(
        program,
        "--no-password",
        "--dbname",
        target,
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, **extra_env},
    )
    _out, error = await process.communicate()
    assert process.returncode == 0, f"{program} failed: {error.decode(errors='replace')[-1000:]}"


async def _state(factory: async_sessionmaker[AsyncSession]) -> tuple:
    async with factory() as session:
        version = tuple((await session.execute(text("SELECT version_num FROM alembic_version"))).all())
        heads = tuple(
            (
                await session.execute(
                    select(ShowrunnerGrantHeadModel.__table__).order_by(
                        ShowrunnerGrantHeadModel.user_id,
                        ShowrunnerGrantHeadModel.project_name,
                        ShowrunnerGrantHeadModel.principal,
                    )
                )
            ).all()
        )
        events = tuple(
            (
                await session.execute(
                    select(ShowrunnerGrantEventModel.__table__).order_by(
                        ShowrunnerGrantEventModel.user_id,
                        ShowrunnerGrantEventModel.project_name,
                        ShowrunnerGrantEventModel.principal,
                        ShowrunnerGrantEventModel.sequence,
                    )
                )
            ).all()
        )
        return version, heads, events


@pytest.mark.asyncio
async def test_pg_dump_restore_denies_old_db_and_coherent_public_before_actual_lifespan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import server.app as app_module

    source_name = "m8c_source_" + uuid.uuid4().hex
    target_name = "m8c_restore_" + uuid.uuid4().hex
    source_url = await _create_database(source_name)
    source_engine = create_async_engine(source_url)
    target_engine = None
    try:
        await asyncio.to_thread(_alembic_upgrade, source_url)
        async with source_engine.begin() as connection:
            major = int((await connection.execute(text("SHOW server_version_num"))).scalar_one()) // 10000
            for program in ("pg_dump", "pg_restore"):
                if shutil.which(program) is None:
                    pytest.skip(f"{program} is required for the real restore drill")
                probe = await asyncio.create_subprocess_exec(program, "--version", stdout=asyncio.subprocess.PIPE)
                output, _error = await probe.communicate()
                match = re.search(rb"PostgreSQL\) (\d+)\.", output)
                if match is None or int(match[1]) != major:
                    pytest.skip("real restore drill requires matching PostgreSQL client/server major versions")
            await connection.execute(
                text(
                    "INSERT INTO users (id, username, role, is_active, created_at, updated_at) "
                    "VALUES ('u1', 'u1', 'user', true, now(), now())"
                )
            )
        source = async_sessionmaker(source_engine, expire_on_commit=False)
        root, paths = _tree(tmp_path)
        scope = GrantScopeV1("u1", "show-a", "reviewer-a")
        key = Ed25519PrivateKey.from_private_bytes(bytes(range(32, 64)))
        public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        importer = GovernanceGrantImporter(source, key_id="grant-key-a", public_key=public)
        body = _event("ISSUE", 1, None, "2026-01-01T00:00:00Z") | {"signer_key_id": "grant-key-a"}
        issue = await importer.import_event(_signed(body, key), scope=scope)
        await _publish_head(root, source, 1, issue.event_digest)
        old_public = (paths["public_high_water"].read_bytes(), paths["public_checkpoint"].read_bytes())
        before_revoke = await _state(source)
        dump = tmp_path / "pre-revoke.dump"
        await _tool("pg_dump", source_url, "-Fc", "--file", str(dump))
        body = _event("REVOKE", 2, issue.event_digest, "2026-02-01T00:00:00Z") | {"signer_key_id": "grant-key-a"}
        revoke = await importer.import_event(_signed(body, key), scope=scope)
        await _publish_head(root, source, 2, revoke.event_digest)
        latest = OperatorArchiveReader(root, expected_uid=os.getuid()).read()
        current = await _state(source)
        target_url = await _create_database(target_name)
        await _tool("pg_restore", target_url, "--exit-on-error", "--no-owner", "--no-privileges", str(dump))
        target_engine = create_async_engine(target_url)
        restored = async_sessionmaker(target_engine, expire_on_commit=False)
        assert await _state(restored) == before_revoke
        runtime = tmp_path / "run"
        runtime.mkdir(mode=0o700)
        projects = tmp_path / "projects"
        projects.mkdir()
        async with serve_governance_attestor(
            root, runtime, session_factory=source, expected_uid=os.getuid(), expected_gid=os.getgid()
        ):
            for coherent_old_public in (False, True):
                if coherent_old_public:
                    _put(paths["public_high_water"], old_public[0], 0o644)
                    _put(paths["public_checkpoint"], old_public[1], 0o644)
                    await verify_governance_public_startup(
                        root / "read", session_factory=restored, expected_uid=os.getuid(), expected_gid=os.getgid()
                    )
                _configure_lifespan(restored, root, runtime, projects, monkeypatch)
                with pytest.raises(GovernanceStartupUnavailable):
                    async with app_module.lifespan(app_module.app):
                        raise AssertionError("restored grant reached readiness")
                assert not hasattr(app_module.app.state, "generation_worker")
                assert await _state(restored) == before_revoke
            _put(paths["public_high_water"], latest.high_water_raw, 0o644)
            _put(paths["public_checkpoint"], latest.checkpoint_raw, 0o644)
            _configure_lifespan(source, root, runtime, projects, monkeypatch)
            async with app_module.lifespan(app_module.app):
                assert app_module.app.state.generation_worker is not None
                async with source() as session, session.begin():
                    with pytest.raises(ShowrunnerGrantUnavailableError):
                        await app_module.app.state.governance_grants.require_current_locked(session, scope=scope)
            assert not any(task.get_name() == "generation-worker" and not task.done() for task in asyncio.all_tasks())
            assert await _state(source) == current
    finally:
        if target_engine is not None:
            await target_engine.dispose()
        await source_engine.dispose()
        await _drop_database(target_name)
        await _drop_database(source_name)
