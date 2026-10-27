"""Private bounded byte snapshots; callers own authenticated master and locator resolution."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import stat
import tempfile
import uuid
from collections.abc import AsyncGenerator, Generator
from contextlib import ExitStack, asynccontextmanager, contextmanager
from dataclasses import dataclass
from pathlib import Path

from r2.quality.errors import (
    OperationalEnvelopeExceededError,
    ReferenceInvalidError,
    RequiredEvidenceMissingError,
)
from r2.quality.ports import ProbeRequest
from r2.quality.probes import ProbeCatalog, ProbeConfig

MAX_MEDIA_BYTES = 67108864
MAX_COMBINED_BYTES = 134217728
MAX_CAPTION_BYTES = 262144


@dataclass(frozen=True)
class ProbeFile:
    path: Path
    digest: str
    size_bytes: int


def _directory_fd(path: Path) -> int:
    if not path.is_absolute() or any(part in {".", ".."} for part in path.parts):
        raise RequiredEvidenceMissingError()
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open("/", flags)
    try:
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _unlink_owned(directory_fd: int, name: str, identity: tuple[int, int]) -> None:
    try:
        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (info.st_dev, info.st_ino) == identity:
            os.unlink(name, dir_fd=directory_fd)
    except FileNotFoundError:
        return
    except OSError:
        raise RequiredEvidenceMissingError() from None


def _write_all(descriptor: int, chunk: bytes) -> None:
    remaining = memoryview(chunk)
    while remaining:
        count = os.write(descriptor, remaining)
        if count <= 0:
            raise RequiredEvidenceMissingError()
        remaining = remaining[count:]


@contextmanager
def verified_probe_file(
    *, project_root: Path, object_ref: str, expected_digest: str, directory: Path, max_bytes: int = 67108864
) -> Generator[ProbeFile, None, None]:
    """Yield an immutable private copy of exact bytes, without granting source-read authority."""
    with ExitStack() as stack:
        try:
            if type(max_bytes) is not int or not 0 < max_bytes <= 67108864:
                raise OperationalEnvelopeExceededError()
            if type(object_ref) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", expected_digest) is None:
                raise RequiredEvidenceMissingError()
            if not object_ref.startswith("/") or any(part in {"", ".", ".."} for part in object_ref.split("/")[1:]):
                raise RequiredEvidenceMissingError()
            source = Path(object_ref)
            relative = source.relative_to(project_root)
            if not relative.parts:
                raise RequiredEvidenceMissingError()
            parent = _directory_fd(project_root)
            stack.callback(os.close, parent)
            for part in relative.parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
                stack.callback(os.close, child)
                parent = child
            source_fd = os.open(
                relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent
            )
            stack.callback(os.close, source_fd)
            observed = os.fstat(source_fd)
            if not stat.S_ISREG(observed.st_mode):
                raise RequiredEvidenceMissingError()
            if observed.st_size > max_bytes:
                raise OperationalEnvelopeExceededError()
            destination_fd = _directory_fd(directory)
            stack.callback(os.close, destination_fd)
            directory_info = os.fstat(destination_fd)
            if directory_info.st_uid != os.geteuid() or stat.S_IMODE(directory_info.st_mode) != 0o700:
                raise RequiredEvidenceMissingError()
            name = "m10-probe-" + uuid.uuid4().hex
            output_fd = os.open(
                name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=destination_fd
            )
            stack.callback(os.close, output_fd)
            output_info = os.fstat(output_fd)
            stack.callback(_unlink_owned, destination_fd, name, (output_info.st_dev, output_info.st_ino))
            digest = hashlib.sha256()
            size = 0
            while chunk := os.read(source_fd, min(65536, max_bytes - size + 1)):
                size += len(chunk)
                if size > max_bytes:
                    raise OperationalEnvelopeExceededError()
                digest.update(chunk)
                _write_all(output_fd, chunk)
            actual_digest = "sha256:" + digest.hexdigest()
            if actual_digest != expected_digest:
                raise RequiredEvidenceMissingError()
            os.fchmod(output_fd, 0o400)
            current = _directory_fd(directory)
            stack.callback(os.close, current)
            current_info = os.fstat(current)
            if (current_info.st_dev, current_info.st_ino) != (directory_info.st_dev, directory_info.st_ino):
                raise RequiredEvidenceMissingError()
            snapshot = ProbeFile(directory / name, actual_digest, size)
        except (OSError, ValueError, TypeError, AttributeError):
            raise RequiredEvidenceMissingError() from None
        yield snapshot


@dataclass(frozen=True)
class ProbeInputs:
    """Supervisor-private copied bytes of one admitted recipe, ordered as measurement input identities."""

    config: ProbeConfig
    target: ProbeFile
    caption: ProbeFile | None
    reference: ProbeFile | None

    @property
    def input_digests(self) -> tuple[str, ...]:
        companion = self.caption or self.reference
        return (self.target.digest,) if companion is None else (self.target.digest, companion.digest)


@asynccontextmanager
async def snapshot_probe_inputs(
    request: ProbeRequest, *, project_root: Path, catalog: ProbeCatalog
) -> AsyncGenerator[ProbeInputs, None]:
    """Copy the request root and its catalog-scoped companion; callers must first prove root authority."""
    config = catalog.resolve(request)
    binding = catalog.input_binding(request, config)
    directory = Path(tempfile.mkdtemp(prefix="m10-probe-"))
    with ExitStack() as stack:
        stack.callback(os.rmdir, directory)
        root = request.subject.master_binding.root
        target = await asyncio.to_thread(
            stack.enter_context,
            verified_probe_file(
                project_root=project_root,
                object_ref=root.object_ref,
                expected_digest=request.subject.artifact_digest,
                directory=directory,
                max_bytes=MAX_MEDIA_BYTES,
            ),
        )
        caption = reference = None
        if binding is not None:
            is_caption = binding.role == "CAPTION"
            limit = min(
                MAX_CAPTION_BYTES if is_caption else MAX_MEDIA_BYTES,
                MAX_COMBINED_BYTES - target.size_bytes,
            )
            try:
                companion = await asyncio.to_thread(
                    stack.enter_context,
                    verified_probe_file(
                        project_root=project_root,
                        object_ref=str(project_root / binding.relative_path),
                        expected_digest=binding.content_digest,
                        directory=directory,
                        max_bytes=limit,
                    ),
                )
            except RequiredEvidenceMissingError:
                if is_caption:
                    raise
                raise ReferenceInvalidError() from None
            caption, reference = (companion, None) if is_caption else (None, companion)
        yield ProbeInputs(config, target, caption, reference)
