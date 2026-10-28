"""Deterministic M10-B export archive builder (stdlib only, so it can run as the confined export worker).

The archive is ZIP_STORED with every ZipInfo field fixed: sorted bytewise ASCII member paths, 1980-01-01
timestamps, Unix create system, mode 0o100644, no extra fields, comments, directories, links or ZIP64. Each
member's bytes are hashed while they are copied and must equal the manifest digest and size.
"""

from __future__ import annotations

import hashlib
import os
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)
MEMBER_MODE = 0o100644
MAX_ARCHIVE_BYTES = 2**31 - 1
_CHUNK = 1 << 20


class ExportBuildError(Exception):
    """A member does not match its declared bytes, or the archive would leave the fixed envelope."""


@dataclass(frozen=True)
class BundleMember:
    path: str
    source: Path
    content_digest: str
    byte_size: int


def _info(path: str, size: int) -> zipfile.ZipInfo:
    if not path.isascii() or path.startswith("/") or path.endswith("/") or ".." in path.split("/"):
        raise ExportBuildError("member paths are relative ASCII files")
    info = zipfile.ZipInfo(path, date_time=ZIP_EPOCH)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.create_version = 20
    info.extract_version = 20
    info.flag_bits = 0
    info.external_attr = MEMBER_MODE << 16
    info.extra = b""
    info.comment = b""
    info.file_size = size
    return info


def build_archive(destination: Path, members: Sequence[BundleMember], manifest: bytes) -> str:
    """Write the archive to a new ``destination`` file, fsync it and return its sha256 digest.

    ``manifest`` is written as ``manifest.json``; members are written in bytewise path order. Any mismatch between
    copied bytes and a member's declared digest or size raises and leaves no complete archive.
    """
    entries = sorted(
        [*((m.path, m) for m in members), ("manifest.json", None)], key=lambda item: item[0].encode("utf-8")
    )
    if len({path for path, _ in entries}) != len(entries):
        raise ExportBuildError("duplicate member path")
    if sum(m.byte_size for m in members) + len(manifest) > MAX_ARCHIVE_BYTES:
        raise ExportBuildError("archive exceeds the fixed envelope")
    descriptor = os.open(destination, os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "w+b") as handle:
        with zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
            archive.comment = b""
            for path, member in entries:
                if member is None:
                    with archive.open(_info(path, len(manifest)), "w", force_zip64=False) as stream:
                        stream.write(manifest)
                    continue
                _copy_member(archive, path, member)
        handle.flush()
        os.fsync(handle.fileno())
        handle.seek(0)
        digest = hashlib.sha256()
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _copy_member(archive: zipfile.ZipFile, path: str, member: BundleMember) -> None:
    digest = hashlib.sha256()
    size = 0
    with (
        member.source.open("rb") as source,
        archive.open(_info(path, member.byte_size), "w", force_zip64=False) as stream,
    ):
        while chunk := source.read(min(_CHUNK, member.byte_size + 1 - size)):
            size += len(chunk)
            if size > member.byte_size:
                raise ExportBuildError(f"{path}: more bytes than declared")
            digest.update(chunk)
            stream.write(chunk)
    if (size, "sha256:" + digest.hexdigest()) != (member.byte_size, member.content_digest):
        raise ExportBuildError(f"{path}: bytes differ from the manifest")


__all__ = ["MAX_ARCHIVE_BYTES", "MEMBER_MODE", "ZIP_EPOCH", "BundleMember", "ExportBuildError", "build_archive"]
