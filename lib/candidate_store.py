"""Immutable candidate object storage for atomic master promotion (M7-B, H3-H4).

``prepare_candidate`` writes a temporary file on the same filesystem as its
final destination, flushes, fsyncs, verifies size/digest/media probe, then
performs one immutable rename. Once a candidate exists at ``final_path`` it is
never overwritten: a later ``prepare_candidate`` call for the same identity and
matching digest is an idempotent replay (recovering from a crash after the
rename), and a call with a *different* expected digest against an existing
file is a duplicate-conflict, not a silent overwrite. Any verification failure
quarantines the temp bytes instead of deleting them, so a human/operator can
inspect what a provider or filesystem actually produced.
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
    # The final component itself does not exist yet; resolve its parent chain and
    # re-attach the leaf name so a symlinked ancestor directory is still caught.
    resolved_parent = final_path.parent.resolve()
    resolved = resolved_parent / final_path.name
    if resolved != root and root not in resolved.parents:
        raise CandidateSymlinkEscapeError(f"{final_path} resolves outside media root {media_root}")


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

    if final_path.is_file():
        existing_digest = _sha256_file(final_path)
        if existing_digest != identity.expected_content_digest:
            raise CandidateDuplicateConflictError(f"{final_path} already holds a candidate with a different digest")
        # Idempotent replay: a prior call already completed the rename.
        return VerifiedCandidateObject(
            candidate_id=identity.candidate_id,
            project_name=identity.project_name,
            artifact_key=identity.artifact_key,
            object_ref=str(final_path),
            byte_size=final_path.stat().st_size,
            content_digest=existing_digest,
            media_probe_digest=media_probe(final_path),
        )

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

        os.replace(tmp_path, final_path)
        tmp_path = None
        _fsync_directory(final_path.parent)

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


def _fsync_directory(directory: Path) -> None:
    dir_fd = os.open(str(directory), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


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
