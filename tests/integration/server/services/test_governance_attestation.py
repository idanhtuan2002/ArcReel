"""Real Unix channels bind a startup challenge to independent archive preflight."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.services.governance_attestation import (
    GovernanceAttestationUnavailable,
    require_governance_archive_freshness,
    serve_governance_attestor,
)
from tests.integration.r2.governance.test_operator_archive_reconcile import _ready_schema
from tests.unit.r2.governance.test_operator_archive_reader import _append_successor, _put, _tree


def _copies(paths: dict[str, Path]) -> tuple[bytes, bytes, bytes, bytes]:
    return (
        paths["public_approved"].read_bytes(),
        paths["public_registry"].read_bytes(),
        paths["public_high_water"].read_bytes(),
        paths["public_checkpoint"].read_bytes(),
    )


@pytest.mark.asyncio
async def test_pg_real_socket_attests_current_archive_and_reopens_each_start(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    engine = session_factory.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("attestor requires PostgreSQL")
    await _ready_schema(engine)
    root, paths = _tree(tmp_path)
    runtime = tmp_path / "run"
    runtime.mkdir(mode=0o700)
    async with serve_governance_attestor(
        root, runtime, session_factory=session_factory, expected_uid=os.getuid(), expected_gid=os.getgid()
    ):
        await require_governance_archive_freshness(
            runtime, _copies(paths), expected_uid=os.getuid(), expected_gid=os.getgid()
        )
        old = _copies(paths)
        _append_successor(root, paths)
        with pytest.raises(GovernanceAttestationUnavailable):
            await require_governance_archive_freshness(runtime, old, expected_uid=os.getuid(), expected_gid=os.getgid())
        await require_governance_archive_freshness(
            runtime, _copies(paths), expected_uid=os.getuid(), expected_gid=os.getgid()
        )
    assert not (runtime / "attestor.sock").exists()


@pytest.mark.asyncio
async def test_pg_real_socket_denies_coherent_old_public_against_retained_successor(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    engine = session_factory.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("attestor requires PostgreSQL")
    await _ready_schema(engine)
    root, paths = _tree(tmp_path)
    old = _copies(paths)
    _append_successor(root, paths)
    _put(paths["public_high_water"], old[2], 0o644)
    _put(paths["public_checkpoint"], old[3], 0o644)
    runtime = tmp_path / "run"
    runtime.mkdir(mode=0o700)
    async with serve_governance_attestor(
        root, runtime, session_factory=session_factory, expected_uid=os.getuid(), expected_gid=os.getgid()
    ):
        with pytest.raises(GovernanceAttestationUnavailable):
            await require_governance_archive_freshness(runtime, old, expected_uid=os.getuid(), expected_gid=os.getgid())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault", ["none", "old_nonce", "extra_field", "trailing", "oversized", "bad_mode", "wrong_owner"]
)
async def test_real_socket_denies_untrusted_response(tmp_path: Path, fault: str) -> None:
    runtime = tmp_path / "run"
    runtime.mkdir(mode=0o700)
    path = runtime / "attestor.sock"
    _root, paths = _tree(tmp_path)
    copies = _copies(paths)

    async def malicious(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = json.loads(await reader.readline())
            response = {
                "schema": "governance.startup_proof.v1",
                "nonce": request["nonce"],
                "deployment_id": "deploy-a",
                "checkpoint_sequence": 1,
                "public_digests": ["sha256:" + hashlib.sha256(raw).hexdigest() for raw in copies],
            }
            if fault == "old_nonce":
                response["nonce"] = "0" * 64
            elif fault == "extra_field":
                response["unexpected"] = "x"
            payload = json.dumps(response, sort_keys=True, separators=(",", ":")).encode() + b"\n"
            if fault == "trailing":
                payload += b"extra"
            elif fault == "oversized":
                payload = b"x" * 5000 + b"\n"
            writer.write(payload)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_unix_server(malicious, path=path)
    os.chmod(path, 0o666 if fault == "bad_mode" else 0o600)
    try:
        if fault == "none":
            await require_governance_archive_freshness(
                runtime, copies, expected_uid=os.getuid(), expected_gid=os.getgid()
            )
        else:
            with pytest.raises(GovernanceAttestationUnavailable):
                await require_governance_archive_freshness(
                    runtime, copies, expected_uid=os.getuid() + (fault == "wrong_owner"), expected_gid=os.getgid()
                )
    finally:
        server.close()
        await server.wait_closed()
        path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_attestor_refuses_existing_path_without_unlinking(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    root, _paths = _tree(tmp_path)
    runtime = tmp_path / "run"
    runtime.mkdir(mode=0o700)
    existing = runtime / "attestor.sock"
    existing.write_bytes(b"operator-owned")
    with pytest.raises(GovernanceAttestationUnavailable):
        async with serve_governance_attestor(
            root, runtime, session_factory=session_factory, expected_uid=os.getuid(), expected_gid=os.getgid()
        ):
            raise AssertionError("existing socket path was accepted")
    assert existing.read_bytes() == b"operator-owned"


@pytest.mark.asyncio
async def test_attestor_shutdown_closes_incomplete_challenge(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    root, _paths = _tree(tmp_path)
    runtime = tmp_path / "run"
    runtime.mkdir(mode=0o700)
    async with serve_governance_attestor(
        root, runtime, session_factory=session_factory, expected_uid=os.getuid(), expected_gid=os.getgid()
    ):
        reader, writer = await asyncio.open_unix_connection(runtime / "attestor.sock")
        writer.write(b'{"schema":')
        await writer.drain()
    try:
        async with asyncio.timeout(1):
            with contextlib.suppress(ConnectionResetError):
                assert await reader.read() == b""
    finally:
        writer.close()
        with contextlib.suppress(ConnectionResetError):
            await writer.wait_closed()


@pytest.mark.asyncio
async def test_attestor_bounds_incomplete_connections(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    root, _paths = _tree(tmp_path)
    runtime = tmp_path / "run"
    runtime.mkdir(mode=0o700)
    writers: list[asyncio.StreamWriter] = []
    reader = None
    try:
        async with serve_governance_attestor(
            root, runtime, session_factory=session_factory, expected_uid=os.getuid(), expected_gid=os.getgid()
        ):
            for _index in range(17):
                reader, writer = await asyncio.open_unix_connection(runtime / "attestor.sock")
                writers.append(writer)
            assert reader is not None
            async with asyncio.timeout(1):
                with contextlib.suppress(ConnectionResetError):
                    assert await reader.read() == b""
    finally:
        for writer in writers:
            writer.close()
            with contextlib.suppress(ConnectionResetError):
                await writer.wait_closed()
