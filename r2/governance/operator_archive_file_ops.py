"""Descriptor-relative create-only file publication for an operator archive."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable

from r2.governance.operator_archive_reader import _FILE_FLAGS, OperatorArchiveInvalid, _identity, _open_regular


class ArchivePublicationInvalid(ValueError):
    """The requested archive file cannot be safely published."""

    def __init__(self) -> None:
        super().__init__("operator Governance archive publication is unavailable")


def _single_name(name: str) -> bool:
    return type(name) is str and bool(name) and name not in {".", ".."} and "/" not in name and "\x00" not in name


def _directory(fd: int, *, expected_uid: int) -> os.stat_result:
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != expected_uid or stat.S_IMODE(info.st_mode) != 0o700:
        raise ArchivePublicationInvalid
    return info


def publish_retained_file(
    *,
    staging_fd: int,
    final_fd: int,
    staging_name: str,
    final_name: str,
    raw: bytes,
    maximum: int,
    expected_uid: int,
    after_phase: Callable[[str], None] | None = None,
) -> None:
    """Create one immutable name from exact bytes under an already-held archive lock.

    An interruption preserves the last filesystem state for locked reconciliation.
    This byte operation does not validate Governance records or database authority.
    """

    if (
        not _single_name(staging_name)
        or not _single_name(final_name)
        or type(raw) is not bytes
        or type(maximum) is not int
        or not 0 < maximum <= 64 * 1024 * 1024
        or not 0 < len(raw) <= maximum
        or type(expected_uid) is not int
        or expected_uid < 0
        or not all(hasattr(os, flag) for flag in ("O_NOFOLLOW", "O_CLOEXEC", "O_EXCL"))
        or os.open not in os.supports_dir_fd
        or os.link not in os.supports_dir_fd
        or os.link not in os.supports_follow_symlinks
        or os.unlink not in os.supports_dir_fd
    ):
        raise ArchivePublicationInvalid
    try:
        staging_info = _directory(staging_fd, expected_uid=expected_uid)
        final_info = _directory(final_fd, expected_uid=expected_uid)
        if staging_info.st_dev != final_info.st_dev or staging_info.st_ino == final_info.st_ino:
            raise ArchivePublicationInvalid
        fd = os.open(
            staging_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=staging_fd,
        )
        try:
            os.fchmod(fd, 0o600)
            remaining = memoryview(raw)
            while remaining:
                written = os.write(fd, remaining)
                if written <= 0:
                    raise ArchivePublicationInvalid
                remaining = remaining[written:]
            if after_phase is not None:
                after_phase("file_written")
            os.fsync(fd)
            if after_phase is not None:
                after_phase("file_fsync")
        finally:
            os.close(fd)
        os.fsync(staging_fd)
        if after_phase is not None:
            after_phase("staging_fsync")
        os.link(staging_name, final_name, src_dir_fd=staging_fd, dst_dir_fd=final_fd, follow_symlinks=False)
        if after_phase is not None:
            after_phase("link_created")
        os.fsync(final_fd)
        if after_phase is not None:
            after_phase("link_fsync")
        os.unlink(staging_name, dir_fd=staging_fd)
        if after_phase is not None:
            after_phase("stage_unlinked")
        os.fsync(staging_fd)
        if after_phase is not None:
            after_phase("unlink_fsync")
    except ArchivePublicationInvalid:
        raise
    except OSError:
        raise ArchivePublicationInvalid from None


def remove_linked_staging_if_exact(
    *,
    staging_fd: int,
    final_fd: int,
    staging_name: str,
    final_name: str,
    raw: bytes,
    maximum: int,
    expected_uid: int,
) -> None:
    """Finish an interrupted create-only link after exact inode and byte checks."""

    if (
        not _single_name(staging_name)
        or not _single_name(final_name)
        or type(raw) is not bytes
        or type(maximum) is not int
        or not 0 < len(raw) <= maximum <= 64 * 1024 * 1024
        or type(expected_uid) is not int
        or expected_uid < 0
        or os.unlink not in os.supports_dir_fd
    ):
        raise ArchivePublicationInvalid
    try:
        staging_info = _directory(staging_fd, expected_uid=expected_uid)
        final_info = _directory(final_fd, expected_uid=expected_uid)
        if staging_info.st_dev != final_info.st_dev or staging_info.st_ino == final_info.st_ino:
            raise ArchivePublicationInvalid
        staged_path = os.stat(staging_name, dir_fd=staging_fd, follow_symlinks=False)
        final_path = os.stat(final_name, dir_fd=final_fd, follow_symlinks=False)
        staged_file = os.open(staging_name, _FILE_FLAGS, dir_fd=staging_fd)
        try:
            final_file = os.open(final_name, _FILE_FLAGS, dir_fd=final_fd)
            try:
                before = os.fstat(staged_file)
                if (
                    not stat.S_ISREG(before.st_mode)
                    or before.st_uid != expected_uid
                    or stat.S_IMODE(before.st_mode) != 0o600
                    or before.st_dev != staging_info.st_dev
                    or before.st_nlink != 2
                    or before.st_size != len(raw)
                    or _identity(staged_path) != _identity(before)
                    or _identity(final_path) != _identity(before)
                    or _identity(os.fstat(final_file)) != _identity(before)
                ):
                    raise ArchivePublicationInvalid
                data = bytearray()
                while chunk := os.read(staged_file, min(65_536, maximum + 1 - len(data))):
                    data.extend(chunk)
                    if len(data) > maximum:
                        raise ArchivePublicationInvalid
                if (
                    bytes(data) != raw
                    or _identity(os.fstat(staged_file)) != _identity(before)
                    or _identity(os.fstat(final_file)) != _identity(before)
                    or _identity(os.stat(staging_name, dir_fd=staging_fd, follow_symlinks=False)) != _identity(before)
                    or _identity(os.stat(final_name, dir_fd=final_fd, follow_symlinks=False)) != _identity(before)
                ):
                    raise ArchivePublicationInvalid
                os.fsync(staged_file)
                os.fsync(final_fd)
                os.unlink(staging_name, dir_fd=staging_fd)
            finally:
                os.close(final_file)
        finally:
            os.close(staged_file)
        os.fsync(staging_fd)
    except ArchivePublicationInvalid:
        raise
    except OSError:
        raise ArchivePublicationInvalid from None


def remove_staged_file_if_exact(
    *,
    staging_fd: int,
    final_fd: int,
    staging_name: str,
    final_name: str,
    raw: bytes,
    maximum: int,
    expected_uid: int,
) -> None:
    """Discard one exact unlinked temporary before restarting create-only publication."""

    if (
        not _single_name(staging_name)
        or not _single_name(final_name)
        or type(raw) is not bytes
        or type(maximum) is not int
        or not 0 < len(raw) <= maximum <= 64 * 1024 * 1024
        or type(expected_uid) is not int
        or expected_uid < 0
        or os.unlink not in os.supports_dir_fd
        or os.stat not in os.supports_dir_fd
        or os.stat not in os.supports_follow_symlinks
    ):
        raise ArchivePublicationInvalid
    try:
        staging_info = _directory(staging_fd, expected_uid=expected_uid)
        final_info = _directory(final_fd, expected_uid=expected_uid)
        if staging_info.st_dev != final_info.st_dev or staging_info.st_ino == final_info.st_ino:
            raise ArchivePublicationInvalid
        try:
            os.stat(final_name, dir_fd=final_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ArchivePublicationInvalid
        staged_path = os.stat(staging_name, dir_fd=staging_fd, follow_symlinks=False)
        fd, before = _open_regular(
            staging_fd, staging_name, uid=expected_uid, mode=0o600, device=staging_info.st_dev, maximum=maximum
        )
        try:
            data = bytearray()
            while chunk := os.read(fd, min(65_536, maximum + 1 - len(data))):
                data.extend(chunk)
                if len(data) > maximum:
                    raise ArchivePublicationInvalid
            if (
                bytes(data) != raw
                or before.st_nlink != 1
                or _identity(before) != _identity(staged_path)
                or _identity(before) != _identity(os.fstat(fd))
                or _identity(before) != _identity(os.stat(staging_name, dir_fd=staging_fd, follow_symlinks=False))
            ):
                raise ArchivePublicationInvalid
            try:
                os.stat(final_name, dir_fd=final_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise ArchivePublicationInvalid
            os.unlink(staging_name, dir_fd=staging_fd)
        finally:
            os.close(fd)
        os.fsync(staging_fd)
    except ArchivePublicationInvalid:
        raise
    except (OSError, OperatorArchiveInvalid):
        raise ArchivePublicationInvalid from None


def replace_public_file(
    *,
    read_fd: int,
    temp_name: str,
    public_name: str,
    raw: bytes,
    maximum: int,
    expected_uid: int,
    after_phase: Callable[[str], None] | None = None,
) -> None:
    """Replace one permitted public copy from a same-directory fsynced temporary."""

    if (
        not _single_name(temp_name)
        or public_name not in {"high-water.json", "grant-checkpoint.json"}
        or temp_name == public_name
        or type(raw) is not bytes
        or type(maximum) is not int
        or not 0 < maximum <= 64 * 1024 * 1024
        or not 0 < len(raw) <= maximum
        or type(expected_uid) is not int
        or expected_uid < 0
        or not all(hasattr(os, flag) for flag in ("O_NOFOLLOW", "O_CLOEXEC", "O_EXCL"))
        or os.open not in os.supports_dir_fd
        or os.rename not in os.supports_dir_fd
    ):
        raise ArchivePublicationInvalid
    try:
        info = os.fstat(read_fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != expected_uid or stat.S_IMODE(info.st_mode) != 0o755:
            raise ArchivePublicationInvalid
        old_fd, _old_info = _open_regular(
            read_fd, public_name, uid=expected_uid, mode=0o644, device=info.st_dev, maximum=maximum
        )
        os.close(old_fd)
        temp_fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o644,
            dir_fd=read_fd,
        )
        try:
            os.fchmod(temp_fd, 0o644)
            remaining = memoryview(raw)
            while remaining:
                written = os.write(temp_fd, remaining)
                if written <= 0:
                    raise ArchivePublicationInvalid
                remaining = remaining[written:]
            if after_phase is not None:
                after_phase("file_written")
            os.fsync(temp_fd)
            if after_phase is not None:
                after_phase("file_fsync")
        finally:
            os.close(temp_fd)
        os.replace(temp_name, public_name, src_dir_fd=read_fd, dst_dir_fd=read_fd)
        if after_phase is not None:
            after_phase("renamed")
        os.fsync(read_fd)
        if after_phase is not None:
            after_phase("directory_fsync")
    except ArchivePublicationInvalid:
        raise
    except (OSError, OperatorArchiveInvalid):
        raise ArchivePublicationInvalid from None


def remove_public_temp_if_exact(
    *, read_fd: int, temp_name: str, expected: bytes, maximum: int, expected_uid: int
) -> None:
    """Remove a previously verified public temporary after checking its current bytes and inode."""

    if (
        not _single_name(temp_name)
        or type(expected) is not bytes
        or type(maximum) is not int
        or not 0 < len(expected) <= maximum <= 64 * 1024 * 1024
        or type(expected_uid) is not int
        or expected_uid < 0
        or os.unlink not in os.supports_dir_fd
    ):
        raise ArchivePublicationInvalid
    try:
        info = os.fstat(read_fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != expected_uid or stat.S_IMODE(info.st_mode) != 0o755:
            raise ArchivePublicationInvalid
        fd, before = _open_regular(
            read_fd, temp_name, uid=expected_uid, mode=0o644, device=info.st_dev, maximum=maximum
        )
        try:
            data = bytearray()
            while chunk := os.read(fd, min(65_536, maximum + 1 - len(data))):
                data.extend(chunk)
                if len(data) > maximum:
                    raise ArchivePublicationInvalid
            if bytes(data) != expected or _identity(before) != _identity(os.fstat(fd)):
                raise ArchivePublicationInvalid
            observed = os.stat(temp_name, dir_fd=read_fd, follow_symlinks=False)
            if _identity(before) != _identity(observed):
                raise ArchivePublicationInvalid
            os.unlink(temp_name, dir_fd=read_fd)
        finally:
            os.close(fd)
        os.fsync(read_fd)
    except ArchivePublicationInvalid:
        raise
    except (OSError, OperatorArchiveInvalid):
        raise ArchivePublicationInvalid from None


__all__ = [
    "ArchivePublicationInvalid",
    "publish_retained_file",
    "remove_linked_staging_if_exact",
    "remove_public_temp_if_exact",
    "replace_public_file",
]
