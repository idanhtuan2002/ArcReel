"""Authenticate a fresh host archive preflight over a bounded Linux Unix channel."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import re
import secrets
import socket
import stat
import struct
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.content_digest import canonical_json_bytes
from r2.governance.public_custody_snapshot import validate_public_custody_snapshot
from server.services.governance_operator_archive import verify_operator_archive_preflight

_MAX_MESSAGE_BYTES = 4096
_EXCHANGE_SECONDS = 30
_MAX_CONNECTIONS = 16
_SOCKET_NAME = "attestor.sock"
_NONCE = re.compile(r"\A[0-9a-f]{64}\Z")


class GovernanceAttestationUnavailable(RuntimeError):
    """The authenticated archive freshness exchange could not complete."""

    def __init__(self) -> None:
        super().__init__("Governance archive freshness is unavailable")


def _digests(copies: tuple[bytes, bytes, bytes, bytes]) -> list[str]:
    return ["sha256:" + hashlib.sha256(raw).hexdigest() for raw in copies]


@contextmanager
def _socket_directory(path: Path, uid: int, gid: int) -> Generator[int]:
    if (
        not path.is_absolute()
        or path == Path("/")
        or ".." in path.parts
        or not hasattr(socket, "SO_PEERCRED")
        or not all(hasattr(os, flag) for flag in ("O_NOFOLLOW", "O_DIRECTORY", "O_CLOEXEC"))
    ):
        raise GovernanceAttestationUnavailable
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY | os.O_CLOEXEC
    fd = os.open("/", flags)
    try:
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            mode = stat.S_IMODE(info.st_mode)
            if info.st_uid not in {0, uid} or (mode & 0o022 and not (info.st_uid == 0 and mode & stat.S_ISVTX)):
                raise GovernanceAttestationUnavailable
        info = os.fstat(fd)
        if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (uid, gid, 0o700):
            raise GovernanceAttestationUnavailable
        yield fd
    finally:
        os.close(fd)


def _socket_identity(fd: int, uid: int, gid: int) -> tuple[int, int]:
    info = os.stat(_SOCKET_NAME, dir_fd=fd, follow_symlinks=False)
    if (
        not stat.S_ISSOCK(info.st_mode)
        or (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (uid, gid, 0o600)
        or info.st_nlink != 1
    ):
        raise GovernanceAttestationUnavailable
    return info.st_dev, info.st_ino


async def _read_message(reader: asyncio.StreamReader) -> dict[str, object]:
    raw = await reader.readuntil(b"\n")
    if not 1 < len(raw) <= _MAX_MESSAGE_BYTES + 1 or await reader.read(1):
        raise GovernanceAttestationUnavailable
    parsed = json.loads(raw[:-1])
    if not isinstance(parsed, dict) or canonical_json_bytes(parsed, allow_nan=False) != raw[:-1]:
        raise GovernanceAttestationUnavailable
    return cast(dict[str, object], parsed)


async def _close(writer: asyncio.StreamWriter) -> None:
    writer.close()
    with contextlib.suppress(ConnectionError, OSError):
        await writer.wait_closed()


class GovernanceArchiveAttestor:
    """One fixed root and database; every challenge performs a new preflight."""

    def __init__(self, root: Path, *, session_factory: async_sessionmaker[AsyncSession], expected_uid: int = 0) -> None:
        self._root = root
        self._sessions = session_factory
        self._uid = expected_uid
        self._busy = asyncio.Lock()
        self._connections: dict[asyncio.Task[None], asyncio.StreamWriter] = {}
        self._closing = False

    def accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if self._closing or len(self._connections) >= _MAX_CONNECTIONS:
            writer.close()
            return
        task = asyncio.create_task(self.handle(reader, writer))
        self._connections[task] = writer
        task.add_done_callback(lambda done: self._connections.pop(done, None))

    async def shutdown(self) -> None:
        self._closing = True
        connections = tuple(self._connections.items())
        for task, writer in connections:
            writer.close()
            task.cancel()
        await asyncio.gather(*(task for task, _writer in connections), return_exceptions=True)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            async with asyncio.timeout(_EXCHANGE_SECONDS):
                challenge = await _read_message(reader)
                nonce = challenge.get("nonce")
                if (
                    set(challenge) != {"schema", "nonce"}
                    or challenge.get("schema") != "governance.startup_challenge.v1"
                    or not isinstance(nonce, str)
                    or not _NONCE.fullmatch(nonce)
                    or self._busy.locked()
                ):
                    raise GovernanceAttestationUnavailable
                async with self._busy:
                    current = await verify_operator_archive_preflight(
                        self._root, session_factory=self._sessions, expected_uid=self._uid
                    )
                    proof = {
                        "schema": "governance.startup_proof.v1",
                        "nonce": nonce,
                        "deployment_id": current.snapshot.approval.deployment_id,
                        "checkpoint_sequence": current.snapshot.high_water.checkpoint_sequence,
                        "public_digests": _digests(
                            (current.approved_raw, current.registry_raw, current.high_water_raw, current.checkpoint_raw)
                        ),
                    }
                    writer.write(canonical_json_bytes(proof, allow_nan=False) + b"\n")
                    await writer.drain()
        except Exception:
            # A failed exchange returns no proof or internal error text.
            pass
        finally:
            await _close(writer)


@asynccontextmanager
async def serve_governance_attestor(
    root: Path,
    socket_directory: Path,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    expected_uid: int = 0,
    expected_gid: int = 0,
) -> AsyncGenerator[asyncio.Server]:
    """Bind in a provisioned directory; never replace an existing pathname."""
    try:
        with _socket_directory(socket_directory, expected_uid, expected_gid) as fd:
            anchored = f"/proc/self/fd/{fd}/{_SOCKET_NAME}"
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            identity: tuple[int, int] | None = None
            server: asyncio.Server | None = None
            attestor = GovernanceArchiveAttestor(root, session_factory=session_factory, expected_uid=expected_uid)
            try:
                listener.bind(anchored)
                created = os.stat(_SOCKET_NAME, dir_fd=fd, follow_symlinks=False)
                identity = (created.st_dev, created.st_ino)
                os.chmod(_SOCKET_NAME, 0o600, dir_fd=fd, follow_symlinks=False)
                _socket_identity(fd, expected_uid, expected_gid)
                listener.listen(16)
                listener.setblocking(False)
                server = await asyncio.start_unix_server(attestor.accept, sock=listener, limit=_MAX_MESSAGE_BYTES)
                yield server
            finally:
                if server is not None:
                    # Let already queued accept callbacks register their connection writers.
                    await asyncio.sleep(0)
                    server.close()
                    await attestor.shutdown()
                    await server.wait_closed()
                listener.close()
                if identity is not None:
                    with contextlib.suppress(OSError, GovernanceAttestationUnavailable):
                        current = os.stat(_SOCKET_NAME, dir_fd=fd, follow_symlinks=False)
                        if (current.st_dev, current.st_ino) == identity:
                            os.unlink(_SOCKET_NAME, dir_fd=fd)
    except (OSError, ValueError):
        raise GovernanceAttestationUnavailable from None


async def require_governance_archive_freshness(
    socket_directory: Path,
    copies: tuple[bytes, bytes, bytes, bytes],
    *,
    expected_uid: int = 0,
    expected_gid: int = 0,
) -> None:
    """Require a fresh host response for these exact public copies."""
    writer: asyncio.StreamWriter | None = None
    try:
        snapshot = validate_public_custody_snapshot(*copies)
        nonce = secrets.token_hex(32)
        async with asyncio.timeout(_EXCHANGE_SECONDS):
            with _socket_directory(socket_directory, expected_uid, expected_gid) as fd:
                before = _socket_identity(fd, expected_uid, expected_gid)
                reader, writer = await asyncio.open_unix_connection(
                    path=f"/proc/self/fd/{fd}/{_SOCKET_NAME}", limit=_MAX_MESSAGE_BYTES
                )
                peer = writer.get_extra_info("socket")
                if peer is None:
                    raise GovernanceAttestationUnavailable
                _pid, uid, gid = struct.unpack("3i", peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                if (uid, gid) != (expected_uid, expected_gid) or _socket_identity(
                    fd, expected_uid, expected_gid
                ) != before:
                    raise GovernanceAttestationUnavailable
                writer.write(
                    canonical_json_bytes({"schema": "governance.startup_challenge.v1", "nonce": nonce}) + b"\n"
                )
                await writer.drain()
                writer.write_eof()
                proof = await _read_message(reader)
                if (
                    set(proof) != {"schema", "nonce", "deployment_id", "checkpoint_sequence", "public_digests"}
                    or proof.get("schema") != "governance.startup_proof.v1"
                    or proof.get("nonce") != nonce
                    or proof.get("deployment_id") != snapshot.approval.deployment_id
                    or type(proof.get("checkpoint_sequence")) is not int
                    or proof.get("checkpoint_sequence") != snapshot.high_water.checkpoint_sequence
                    or proof.get("public_digests") != _digests(copies)
                ):
                    raise GovernanceAttestationUnavailable
    except Exception:
        raise GovernanceAttestationUnavailable from None
    finally:
        if writer is not None:
            await _close(writer)


__all__ = [
    "GovernanceArchiveAttestor",
    "GovernanceAttestationUnavailable",
    "require_governance_archive_freshness",
    "serve_governance_attestor",
]
