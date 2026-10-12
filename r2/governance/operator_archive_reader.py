"""Read an operator-owned Governance archive without following path links."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Generator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import portalocker

from r2.contracts.governance_host_records import (
    MAX_HOST_RECORD_BYTES,
    parse_approved_deployment,
    parse_checkpoint_high_water,
)
from r2.contracts.governance_verifier_registry import MAX_VERIFIER_REGISTRY_BYTES
from r2.contracts.grant_checkpoint import MAX_GRANT_CHECKPOINT_BYTES, CheckpointInvalid, parse_grant_checkpoint
from r2.governance.archived_custody_chain import validate_retained_custody_chain
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


@dataclass(frozen=True)
class _RetainedArchiveState:
    snapshot: VerifiedPublicCustodySnapshotV1
    approved_raw: bytes
    registry_raw: bytes
    history: tuple[tuple[bytes, bytes], ...]
    public: tuple[bytes, bytes, bytes, bytes]
    public_temps: tuple[str, ...] = ()


def classify_public_copies(state: _RetainedArchiveState) -> Literal["current", "previous", "new_high_water"]:
    if state.public[:2] != (state.approved_raw, state.registry_raw):
        raise OperatorArchiveInvalid
    current = state.history[-1]
    if state.public[2:] == current:
        return "current"
    if len(state.history) < 2:
        raise OperatorArchiveInvalid
    previous = state.history[-2]
    if state.public[2:] == previous:
        return "previous"
    if state.public[2:] == (current[0], previous[1]):
        return "new_high_water"
    raise OperatorArchiveInvalid


@dataclass
class _LockedArchive:
    root: Path
    uid: int
    limits: ArchiveReadLimits
    device: int
    directories: tuple[tuple[int, os.stat_result], ...]
    archive_fd: int
    read_fd: int
    approved_fd: int
    registry_fd: int
    high_water_fd: int
    checkpoint_fd: int
    staging_fd: int
    lock_before: os.stat_result

    def read_retained(self, *, allow_public_temps: bool = False) -> _RetainedArchiveState:
        """Verify the complete retained chain while keeping the publisher lock."""
        return self._scan(require_public_current=False, allow_public_temps=allow_public_temps)

    def read_orphan_checkpoint(self, candidate_raw: bytes) -> _RetainedArchiveState:
        """Verify one exact orphan envelope against a complete prior archive."""
        return self._read_candidate_checkpoint(candidate_raw, location="orphan")

    def read_staged_checkpoint(self, candidate_raw: bytes) -> _RetainedArchiveState:
        """Verify one exact unlinked staged envelope against a complete prior archive."""
        return self._read_candidate_checkpoint(candidate_raw, location="staged")

    def _read_candidate_checkpoint(
        self, candidate_raw: bytes, *, location: Literal["orphan", "staged"]
    ) -> _RetainedArchiveState:
        if type(candidate_raw) is not bytes or not 0 < len(candidate_raw) <= MAX_GRANT_CHECKPOINT_BYTES:
            raise OperatorArchiveInvalid
        try:
            candidate = parse_grant_checkpoint(candidate_raw)
        except CheckpointInvalid:
            raise OperatorArchiveInvalid from None
        state = self._scan(
            require_public_current=True,
            allow_public_temps=False,
            expected_orphan=candidate_raw if location == "orphan" else None,
            expected_staged=(f".checkpoint.{candidate.body.checkpoint_sequence:020d}.tmp", candidate_raw)
            if location == "staged"
            else None,
        )
        if (
            candidate.body.checkpoint_sequence != state.snapshot.high_water.checkpoint_sequence + 1
            or candidate.body.deployment_id != state.snapshot.approval.deployment_id
            or candidate.body.previous_checkpoint_digest != state.snapshot.checkpoint.checkpoint_digest
        ):
            raise OperatorArchiveInvalid
        return state

    def read_complete(self) -> VerifiedOperatorArchiveV1:
        """Require exact latest public copies as well as a valid retained chain."""
        state = self._scan(require_public_current=True, allow_public_temps=False)
        return VerifiedOperatorArchiveV1(
            state.snapshot, state.approved_raw, state.registry_raw, state.history[-1][0], state.history[-1][1]
        )

    def _scan(
        self,
        *,
        require_public_current: bool,
        allow_public_temps: bool,
        expected_orphan: bytes | None = None,
        expected_staged: tuple[str, bytes] | None = None,
    ) -> _RetainedArchiveState:
        budget = _Budget(self.limits)
        uid = self.uid
        device = self.device
        root_fd = self.directories[0][0]
        if _names(root_fd, budget) != {"archive", "read"} or _names(self.archive_fd, budget) != _ARCHIVE_NAMES:
            raise OperatorArchiveInvalid
        staging_names = _names(self.staging_fd, budget)
        if staging_names != ({expected_staged[0]} if expected_staged is not None else set()) or _names(
            self.approved_fd, budget
        ) != {"00000000000000000001.json"}:
            raise OperatorArchiveInvalid
        if expected_staged is not None and (
            _read_file(
                self.staging_fd,
                expected_staged[0],
                uid=uid,
                mode=0o600,
                device=device,
                maximum=MAX_GRANT_CHECKPOINT_BYTES,
                budget=budget,
            )
            != expected_staged[1]
        ):
            raise OperatorArchiveInvalid
        approved_raw = _read_file(
            self.approved_fd,
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
        if _names(self.registry_fd, budget) != {registry_name}:
            raise OperatorArchiveInvalid
        registry_raw = _read_file(
            self.registry_fd,
            registry_name,
            uid=uid,
            mode=0o600,
            device=device,
            maximum=MAX_VERIFIER_REGISTRY_BYTES,
            budget=budget,
        )
        high_water_names = _names(self.high_water_fd, budget)
        if not high_water_names or high_water_names != {
            f"{sequence:020d}.json" for sequence in range(1, len(high_water_names) + 1)
        }:
            raise OperatorArchiveInvalid
        history: list[tuple[bytes, bytes]] = []
        checkpoint_names: set[str] = set()
        for sequence in range(1, len(high_water_names) + 1):
            high_water_raw = _read_file(
                self.high_water_fd,
                f"{sequence:020d}.json",
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
                self.checkpoint_fd,
                checkpoint_name,
                uid=uid,
                mode=0o600,
                device=device,
                maximum=MAX_GRANT_CHECKPOINT_BYTES,
                budget=budget,
            )
            history.append((high_water_raw, checkpoint_raw))
        orphan_name = (
            f"sha256-{hashlib.sha256(expected_orphan).hexdigest()}.json" if expected_orphan is not None else None
        )
        if orphan_name in checkpoint_names or _names(self.checkpoint_fd, budget) != checkpoint_names | (
            {orphan_name} if orphan_name is not None else set()
        ):
            raise OperatorArchiveInvalid
        if orphan_name is not None and (
            _read_file(
                self.checkpoint_fd,
                orphan_name,
                uid=uid,
                mode=0o600,
                device=device,
                maximum=MAX_GRANT_CHECKPOINT_BYTES,
                budget=budget,
            )
            != expected_orphan
        ):
            raise OperatorArchiveInvalid
        read_names = _names(self.read_fd, budget)
        sequence = len(history)
        temp_expected = {
            f".high-water.{sequence:020d}.tmp": (history[-1][0], MAX_HOST_RECORD_BYTES),
            f".checkpoint.{sequence:020d}.tmp": (history[-1][1], MAX_GRANT_CHECKPOINT_BYTES),
        }
        public_temps = read_names - _PUBLIC_NAMES
        if (
            not _PUBLIC_NAMES.issubset(read_names)
            or (public_temps and not allow_public_temps)
            or not public_temps <= temp_expected.keys()
        ):
            raise OperatorArchiveInvalid
        for name in sorted(public_temps):
            expected, maximum = temp_expected[name]
            if (
                _read_file(self.read_fd, name, uid=uid, mode=0o644, device=device, maximum=maximum, budget=budget)
                != expected
            ):
                raise OperatorArchiveInvalid
        public = (
            _read_file(
                self.read_fd,
                "approved-deployment.json",
                uid=uid,
                mode=0o644,
                device=device,
                maximum=MAX_HOST_RECORD_BYTES,
                budget=budget,
            ),
            _read_file(
                self.read_fd,
                "governance-verifiers-v1.json",
                uid=uid,
                mode=0o644,
                device=device,
                maximum=MAX_VERIFIER_REGISTRY_BYTES,
                budget=budget,
            ),
            _read_file(
                self.read_fd,
                "high-water.json",
                uid=uid,
                mode=0o644,
                device=device,
                maximum=MAX_HOST_RECORD_BYTES,
                budget=budget,
            ),
            _read_file(
                self.read_fd,
                "grant-checkpoint.json",
                uid=uid,
                mode=0o644,
                device=device,
                maximum=MAX_GRANT_CHECKPOINT_BYTES,
                budget=budget,
            ),
        )
        snapshot = validate_retained_custody_chain(approved_raw, registry_raw, history)
        if require_public_current and public != (approved_raw, registry_raw, *history[-1]):
            raise OperatorArchiveInvalid
        self._assert_stable()
        return _RetainedArchiveState(
            snapshot, approved_raw, registry_raw, tuple(history), public, tuple(sorted(public_temps))
        )

    def note_public_write(self) -> None:
        """Refresh only the read-directory metadata after a completed owned write."""
        self._assert_stable(ignore_read=True)
        before = self.directories[2][1]
        after = os.fstat(self.read_fd)
        if (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_uid,
            before.st_nlink,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_uid,
            after.st_nlink,
        ):
            raise OperatorArchiveInvalid
        self.directories = (*self.directories[:2], (self.read_fd, after), *self.directories[3:])

    def _assert_stable(self, *, ignore_read: bool = False) -> None:
        if any(
            _identity(before) != _identity(os.fstat(fd))
            for index, (fd, before) in enumerate(self.directories)
            if not (ignore_read and index == 2)
        ):
            raise OperatorArchiveInvalid
        lock_after = os.stat(".publisher.lock", dir_fd=self.archive_fd, follow_symlinks=False)
        if _identity(self.lock_before) != _identity(lock_after):
            raise OperatorArchiveInvalid
        with ExitStack() as check_stack:
            _reopened, reopened_info = _open_root(self.root, check_stack, self.uid)
            if _identity(self.directories[0][1]) != _identity(reopened_info):
                raise OperatorArchiveInvalid


@contextmanager
def _locked_archive(root: Path, *, uid: int, limits: ArchiveReadLimits) -> Generator[_LockedArchive]:
    with ExitStack() as stack:
        root_fd, root_before = _open_root(root, stack, uid)
        device = root_before.st_dev
        archive_fd, archive_before = _open_child(root_fd, "archive", stack, uid=uid, mode=0o700, device=device)
        read_fd, read_before = _open_child(root_fd, "read", stack, uid=uid, mode=0o755, device=device)
        lock_fd, lock_before = _open_regular(
            archive_fd, ".publisher.lock", uid=uid, mode=0o600, device=device, maximum=0
        )
        lock = os.fdopen(lock_fd, "rb")
        stack.callback(lock.close)
        portalocker.lock(lock, portalocker.LOCK_EX | portalocker.LOCK_NB)
        stack.callback(portalocker.unlock, lock)
        approved_fd, approved_before = _open_child(archive_fd, "approved", stack, uid=uid, mode=0o700, device=device)
        registry_fd, registry_before = _open_child(archive_fd, "registries", stack, uid=uid, mode=0o700, device=device)
        high_water_fd, high_water_before = _open_child(
            archive_fd, "high-water", stack, uid=uid, mode=0o700, device=device
        )
        checkpoint_fd, checkpoint_before = _open_child(
            archive_fd, "checkpoints", stack, uid=uid, mode=0o700, device=device
        )
        staging_fd, staging_before = _open_child(archive_fd, ".staging", stack, uid=uid, mode=0o700, device=device)
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
        yield _LockedArchive(
            root,
            uid,
            limits,
            device,
            directories,
            archive_fd,
            read_fd,
            approved_fd,
            registry_fd,
            high_water_fd,
            checkpoint_fd,
            staging_fd,
            lock_before,
        )


class OperatorArchiveReader:
    """Read one stable operator archive under its cooperating publisher lock."""

    def __init__(self, root: Path, *, expected_uid: int = 0, limits: ArchiveReadLimits | None = None) -> None:
        self._root = root
        self._uid = expected_uid
        self._limits = limits if limits is not None else ArchiveReadLimits()

    def read(self) -> VerifiedOperatorArchiveV1:
        try:
            with _locked_archive(self._root, uid=self._uid, limits=self._limits) as session:
                return session.read_complete()
        except OperatorArchiveInvalid:
            raise
        except (OSError, ValueError, portalocker.LockException):
            raise OperatorArchiveInvalid from None


__all__ = [
    "ArchiveReadLimits",
    "OperatorArchiveInvalid",
    "OperatorArchiveReader",
    "VerifiedOperatorArchiveV1",
    "classify_public_copies",
]
