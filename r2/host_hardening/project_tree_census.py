"""Read-only physical census for an approved H6 project tree.

The caller owns project admission and the write fence. A census is not a
consistent backup, a reference classifier, or restore authority.
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

type CensusFailureCode = Literal[
    "ROOT_INVALID", "ENTRY_UNSUPPORTED", "ENTRY_CHANGED", "LIMIT_EXCEEDED", "PLATFORM_UNSUPPORTED"
]

_CHUNK_SIZE = 1024 * 1024


class CensusError(Exception):
    """A sanitized physical-census failure."""

    def __init__(self, code: CensusFailureCode) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class CensusLimits:
    max_files: int
    max_entries: int
    max_file_bytes: int
    max_total_bytes: int
    max_depth: int

    def __post_init__(self) -> None:
        if any(
            type(value) is not int or value <= 0
            for value in (self.max_files, self.max_entries, self.max_file_bytes, self.max_total_bytes, self.max_depth)
        ):
            raise ValueError("census bounds must be positive integers")


@dataclass(frozen=True)
class DirectoryRecord:
    relative_path: str


@dataclass(frozen=True)
class FileRecord:
    relative_path: str
    byte_size: int
    content_digest: str


@dataclass(frozen=True)
class TreeCensus:
    directories: tuple[DirectoryRecord, ...]
    files: tuple[FileRecord, ...]
    total_bytes: int


def _open_root(root: Path) -> int:
    if (
        not root.is_absolute()
        or root == Path("/")
        or "\x00" in os.fspath(root)
        or any(part in {".", ".."} for part in root.parts)
    ):
        raise CensusError("ROOT_INVALID")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        current_fd = os.open("/", flags)
        for part in root.parts[1:]:
            try:
                next_fd = os.open(part, flags, dir_fd=current_fd)
            finally:
                os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except OSError:
        raise CensusError("ROOT_INVALID") from None


def _same_identity(first: os.stat_result, second: os.stat_result) -> bool:
    return (first.st_dev, first.st_ino, first.st_mode) == (second.st_dev, second.st_ino, second.st_mode)


def _read_file(directory_fd: int, name: str, observed: os.stat_result, remaining: int, per_file: int) -> FileRecord:
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    try:
        file_fd = os.open(name, flags, dir_fd=directory_fd)
    except OSError:
        raise CensusError("ENTRY_CHANGED") from None
    try:
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode) or not _same_identity(observed, before):
            raise CensusError("ENTRY_CHANGED")
        if before.st_size > per_file or before.st_size > remaining:
            raise CensusError("LIMIT_EXCEEDED")
        digest = hashlib.sha256()
        count = 0
        while chunk := os.read(file_fd, min(_CHUNK_SIZE, per_file - count + 1, remaining - count + 1)):
            count += len(chunk)
            if count > per_file or count > remaining:
                raise CensusError("LIMIT_EXCEEDED")
            digest.update(chunk)
        after = os.fstat(file_fd)
        if (
            not _same_identity(before, after)
            or count != before.st_size
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
        ):
            raise CensusError("ENTRY_CHANGED")
        return FileRecord("", count, "sha256:" + digest.hexdigest())
    except OSError:
        raise CensusError("ENTRY_CHANGED") from None
    finally:
        os.close(file_fd)


def scan_project_tree(root: Path, *, limits: CensusLimits) -> TreeCensus:
    """Hash every regular file and retain every directory under an approved root.

    The caller must separately prove a source write fence and project liveness.
    POSIX no-follow directory descriptors are required; no path is opened by
    following a symlink. Returned paths are relative to ``root``.
    """
    if (
        not all(hasattr(os, flag) for flag in ("O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC", "O_NONBLOCK"))
        or os.open not in os.supports_dir_fd
        or os.scandir not in os.supports_fd
        or os.stat not in os.supports_dir_fd
    ):
        raise CensusError("PLATFORM_UNSUPPORTED")

    directories: list[DirectoryRecord] = []
    files: list[FileRecord] = []
    total_bytes = 0

    def visit(directory_fd: int, relative: str, depth: int) -> None:
        nonlocal total_bytes
        if len(directories) + len(files) >= limits.max_entries:
            raise CensusError("LIMIT_EXCEEDED")
        directories.append(DirectoryRecord(relative))
        try:
            with os.scandir(directory_fd) as iterator:
                entries = []
                for entry in iterator:
                    if len(entries) >= limits.max_entries:
                        raise CensusError("LIMIT_EXCEEDED")
                    entries.append(entry)
                entries.sort(key=lambda entry: entry.name)
        except OSError:
            raise CensusError("ENTRY_CHANGED") from None
        for entry in entries:
            name = entry.name
            path = f"{relative}/{name}" if relative else name
            try:
                observed = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except OSError:
                raise CensusError("ENTRY_CHANGED") from None
            if stat.S_ISDIR(observed.st_mode):
                if depth >= limits.max_depth:
                    raise CensusError("LIMIT_EXCEEDED")
                try:
                    child_fd = os.open(
                        name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory_fd
                    )
                except OSError:
                    raise CensusError("ENTRY_CHANGED") from None
                try:
                    if not _same_identity(observed, os.fstat(child_fd)):
                        raise CensusError("ENTRY_CHANGED")
                    visit(child_fd, path, depth + 1)
                finally:
                    os.close(child_fd)
            elif stat.S_ISREG(observed.st_mode):
                if len(files) >= limits.max_files or len(directories) + len(files) >= limits.max_entries:
                    raise CensusError("LIMIT_EXCEEDED")
                record = _read_file(
                    directory_fd, name, observed, limits.max_total_bytes - total_bytes, limits.max_file_bytes
                )
                files.append(FileRecord(path, record.byte_size, record.content_digest))
                total_bytes += record.byte_size
            else:
                raise CensusError("ENTRY_UNSUPPORTED")

    root_fd = _open_root(root)
    try:
        visit(root_fd, "", 0)
    finally:
        os.close(root_fd)
    return TreeCensus(
        tuple(sorted(directories, key=lambda item: item.relative_path)),
        tuple(sorted(files, key=lambda item: item.relative_path)),
        total_bytes,
    )
