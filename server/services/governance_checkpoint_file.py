"""Read complete checkpoint bytes from an operator-provided directory."""

from __future__ import annotations

import asyncio
import os
import stat
from pathlib import Path

from r2.contracts.governance_host_records import MAX_HOST_RECORD_BYTES
from r2.contracts.governance_verifier_registry import MAX_VERIFIER_REGISTRY_BYTES
from r2.contracts.grant_checkpoint import MAX_GRANT_CHECKPOINT_BYTES

_CHECKPOINT_NAME = "grant-checkpoint.json"
_READ_CHUNK_BYTES = 65_536
_PUBLIC_FILES = (
    ("approved-deployment.json", MAX_HOST_RECORD_BYTES),
    ("governance-verifiers-v1.json", MAX_VERIFIER_REGISTRY_BYTES),
    ("high-water.json", MAX_HOST_RECORD_BYTES),
    (_CHECKPOINT_NAME, MAX_GRANT_CHECKPOINT_BYTES),
)


class CheckpointFileUnavailable(RuntimeError):
    """A complete regular checkpoint file cannot be read."""


class GovernanceCheckpointFile:
    """Reopen one fixed pathname for each scanner or transaction read."""

    def __init__(self, directory: Path, *, expected_uid: int = 0, expected_gid: int = 0) -> None:
        self._directory = directory
        self._expected_uid = expected_uid
        self._expected_gid = expected_gid

    async def load(self) -> bytes:
        return await asyncio.to_thread(self._read)

    async def load_public_copies(self) -> tuple[bytes, bytes, bytes, bytes]:
        """Read the fixed public set twice and require stable complete bytes."""
        return await asyncio.to_thread(self._read_public_copies)

    def _read(self) -> bytes:
        try:
            directory_fd = self._open_directory()
            try:
                return self._read_named(directory_fd, _CHECKPOINT_NAME, MAX_GRANT_CHECKPOINT_BYTES)
            finally:
                os.close(directory_fd)
        except OSError:
            raise CheckpointFileUnavailable("checkpoint file is unavailable") from None

    def _read_public_copies(self) -> tuple[bytes, bytes, bytes, bytes]:
        if os.scandir not in os.supports_fd:
            raise CheckpointFileUnavailable("checkpoint file is unavailable")
        try:
            directory_fd = self._open_directory(require_public_custody=True)
            try:
                before = os.fstat(directory_fd)
                expected = {name for name, _ in _PUBLIC_FILES}
                with os.scandir(directory_fd) as entries:
                    observed = {entry.name for entry in entries}
                if observed != expected:
                    raise CheckpointFileUnavailable("checkpoint file is unavailable")
                custody = (self._expected_uid, self._expected_gid, before.st_dev)
                first = tuple(
                    self._read_named(directory_fd, name, maximum, public_custody=custody)
                    for name, maximum in _PUBLIC_FILES
                )
                second = tuple(
                    self._read_named(directory_fd, name, maximum, public_custody=custody)
                    for name, maximum in _PUBLIC_FILES
                )
                after = os.fstat(directory_fd)
                if first != second or (
                    before.st_dev,
                    before.st_ino,
                    before.st_mode,
                    before.st_mtime_ns,
                    before.st_ctime_ns,
                ) != (
                    after.st_dev,
                    after.st_ino,
                    after.st_mode,
                    after.st_mtime_ns,
                    after.st_ctime_ns,
                ):
                    raise CheckpointFileUnavailable("checkpoint file is unavailable")
                return first[0], first[1], first[2], first[3]
            finally:
                os.close(directory_fd)
        except OSError:
            raise CheckpointFileUnavailable("checkpoint file is unavailable") from None

    def _open_directory(self, *, require_public_custody: bool = False) -> int:
        directory = self._directory
        if (
            not directory.is_absolute()
            or directory == Path("/")
            or any(part == ".." for part in directory.parts)
            or not all(hasattr(os, flag) for flag in ("O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC", "O_NONBLOCK"))
            or os.open not in os.supports_dir_fd
        ):
            raise CheckpointFileUnavailable("checkpoint file is unavailable")
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        directory_fd = os.open("/", directory_flags)
        try:
            if require_public_custody:
                self._check_ancestor(os.fstat(directory_fd))
            for part in directory.parts[1:]:
                next_fd = os.open(part, directory_flags, dir_fd=directory_fd)
                os.close(directory_fd)
                directory_fd = next_fd
                if require_public_custody:
                    self._check_ancestor(os.fstat(directory_fd))
            if require_public_custody:
                info = os.fstat(directory_fd)
                if (
                    info.st_uid != self._expected_uid
                    or info.st_gid != self._expected_gid
                    or stat.S_IMODE(info.st_mode) != 0o755
                ):
                    raise CheckpointFileUnavailable("checkpoint file is unavailable")
            return directory_fd
        except BaseException:
            os.close(directory_fd)
            raise

    def _check_ancestor(self, info: os.stat_result) -> None:
        mode = stat.S_IMODE(info.st_mode)
        sticky_root = info.st_uid == 0 and bool(mode & stat.S_ISVTX)
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid not in {0, self._expected_uid}
            or (mode & 0o022 and not sticky_root)
        ):
            raise CheckpointFileUnavailable("checkpoint file is unavailable")

    @staticmethod
    def _read_named(
        directory_fd: int, name: str, maximum: int, *, public_custody: tuple[int, int, int] | None = None
    ) -> bytes:
        file_fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory_fd)
        try:
            before = os.fstat(file_fd)
            if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
                raise CheckpointFileUnavailable("checkpoint file is unavailable")
            if public_custody is not None and (
                (before.st_uid, before.st_gid, before.st_dev) != public_custody
                or stat.S_IMODE(before.st_mode) != 0o644
                or before.st_nlink != 1
            ):
                raise CheckpointFileUnavailable("checkpoint file is unavailable")
            chunks: list[bytes] = []
            byte_count = 0
            while chunk := os.read(file_fd, min(_READ_CHUNK_BYTES, maximum + 1 - byte_count)):
                byte_count += len(chunk)
                if byte_count > maximum:
                    raise CheckpointFileUnavailable("checkpoint file is unavailable")
                chunks.append(chunk)
            after = os.fstat(file_fd)
            if byte_count != before.st_size or (
                before.st_dev,
                before.st_ino,
                before.st_mode,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
                before.st_nlink,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_mode,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
                after.st_nlink,
            ):
                raise CheckpointFileUnavailable("checkpoint file is unavailable")
            return b"".join(chunks)
        finally:
            os.close(file_fd)


__all__ = ["CheckpointFileUnavailable", "GovernanceCheckpointFile"]
