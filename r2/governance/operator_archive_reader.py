"""Read an operator-owned Governance archive without following path links."""

from __future__ import annotations

import os
import stat
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

import portalocker

from r2.contracts.governance_host_records import (
    MAX_HOST_RECORD_BYTES,
    parse_approved_deployment,
    parse_checkpoint_high_water,
)
from r2.contracts.governance_verifier_registry import MAX_VERIFIER_REGISTRY_BYTES
from r2.contracts.grant_checkpoint import MAX_GRANT_CHECKPOINT_BYTES
from r2.governance.archived_custody_chain import validate_archived_custody_chain
from r2.governance.public_custody_snapshot import VerifiedPublicCustodySnapshotV1

MAX_ARCHIVE_ENTRIES = 10_000
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
_PUBLIC_NAMES = {
    "approved-deployment.json",
    "governance-verifiers-v1.json",
    "high-water.json",
    "grant-checkpoint.json",
}
_ARCHIVE_NAMES = {"approved", "registries", "high-water", "checkpoints", ".staging", ".publisher.lock"}
_DIRECTORY_FLAGS = (
    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
)
_FILE_FLAGS = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


class OperatorArchiveInvalid(ValueError):
    """The host archive cannot establish one current Governance checkpoint."""

    def __init__(self) -> None:
        super().__init__("operator Governance archive is unavailable")


@dataclass(frozen=True)
class VerifiedOperatorArchiveV1:
    snapshot: VerifiedPublicCustodySnapshotV1
    approved_raw: bytes
    registry_raw: bytes
    high_water_raw: bytes
    checkpoint_raw: bytes


@dataclass(frozen=True)
class ArchiveReadLimits:
    max_entries: int = MAX_ARCHIVE_ENTRIES
    max_bytes: int = MAX_ARCHIVE_BYTES

    def __post_init__(self) -> None:
        if (
            type(self.max_entries) is not int
            or not 0 < self.max_entries <= MAX_ARCHIVE_ENTRIES
            or type(self.max_bytes) is not int
            or not 0 < self.max_bytes <= MAX_ARCHIVE_BYTES
        ):
            raise ValueError("invalid archive read limits")


@dataclass
class _Budget:
    limits: ArchiveReadLimits
    entries: int = 0
    byte_count: int = 0

    def add_entries(self, count: int) -> None:
        self.entries += count
        if self.entries > self.limits.max_entries:
            raise OperatorArchiveInvalid

    def add_bytes(self, count: int) -> None:
        self.byte_count += count
        if self.byte_count > self.limits.max_bytes:
            raise OperatorArchiveInvalid


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_nlink,
    )


def _directory(fd: int, *, uid: int, mode: int, device: int | None = None) -> os.stat_result:
    info = os.fstat(fd)
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != uid
        or stat.S_IMODE(info.st_mode) != mode
        or (device is not None and info.st_dev != device)
    ):
        raise OperatorArchiveInvalid
    return info


def _open_root(root: Path, stack: ExitStack, uid: int) -> tuple[int, os.stat_result]:
    if (
        not root.is_absolute()
        or root == Path("/")
        or "\x00" in os.fspath(root)
        or any(part in {".", ".."} for part in root.parts)
        or not all(hasattr(os, flag) for flag in ("O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC", "O_NONBLOCK"))
        or os.open not in os.supports_dir_fd
        or os.stat not in os.supports_dir_fd
        or os.stat not in os.supports_follow_symlinks
        or os.scandir not in os.supports_fd
    ):
        raise OperatorArchiveInvalid
    current = os.open("/", _DIRECTORY_FLAGS)
    stack.callback(os.close, current)
    for part in root.parts[1:]:
        current = os.open(part, _DIRECTORY_FLAGS, dir_fd=current)
        stack.callback(os.close, current)
    return current, _directory(current, uid=uid, mode=0o700)


def _open_child(
    parent: int, name: str, stack: ExitStack, *, uid: int, mode: int, device: int
) -> tuple[int, os.stat_result]:
    child = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent)
    stack.callback(os.close, child)
    return child, _directory(child, uid=uid, mode=mode, device=device)


def _regular(fd: int, *, uid: int, mode: int, device: int, maximum: int) -> os.stat_result:
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != uid
        or stat.S_IMODE(info.st_mode) != mode
        or info.st_nlink != 1
        or info.st_dev != device
        or not 0 <= info.st_size <= maximum
    ):
        raise OperatorArchiveInvalid
    return info


def _open_regular(
    parent: int, name: str, *, uid: int, mode: int, device: int, maximum: int
) -> tuple[int, os.stat_result]:
    observed = os.stat(name, dir_fd=parent, follow_symlinks=False)
    fd = os.open(name, _FILE_FLAGS, dir_fd=parent)
    try:
        before = _regular(fd, uid=uid, mode=mode, device=device, maximum=maximum)
        if _identity(observed) != _identity(before):
            raise OperatorArchiveInvalid
    except BaseException:
        os.close(fd)
        raise
    return fd, before


def _read_file(parent: int, name: str, *, uid: int, mode: int, device: int, maximum: int, budget: _Budget) -> bytes:
    fd, before = _open_regular(parent, name, uid=uid, mode=mode, device=device, maximum=maximum)
    try:
        budget.add_bytes(before.st_size)
        chunks: list[bytes] = []
        count = 0
        while chunk := os.read(fd, min(65_536, maximum + 1 - count)):
            count += len(chunk)
            if count > maximum:
                raise OperatorArchiveInvalid
            chunks.append(chunk)
        after = os.fstat(fd)
        if count != before.st_size or _identity(before) != _identity(after):
            raise OperatorArchiveInvalid
        return b"".join(chunks)
    finally:
        os.close(fd)


def _names(fd: int, budget: _Budget) -> set[str]:
    found: set[str] = set()
    with os.scandir(fd) as entries:
        for entry in entries:
            budget.add_entries(1)
            if entry.name in found:
                raise OperatorArchiveInvalid
            found.add(entry.name)
    return found


class OperatorArchiveReader:
    """Read one stable operator archive under its cooperating publisher lock."""

    def __init__(self, root: Path, *, expected_uid: int = 0, limits: ArchiveReadLimits | None = None) -> None:
        self._root = root
        self._uid = expected_uid
        self._limits = limits if limits is not None else ArchiveReadLimits()

    def read(self) -> VerifiedOperatorArchiveV1:
        try:
            return self._read()
        except OperatorArchiveInvalid:
            raise
        except (OSError, ValueError, portalocker.LockException):
            raise OperatorArchiveInvalid from None

    def _read(self) -> VerifiedOperatorArchiveV1:
        budget = _Budget(self._limits)
        uid = self._uid
        with ExitStack() as stack:
            root_fd, root_before = _open_root(self._root, stack, uid)
            device = root_before.st_dev
            archive_fd, archive_before = _open_child(root_fd, "archive", stack, uid=uid, mode=0o700, device=device)
            read_fd, read_before = _open_child(root_fd, "read", stack, uid=uid, mode=0o755, device=device)
            if _names(root_fd, budget) != {"archive", "read"} or _names(archive_fd, budget) != _ARCHIVE_NAMES:
                raise OperatorArchiveInvalid
            lock_fd, lock_before = _open_regular(
                archive_fd, ".publisher.lock", uid=uid, mode=0o600, device=device, maximum=0
            )
            lock = os.fdopen(lock_fd, "rb")
            stack.callback(lock.close)
            portalocker.lock(lock, portalocker.LOCK_EX | portalocker.LOCK_NB)
            stack.callback(portalocker.unlock, lock)

            approved_fd, approved_before = _open_child(
                archive_fd, "approved", stack, uid=uid, mode=0o700, device=device
            )
            registry_fd, registry_before = _open_child(
                archive_fd, "registries", stack, uid=uid, mode=0o700, device=device
            )
            high_water_fd, high_water_before = _open_child(
                archive_fd, "high-water", stack, uid=uid, mode=0o700, device=device
            )
            checkpoint_fd, checkpoint_before = _open_child(
                archive_fd, "checkpoints", stack, uid=uid, mode=0o700, device=device
            )
            staging_fd, staging_before = _open_child(archive_fd, ".staging", stack, uid=uid, mode=0o700, device=device)
            if _names(staging_fd, budget) or _names(approved_fd, budget) != {"00000000000000000001.json"}:
                raise OperatorArchiveInvalid
            approved_raw = _read_file(
                approved_fd,
                "00000000000000000001.json",
                uid=uid,
                mode=0o600,
                device=device,
                maximum=MAX_HOST_RECORD_BYTES,
                budget=budget,
            )
            approval = parse_approved_deployment(approved_raw)
            if approval.approval_sequence != 1:
                raise OperatorArchiveInvalid
            registry_name = f"sha256-{approval.body.registry_file_digest[7:]}.json"
            if _names(registry_fd, budget) != {registry_name}:
                raise OperatorArchiveInvalid
            registry_raw = _read_file(
                registry_fd,
                registry_name,
                uid=uid,
                mode=0o600,
                device=device,
                maximum=MAX_VERIFIER_REGISTRY_BYTES,
                budget=budget,
            )
            high_water_names = _names(high_water_fd, budget)
            if not high_water_names or high_water_names != {
                f"{sequence:020d}.json" for sequence in range(1, len(high_water_names) + 1)
            }:
                raise OperatorArchiveInvalid
            history: list[tuple[bytes, bytes]] = []
            checkpoint_names: set[str] = set()
            for sequence in range(1, len(high_water_names) + 1):
                name = f"{sequence:020d}.json"
                high_water_raw = _read_file(
                    high_water_fd,
                    name,
                    uid=uid,
                    mode=0o600,
                    device=device,
                    maximum=MAX_HOST_RECORD_BYTES,
                    budget=budget,
                )
                parsed = parse_checkpoint_high_water(high_water_raw)
                checkpoint_name = f"sha256-{parsed.body.checkpoint_file_digest[7:]}.json"
                checkpoint_names.add(checkpoint_name)
                checkpoint_raw = _read_file(
                    checkpoint_fd,
                    checkpoint_name,
                    uid=uid,
                    mode=0o600,
                    device=device,
                    maximum=MAX_GRANT_CHECKPOINT_BYTES,
                    budget=budget,
                )
                history.append((high_water_raw, checkpoint_raw))
            if _names(checkpoint_fd, budget) != checkpoint_names or _names(read_fd, budget) != _PUBLIC_NAMES:
                raise OperatorArchiveInvalid
            public = (
                _read_file(
                    read_fd,
                    "approved-deployment.json",
                    uid=uid,
                    mode=0o644,
                    device=device,
                    maximum=MAX_HOST_RECORD_BYTES,
                    budget=budget,
                ),
                _read_file(
                    read_fd,
                    "governance-verifiers-v1.json",
                    uid=uid,
                    mode=0o644,
                    device=device,
                    maximum=MAX_VERIFIER_REGISTRY_BYTES,
                    budget=budget,
                ),
                _read_file(
                    read_fd,
                    "high-water.json",
                    uid=uid,
                    mode=0o644,
                    device=device,
                    maximum=MAX_HOST_RECORD_BYTES,
                    budget=budget,
                ),
                _read_file(
                    read_fd,
                    "grant-checkpoint.json",
                    uid=uid,
                    mode=0o644,
                    device=device,
                    maximum=MAX_GRANT_CHECKPOINT_BYTES,
                    budget=budget,
                ),
            )
            snapshot = validate_archived_custody_chain(approved_raw, registry_raw, history, public)
            directories = (
                (root_fd, root_before),
                (archive_fd, archive_before),
                (read_fd, read_before),
                (approved_fd, approved_before),
                (registry_fd, registry_before),
                (high_water_fd, high_water_before),
                (checkpoint_fd, checkpoint_before),
                (staging_fd, staging_before),
            )
            if any(_identity(before) != _identity(os.fstat(fd)) for fd, before in directories):
                raise OperatorArchiveInvalid
            lock_after = os.stat(".publisher.lock", dir_fd=archive_fd, follow_symlinks=False)
            if _identity(lock_before) != _identity(lock_after):
                raise OperatorArchiveInvalid
            with ExitStack() as check_stack:
                _reopened, reopened_info = _open_root(self._root, check_stack, uid)
                if _identity(root_before) != _identity(reopened_info):
                    raise OperatorArchiveInvalid
            return VerifiedOperatorArchiveV1(snapshot, approved_raw, registry_raw, history[-1][0], history[-1][1])


__all__ = ["ArchiveReadLimits", "OperatorArchiveInvalid", "OperatorArchiveReader", "VerifiedOperatorArchiveV1"]
