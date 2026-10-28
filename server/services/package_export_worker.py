"""Deterministic M10-B export archive builder and its confined worker entry (stdlib only).

The archive is ZIP_STORED with every ZipInfo field fixed: sorted bytewise member paths in the lowercase
normalized export grammar, 1980-01-01 timestamps, Unix create system, mode 0o100644, no extra fields, comments,
directories, links or ZIP64. Each member's bytes are hashed while they are copied and must equal the manifest
digest and size. As a worker (``main``) it runs in an owned transient unit, confines itself with the A4 probe
worker's verified envelope, seccomp/no-new-privileges check and Landlock (read-only snapshots, one precreated
output inode, no network), then writes the archive into that output and reports its digest.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)
MEMBER_MODE = 0o100644
ZIP64_LIMIT = (1 << 31) - 1
#: zipfile refuses a member whose size times 1.05 exceeds the ZIP64 limit when ZIP64 is disabled.
MAX_MEMBER_BYTES = int(ZIP64_LIMIT / 1.05)
MAX_ARCHIVE_BYTES = ZIP64_LIMIT
MANIFEST_PATH = "manifest.json"
EXPORT_PATH = re.compile(r"^[a-z0-9._-]+(/[a-z0-9._-]+)*$")
WORKER_CONFIG_SCHEMA = "m10.export-worker-config.v1"
WORKER_OUTPUT_SCHEMA = "m10.export-worker-output.v1"
_CHUNK = 1 << 20
_LOCAL_HEADER = 30
_CENTRAL_HEADER = 46
_END_RECORD = 22


class ExportBuildError(Exception):
    """A member does not match its declared bytes, or the archive would leave the fixed envelope."""


class ExportEnvelopeError(ExportBuildError):
    """The archive would exceed the fixed size envelope (no ZIP64)."""


@dataclass(frozen=True)
class BundleMember:
    path: str
    source: Path
    content_digest: str
    byte_size: int


def validate_path(path: str) -> None:
    """The frozen archive path grammar: relative, normalized, lowercase ASCII, no dot segments."""
    if "\x00" in path or EXPORT_PATH.fullmatch(path) is None or any(part in {".", ".."} for part in path.split("/")):
        raise ExportBuildError("member paths follow the lowercase normalized export grammar")


def archive_size(paths_and_sizes: Sequence[tuple[str, int]], manifest_size: int) -> int:
    """The exact archive byte size for these members plus the manifest; raises outside the fixed envelope."""
    entries = [*paths_and_sizes, (MANIFEST_PATH, manifest_size)]
    total = _END_RECORD
    for path, size in entries:
        if size > MAX_MEMBER_BYTES:
            raise ExportEnvelopeError("a member exceeds the no-ZIP64 envelope")
        name = len(path.encode("ascii"))
        total += _LOCAL_HEADER + name + size + _CENTRAL_HEADER + name
    if total > MAX_ARCHIVE_BYTES or len(entries) > 0xFFFF:
        raise ExportEnvelopeError("the archive exceeds the no-ZIP64 envelope")
    return total


def _entries(members: Sequence[BundleMember]) -> list[tuple[str, BundleMember | None]]:
    for member in members:
        validate_path(member.path)
        if member.path == MANIFEST_PATH:
            raise ExportBuildError("manifest.json is written by the builder")
    pending: list[tuple[str, BundleMember | None]] = [(m.path, m) for m in members]
    pending.append((MANIFEST_PATH, None))
    entries = sorted(pending, key=lambda item: item[0].encode())
    if len({path.casefold() for path, _ in entries}) != len(entries):
        raise ExportBuildError("duplicate or case-colliding member path")
    return entries


def _info(path: str, size: int) -> zipfile.ZipInfo:
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


type Opener = Callable[[BundleMember], BinaryIO]


def _open_source(member: BundleMember) -> BinaryIO:
    return member.source.open("rb")


def write_archive(
    handle: BinaryIO, members: Sequence[BundleMember], manifest: bytes, opener: Opener = _open_source
) -> str:
    """Write the archive into an empty, seekable ``handle``, fsync it and return its sha256 digest."""
    entries = _entries(members)
    archive_size([(m.path, m.byte_size) for m in members], len(manifest))
    with zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
        archive.comment = b""
        for path, member in entries:
            if member is None:
                with archive.open(_info(path, len(manifest)), "w", force_zip64=False) as stream:
                    stream.write(manifest)
                continue
            _copy_member(archive, path, member, opener)
    handle.flush()
    os.fsync(handle.fileno())
    handle.seek(0)
    digest = hashlib.sha256()
    for chunk in iter(lambda: handle.read(_CHUNK), b""):
        digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def build_archive(destination: Path, members: Sequence[BundleMember], manifest: bytes) -> str:
    """Write the archive to a new ``destination`` file (never overwritten) and return its digest."""
    _entries(members)
    descriptor = os.open(destination, os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "w+b") as handle:
        return write_archive(handle, members, manifest)


def _copy_member(archive: zipfile.ZipFile, path: str, member: BundleMember, opener: Opener) -> None:
    digest = hashlib.sha256()
    size = 0
    with (
        opener(member) as source,
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


def _confinement():
    """The A4 probe worker module, loaded by path next to this file (both are stdlib-only)."""
    path = Path(__file__).with_name("quality_probe_worker.py")
    spec = importlib.util.spec_from_file_location("m10_probe_worker_confinement", path)
    if spec is None or spec.loader is None:
        raise ExportBuildError("ISOLATION_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _emit(body: dict[str, object]) -> None:
    sys.stdout.buffer.write(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    sys.stdout.buffer.flush()


def worker_digests() -> dict[str, str]:
    """The exact bytes of this worker and the confinement module it loads."""
    here = Path(__file__)
    return {
        name: "sha256:" + hashlib.sha256((here.parent / name).read_bytes()).hexdigest()
        for name in ("package_export_worker.py", "quality_probe_worker.py")
    }


def _pinned(path: str, identity: object, flags: int) -> int:
    """Open ``path`` without following a final link and require it to be exactly the host's regular inode."""
    if type(identity) is not list or len(identity) != 2 or not all(type(item) is int for item in identity):
        raise ExportBuildError("CONFIG_INVALID")
    descriptor = os.open(path, flags | os.O_NOFOLLOW | os.O_CLOEXEC)
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or [info.st_dev, info.st_ino] != identity:
        os.close(descriptor)
        raise ExportBuildError("IDENTITY_MISMATCH")
    return descriptor


def main() -> int:
    """Confined worker: read the host config from stdin, confine, build into the pinned output inode, report.

    Every input and the output are reopened after confinement and must be the exact inodes the host created, so a
    swapped path can neither redirect a read nor a write.
    """
    devnull = os.open("/dev/null", os.O_WRONLY | os.O_CLOEXEC)
    os.dup2(devnull, 2)
    os.close(devnull)
    body: dict[str, object] = {"schema": WORKER_OUTPUT_SCHEMA, "status": "WORKER_FAILED", "digest": None}
    try:
        body["worker"] = worker_digests()
        config = json.loads(sys.stdin.buffer.read(1 << 20))
        if type(config) is not dict or config.get("schema") != WORKER_CONFIG_SCHEMA:
            raise ExportBuildError("CONFIG_INVALID")
        probe = _confinement()
        confinement = probe.confine(config)
        body.update(envelope=confinement.envelope, landlock_abi=confinement.landlock_abi)
        sources: dict[str, int] = {}
        members: list[BundleMember] = []
        for item in config["members"]:
            member = BundleMember(str(item["path"]), Path(str(item["source"])), str(item["digest"]), int(item["size"]))
            sources[member.path] = _pinned(str(member.source), item["identity"], os.O_RDONLY)
            members.append(member)
        manifest_fd = _pinned(str(config["manifest"]), config["manifest_identity"], os.O_RDONLY)
        with os.fdopen(manifest_fd, "rb") as handle:
            manifest = handle.read(1 << 20)
        output = _pinned(str(config["output"]), config["output_identity"], os.O_RDWR)

        def opener(member: BundleMember) -> BinaryIO:
            return os.fdopen(sources.pop(member.path), "rb", buffering=0)

        with os.fdopen(output, "w+b") as handle:
            if os.fstat(handle.fileno()).st_size != 0:
                raise ExportBuildError("OUTPUT_NOT_EMPTY")
            body.update(status="OK", digest=write_archive(handle, members, manifest, opener))
    except ExportEnvelopeError:
        body.update(status="ENVELOPE_EXCEEDED")
    except ExportBuildError:
        body.update(status="INTEGRITY_FAILED")
    except Exception:
        body.update(status="WORKER_FAILED")
    _emit(body)
    return 0 if body["status"] == "OK" else 1


__all__ = [
    "MANIFEST_PATH",
    "MAX_ARCHIVE_BYTES",
    "MAX_MEMBER_BYTES",
    "MEMBER_MODE",
    "WORKER_CONFIG_SCHEMA",
    "WORKER_OUTPUT_SCHEMA",
    "ZIP_EPOCH",
    "BundleMember",
    "ExportBuildError",
    "ExportEnvelopeError",
    "archive_size",
    "build_archive",
    "main",
    "validate_path",
    "worker_digests",
    "write_archive",
]
