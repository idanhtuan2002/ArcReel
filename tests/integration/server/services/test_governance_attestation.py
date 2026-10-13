"""Real Unix channels bind a startup challenge to independent archive preflight."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import socket
from pathlib import Path

import portalocker
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.services.governance_attestation import (
    GovernanceAttestationUnavailable,
    read_peer_credentials,
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
    "fault",
    [
        "none",
        "old_nonce",
        "extra_field",
        "trailing",
        "oversized",
        "bad_mode",
        "wrong_owner",
        "wrong_peer",
        "replaced",
        "deadline",
    ],
)
async def test_real_socket_denies_untrusted_response(tmp_path: Path, fault: str) -> None:
    runtime = tmp_path / "run"
    runtime.mkdir(mode=0o700)
    path = runtime / "attestor.sock"
    _root, paths = _tree(tmp_path)
    copies = _copies(paths)

    replacement: list[socket.socket] = []

    async def replacing_connect(**kwargs: object) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        connected = await asyncio.open_unix_connection(**kwargs)
        path.unlink()
        other = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        other.bind(str(path))
        os.chmod(path, 0o600)
        replacement.append(other)
        return connected

    seams: dict[str, object] = {
        "wrong_peer": {"peer_credentials": lambda _peer: (os.getuid() + 1, os.getgid())},
        "replaced": {"connect": replacing_connect},
        "deadline": {"exchange_seconds": 0},
    }.get(fault, {})

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
                    runtime,
                    copies,
                    expected_uid=os.getuid() + (fault == "wrong_owner"),
                    expected_gid=os.getgid(),
                    **seams,
                )
    finally:
        for other in replacement:
            other.close()
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


def test_peer_credentials_read_connected_linux_owner() -> None:
    left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    with left, right:
        assert read_peer_credentials(left) == (os.getuid(), os.getgid())


@pytest.mark.asyncio
async def test_attestor_denies_competing_challenge_while_preflight_runs(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    root, _paths = _tree(tmp_path)
    runtime = tmp_path / "run"
    runtime.mkdir(mode=0o700)
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocked_preflight(*_args: object, **_kwargs: object):
        started.set()
        await release.wait()
        raise RuntimeError("archive unavailable")

    challenge = json.dumps({"nonce": "a" * 64, "schema": "governance.startup_challenge.v1"}, separators=(",", ":"))
    writers: list[asyncio.StreamWriter] = []
    try:
        async with serve_governance_attestor(
            root,
            runtime,
            session_factory=session_factory,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
            preflight=blocked_preflight,
        ):
            exchanges = []
            for _index in range(2):
                reader, writer = await asyncio.open_unix_connection(runtime / "attestor.sock")
                writers.append(writer)
                writer.write(challenge.encode() + b"\n")
                writer.write_eof()
                exchanges.append(reader)
                if not started.is_set():
                    await started.wait()
            async with asyncio.timeout(1):
                assert await exchanges[1].read() == b""
            first = asyncio.create_task(exchanges[0].read())
            await asyncio.sleep(0)
            assert not first.done()
            release.set()
            async with asyncio.timeout(1):
                assert await first == b""
    finally:
        for writer in writers:
            writer.close()
            with contextlib.suppress(ConnectionResetError):
                await writer.wait_closed()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "challenge",
    [
        b'{"nonce":"' + b"a" * 64 + b'","schema":"governance.startup_challenge.v1","x":1}\n',
        b'{"nonce":"' + b"A" * 64 + b'","schema":"governance.startup_challenge.v1"}\n',
        b'{"schema":"governance.startup_challenge.v1","nonce":"' + b"a" * 64 + b'"}\n',
        b'{"nonce":"' + b"a" * 64 + b'","schema":"governance.startup_challenge.v2"}\n',
        b"[]\n",
        b"\n",
    ],
    ids=["extra_field", "uppercase_nonce", "noncanonical_order", "wrong_schema", "not_object", "empty"],
)
async def test_attestor_rejects_malformed_challenge_without_preflight(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path, challenge: bytes
) -> None:
    root, _paths = _tree(tmp_path)
    runtime = tmp_path / "run"
    runtime.mkdir(mode=0o700)
    calls: list[object] = []

    async def recording_preflight(*args: object, **_kwargs: object):
        calls.append(args)
        raise RuntimeError("archive unavailable")

    async with serve_governance_attestor(
        root,
        runtime,
        session_factory=session_factory,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
        preflight=recording_preflight,
    ):
        reader, writer = await asyncio.open_unix_connection(runtime / "attestor.sock")
        try:
            writer.write(challenge)
            writer.write_eof()
            async with asyncio.timeout(1):
                assert await reader.read() == b""
        finally:
            writer.close()
            with contextlib.suppress(ConnectionResetError):
                await writer.wait_closed()
    assert calls == []


@pytest.mark.asyncio
async def test_pg_attestor_denies_while_publisher_holds_archive_lock(
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
        with paths["lock"].open("rb") as held:
            portalocker.lock(held, portalocker.LOCK_EX | portalocker.LOCK_NB)
            try:
                with pytest.raises(GovernanceAttestationUnavailable):
                    await require_governance_archive_freshness(
                        runtime, _copies(paths), expected_uid=os.getuid(), expected_gid=os.getgid()
                    )
            finally:
                portalocker.unlock(held)
        await require_governance_archive_freshness(
            runtime, _copies(paths), expected_uid=os.getuid(), expected_gid=os.getgid()
        )
