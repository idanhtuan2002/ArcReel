"""Immutable candidate object storage for atomic master promotion (M7-B, H3-H4).

``prepare_candidate`` writes a temporary file on the same filesystem as its
final destination, flushes, fsyncs, verifies size/digest/media probe, then
publishes a hard link without replacing an existing destination. Once a candidate
exists at ``final_path`` it is never overwritten: a later call for the same
identity and matching digest is an idempotent replay (recovering from a crash
after publication), and a different digest is a duplicate conflict. Digest and
media-probe verification failures quarantine the temp bytes for inspection.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from r2.contracts.host_hardening import CandidateIdentity, VerifiedCandidateObject

_HASH_CHUNK_BYTES = 1024 * 1024


class CandidateStoreError(Exception):
    """Base for all candidate-store integrity failures."""


class CandidateDigestMismatchError(CandidateStoreError):
    """The written bytes' digest does not match the candidate's expected digest."""


class CandidateMediaProbeMismatchError(CandidateStoreError):
    """The media probe rejected the written bytes as not valid/matching media."""


class CandidateCrossMountError(CandidateStoreError):
    """The temp file and final path do not share a filesystem; rename would not be atomic."""


class CandidateSymlinkEscapeError(CandidateStoreError):
    """The final path resolves outside the configured media root."""


class CandidateDuplicateConflictError(CandidateStoreError):
    """A different candidate already occupies this final path with unequal bytes."""


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_HASH_CHUNK_BYTES):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def _device_of(path: Path) -> int:
    return path.stat().st_dev


def _reject_symlink_escape(*, final_path: Path, media_root: Path) -> None:
    root = media_root.resolve()
    # Resolve the parent chain and re-attach the leaf name so a symlinked
    # ancestor directory is caught without following the final component.
    resolved_parent = final_path.parent.resolve()
    resolved = resolved_parent / final_path.name
    if resolved != root and root not in resolved.parents:
        raise CandidateSymlinkEscapeError(f"{final_path} resolves outside media root {media_root}")


def _open_parent_under_root(*, final_path: Path, media_root: Path) -> int:
    try:
        relative_parent = final_path.absolute().parent.relative_to(media_root.absolute())
    except ValueError as exc:
        raise CandidateSymlinkEscapeError(f"{final_path} is outside media root {media_root}") from exc
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(media_root.resolve(), flags)
    try:
        for component in relative_parent.parts:
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _assert_parent_anchored(*, descriptor: int, final_path: Path, media_root: Path) -> None:
    try:
        current = _open_parent_under_root(final_path=final_path, media_root=media_root)
    except OSError as exc:
        raise CandidateSymlinkEscapeError(f"{final_path.parent} changed during publication") from exc
    try:
        original_stat = os.fstat(descriptor)
        current_stat = os.fstat(current)
        if (original_stat.st_dev, original_stat.st_ino) != (current_stat.st_dev, current_stat.st_ino):
            raise CandidateSymlinkEscapeError(f"{final_path.parent} changed during publication")
    finally:
        os.close(current)


def _read_existing_candidate(
    *,
    descriptor: int,
    final_path: Path,
    media_root: Path,
    identity: CandidateIdentity,
    media_probe: Callable[[Path], str],
) -> VerifiedCandidateObject:
    _assert_parent_anchored(descriptor=descriptor, final_path=final_path, media_root=media_root)
    try:
        file_fd = os.open(final_path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor)
    except OSError as exc:
        raise CandidateSymlinkEscapeError(f"{final_path} is not an anchored candidate file") from exc
    with os.fdopen(file_fd, "rb") as stream:
        file_stat = os.fstat(stream.fileno())
        hasher = hashlib.sha256()
        while chunk := stream.read(_HASH_CHUNK_BYTES):
            hasher.update(chunk)
    digest = "sha256:" + hasher.hexdigest()
    if digest != identity.expected_content_digest:
        raise CandidateDuplicateConflictError(f"{final_path} already holds a candidate with a different digest")
    probe_digest = media_probe(final_path)
    _assert_parent_anchored(descriptor=descriptor, final_path=final_path, media_root=media_root)
    current_stat = os.stat(final_path.name, dir_fd=descriptor, follow_symlinks=False)
    if (current_stat.st_dev, current_stat.st_ino) != (file_stat.st_dev, file_stat.st_ino):
        raise CandidateSymlinkEscapeError(f"{final_path} changed during candidate verification")
    return VerifiedCandidateObject(
        candidate_id=identity.candidate_id,
        project_name=identity.project_name,
        artifact_key=identity.artifact_key,
        object_ref=str(final_path),
        byte_size=file_stat.st_size,
        content_digest=digest,
        media_probe_digest=probe_digest,
    )


def quarantine(*, path: Path, quarantine_root: Path, reason_code: str) -> Path:
    """Move ``path`` into ``quarantine_root`` under a reason-coded, collision-free name."""

    quarantine_root.mkdir(parents=True, exist_ok=True)
    destination = quarantine_root / f"{int(time.time() * 1_000_000)}.{reason_code}.{path.name}"
    os.replace(path, destination)
    return destination


def prepare_candidate(
    *,
    identity: CandidateIdentity,
    source_file: Path,
    final_path: Path,
    media_root: Path,
    media_probe: Callable[[Path], str],
    quarantine_root: Path | None = None,
    device_of: Callable[[Path], int] = _device_of,
) -> VerifiedCandidateObject:
    final_path = Path(final_path)
    media_root = Path(media_root)
    _reject_symlink_escape(final_path=final_path, media_root=media_root)

    if final_path.is_symlink():
        raise CandidateSymlinkEscapeError(f"{final_path} is a symlink")
    if final_path.is_file():
        try:
            parent_fd = _open_parent_under_root(final_path=final_path, media_root=media_root)
        except OSError as exc:
            raise CandidateSymlinkEscapeError(f"{final_path.parent} is not an anchored media directory") from exc
        try:
            return _read_existing_candidate(
                descriptor=parent_fd,
                final_path=final_path,
                media_root=media_root,
                identity=identity,
                media_probe=media_probe,
            )
        finally:
            os.close(parent_fd)

    final_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=str(final_path.parent),
            prefix=f".{identity.candidate_id}.",
            suffix=".part",
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
            hasher = hashlib.sha256()
            with source_file.open("rb") as source:
                while chunk := source.read(_HASH_CHUNK_BYTES):
                    tmp.write(chunk)
                    hasher.update(chunk)
            tmp.flush()
            os.fsync(tmp.fileno())

        digest = "sha256:" + hasher.hexdigest()
        byte_size = tmp_path.stat().st_size

        if digest != identity.expected_content_digest:
            _quarantine_tmp(tmp_path, quarantine_root, "digest_mismatch")
            tmp_path = None
            raise CandidateDigestMismatchError(
                f"candidate {identity.candidate_id} digest {digest} != expected {identity.expected_content_digest}"
            )

        if device_of(tmp_path) != device_of(final_path.parent):
            _quarantine_tmp(tmp_path, quarantine_root, "cross_mount")
            tmp_path = None
            raise CandidateCrossMountError(
                f"temp file and {final_path.parent} are on different filesystems; rename would not be atomic"
            )

        try:
            media_probe_digest = media_probe(tmp_path)
        except Exception as probe_error:
            _quarantine_tmp(tmp_path, quarantine_root, "media_probe_failed")
            tmp_path = None
            raise CandidateMediaProbeMismatchError(
                f"candidate {identity.candidate_id} failed media probe: {probe_error}"
            ) from probe_error

        try:
            parent_fd = _open_parent_under_root(final_path=final_path, media_root=media_root)
        except OSError as exc:
            raise CandidateSymlinkEscapeError(f"{final_path.parent} is not an anchored media directory") from exc
        linked = False
        published_inode: tuple[int, int] | None = None
        try:
            _assert_parent_anchored(descriptor=parent_fd, final_path=final_path, media_root=media_root)
            temp_stat = os.stat(tmp_path.name, dir_fd=parent_fd, follow_symlinks=False)
            published_inode = (temp_stat.st_dev, temp_stat.st_ino)
            try:
                os.link(tmp_path.name, final_path.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                linked = True
            except FileExistsError:
                return _read_existing_candidate(
                    descriptor=parent_fd,
                    final_path=final_path,
                    media_root=media_root,
                    identity=identity,
                    media_probe=media_probe,
                )
            _assert_parent_anchored(descriptor=parent_fd, final_path=final_path, media_root=media_root)
            os.unlink(tmp_path.name, dir_fd=parent_fd)
            tmp_path = None
            os.fsync(parent_fd)
            _assert_parent_anchored(descriptor=parent_fd, final_path=final_path, media_root=media_root)
        except CandidateSymlinkEscapeError:
            if linked and published_inode is not None:
                try:
                    final_stat = os.stat(final_path.name, dir_fd=parent_fd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    if (final_stat.st_dev, final_stat.st_ino) == published_inode:
                        os.unlink(final_path.name, dir_fd=parent_fd)
            raise
        finally:
            os.close(parent_fd)

        return VerifiedCandidateObject(
            candidate_id=identity.candidate_id,
            project_name=identity.project_name,
            artifact_key=identity.artifact_key,
            object_ref=str(final_path),
            byte_size=byte_size,
            content_digest=digest,
            media_probe_digest=media_probe_digest,
        )
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def _quarantine_tmp(tmp_path: Path, quarantine_root: Path | None, reason_code: str) -> None:
    if quarantine_root is None:
        return
    quarantine(path=tmp_path, quarantine_root=quarantine_root, reason_code=reason_code)


def verify_candidate(
    *, object_ref: Path, expected: VerifiedCandidateObject, media_probe: Callable[[Path], str]
) -> bool:
    """Re-check an already-prepared candidate against its recorded verification.

    Never raises for an ordinary integrity mismatch; returns ``False`` so a
    caller (backup verification, pre-promotion re-check) can decide the
    response (quarantine, alert, refuse promotion) itself.
    """

    object_ref = Path(object_ref)
    if not object_ref.is_file():
        return False
    if object_ref.stat().st_size != expected.byte_size:
        return False
    if _sha256_file(object_ref) != expected.content_digest:
        return False
    try:
        return media_probe(object_ref) == expected.media_probe_digest
    except Exception:
        return False


__all__ = [
    "CandidateCrossMountError",
    "CandidateDigestMismatchError",
    "CandidateDuplicateConflictError",
    "CandidateMediaProbeMismatchError",
    "CandidateStoreError",
    "CandidateSymlinkEscapeError",
    "prepare_candidate",
    "quarantine",
    "verify_candidate",
]
