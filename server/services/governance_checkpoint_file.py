"""Read complete checkpoint bytes from an operator-provided directory."""

from __future__ import annotations

import asyncio
import os
import stat
from pathlib import Path

from r2.contracts.grant_checkpoint import MAX_GRANT_CHECKPOINT_BYTES

_CHECKPOINT_NAME = "grant-checkpoint.json"
_READ_CHUNK_BYTES = 65_536


class CheckpointFileUnavailable(RuntimeError):
    """A complete regular checkpoint file cannot be read."""


class GovernanceCheckpointFile:
    """Reopen one fixed pathname for each scanner or transaction read."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    async def load(self) -> bytes:
        return await asyncio.to_thread(self._read)

    def _read(self) -> bytes:
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
        try:
            directory_fd = os.open("/", directory_flags)
            try:
                for part in directory.parts[1:]:
                    next_fd = os.open(part, directory_flags, dir_fd=directory_fd)
                    os.close(directory_fd)
                    directory_fd = next_fd
                file_fd = os.open(
                    _CHECKPOINT_NAME,
                    os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=directory_fd,
                )
                try:
                    before = os.fstat(file_fd)
                    if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_GRANT_CHECKPOINT_BYTES:
                        raise CheckpointFileUnavailable("checkpoint file is unavailable")
                    chunks: list[bytes] = []
                    byte_count = 0
                    while chunk := os.read(
                        file_fd, min(_READ_CHUNK_BYTES, MAX_GRANT_CHECKPOINT_BYTES + 1 - byte_count)
                    ):
                        byte_count += len(chunk)
                        if byte_count > MAX_GRANT_CHECKPOINT_BYTES:
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
            finally:
                os.close(directory_fd)
        except OSError:
            raise CheckpointFileUnavailable("checkpoint file is unavailable") from None


__all__ = ["CheckpointFileUnavailable", "GovernanceCheckpointFile"]
