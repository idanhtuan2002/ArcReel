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

    def __init__(self, directory: Path) -> None:
        self._directory = directory

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
            directory_fd = self._open_directory()
            try:
                before = os.fstat(directory_fd)
                expected = {name for name, _ in _PUBLIC_FILES}
                with os.scandir(directory_fd) as entries:
                    observed = {entry.name for entry in entries}
                if observed != expected:
                    raise CheckpointFileUnavailable("checkpoint file is unavailable")
                first = tuple(self._read_named(directory_fd, name, maximum) for name, maximum in _PUBLIC_FILES)
                second = tuple(self._read_named(directory_fd, name, maximum) for name, maximum in _PUBLIC_FILES)
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

    def _open_directory(self) -> int:
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
            for part in directory.parts[1:]:
                next_fd = os.open(part, directory_flags, dir_fd=directory_fd)
                os.close(directory_fd)
                directory_fd = next_fd
            return directory_fd
        except BaseException:
            os.close(directory_fd)
            raise

    @staticmethod
    def _read_named(directory_fd: int, name: str, maximum: int) -> bytes:
        file_fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory_fd)
        try:
            before = os.fstat(file_fd)
            if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
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
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_mode,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise CheckpointFileUnavailable("checkpoint file is unavailable")
            return b"".join(chunks)
        finally:
            os.close(file_fd)


__all__ = ["CheckpointFileUnavailable", "GovernanceCheckpointFile"]
