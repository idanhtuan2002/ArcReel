"""Immutable candidate object storage: fault-injection coverage for M7-B H3-H4.

Candidate bytes must become immutable and verified before any promotion
authority ever sees them. Every fault below must leave the destination
untouched (no partial/incorrect file at ``final_path``) and never silently
succeed.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from lib.candidate_store import (
    CandidateCrossMountError,
    CandidateDigestMismatchError,
    CandidateDuplicateConflictError,
    CandidateMediaProbeMismatchError,
    CandidateSymlinkEscapeError,
    prepare_candidate,
    quarantine,
    verify_candidate,
)
from r2.contracts.host_hardening import CandidateIdentity

_CONTENT = b"paid-master-bytes"
_DIGEST = "sha256:" + __import__("hashlib").sha256(_CONTENT).hexdigest()
_OTHER_DIGEST = "sha256:" + __import__("hashlib").sha256(b"different-bytes").hexdigest()


def _identity(**overrides: object) -> CandidateIdentity:
    defaults: dict[str, object] = {
        "candidate_id": "cand-1",
        "user_id": "u1",
        "project_name": "demo",
        "artifact_key": "videos/E1S01",
        "expected_content_digest": _DIGEST,
    }
    defaults.update(overrides)
    return CandidateIdentity(**defaults)


def _source(tmp_path: Path, content: bytes = _CONTENT) -> Path:
    source = tmp_path / "source.mp4"
    source.write_bytes(content)
    return source


def _probe_ok(_path: Path) -> str:
    return "sha256:" + "c" * 64


def test_prepare_candidate_verifies_and_publishes_into_place(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    final_path = media_root / "demo" / "videos" / "cand-1.mp4"

    result = prepare_candidate(
        identity=_identity(),
        source_file=_source(tmp_path),
        final_path=final_path,
        media_root=media_root,
        media_probe=_probe_ok,
    )

    assert final_path.is_file()
    assert final_path.read_bytes() == _CONTENT
    assert result.content_digest == _DIGEST
    assert result.byte_size == len(_CONTENT)
    assert result.object_ref == str(final_path)
    assert result.media_probe_digest == "sha256:" + "c" * 64
    # no leftover temp file
    assert list(final_path.parent.iterdir()) == [final_path]


def test_prepare_candidate_rejects_digest_mismatch_and_quarantines(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    final_path = media_root / "demo" / "videos" / "cand-1.mp4"
    quarantine_root = tmp_path / "quarantine"

    with pytest.raises(CandidateDigestMismatchError):
        prepare_candidate(
            identity=_identity(expected_content_digest=_OTHER_DIGEST),
            source_file=_source(tmp_path),
            final_path=final_path,
            media_root=media_root,
            media_probe=_probe_ok,
            quarantine_root=quarantine_root,
        )

    assert not final_path.exists()
    assert not final_path.parent.exists() or list(final_path.parent.iterdir()) == []
    quarantined = list(quarantine_root.iterdir())
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == _CONTENT


def test_prepare_candidate_rejects_media_probe_failure_and_quarantines(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    final_path = media_root / "demo" / "videos" / "cand-1.mp4"
    quarantine_root = tmp_path / "quarantine"

    def _probe_raises(_path: Path) -> str:
        raise ValueError("not a valid container")

    with pytest.raises(CandidateMediaProbeMismatchError):
        prepare_candidate(
            identity=_identity(),
            source_file=_source(tmp_path),
            final_path=final_path,
            media_root=media_root,
            media_probe=_probe_raises,
            quarantine_root=quarantine_root,
        )

    assert not final_path.exists()
    assert len(list(quarantine_root.iterdir())) == 1


def test_prepare_candidate_surfaces_disk_full_and_leaves_no_final_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    final_path = media_root / "demo" / "videos" / "cand-1.mp4"

    def _fsync_enospc(_fd: int) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "fsync", _fsync_enospc)

    with pytest.raises(OSError, match="No space left on device"):
        prepare_candidate(
            identity=_identity(),
            source_file=_source(tmp_path),
            final_path=final_path,
            media_root=media_root,
            media_probe=_probe_ok,
        )

    assert not final_path.exists()
    assert not final_path.parent.exists() or list(final_path.parent.iterdir()) == []


def test_prepare_candidate_rejects_cross_mount_publication(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    final_path = media_root / "demo" / "videos" / "cand-1.mp4"
    calls = {"n": 0}

    def _fake_device_of(_path: Path) -> int:
        calls["n"] += 1
        # First call probes the temp file's device, second probes the destination
        # directory's device; report them as different to force the guard.
        return calls["n"]

    with pytest.raises(CandidateCrossMountError):
        prepare_candidate(
            identity=_identity(),
            source_file=_source(tmp_path),
            final_path=final_path,
            media_root=media_root,
            media_probe=_probe_ok,
            device_of=_fake_device_of,
        )

    assert not final_path.exists()


def test_prepare_candidate_rejects_symlink_escape_outside_media_root(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    escape_link = media_root / "escape"
    escape_link.symlink_to(outside, target_is_directory=True)
    final_path = escape_link / "cand-1.mp4"

    with pytest.raises(CandidateSymlinkEscapeError):
        prepare_candidate(
            identity=_identity(),
            source_file=_source(tmp_path),
            final_path=final_path,
            media_root=media_root,
            media_probe=_probe_ok,
        )

    assert not (outside / "cand-1.mp4").exists()


def test_prepare_candidate_rejects_duplicate_unequal_bytes_without_touching_existing(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    final_path = media_root / "demo" / "videos" / "cand-1.mp4"
    final_path.parent.mkdir(parents=True)
    final_path.write_bytes(b"already-stored-different-bytes")

    with pytest.raises(CandidateDuplicateConflictError):
        prepare_candidate(
            identity=_identity(),
            source_file=_source(tmp_path),
            final_path=final_path,
            media_root=media_root,
            media_probe=_probe_ok,
        )

    assert final_path.read_bytes() == b"already-stored-different-bytes"


def test_prepare_candidate_preserves_destination_created_after_precheck(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    final_path = media_root / "demo" / "videos" / "cand-1.mp4"
    source = _source(tmp_path)

    def competing_device_probe(path: Path) -> int:
        if path == final_path.parent:
            final_path.write_bytes(b"competing-writer-bytes")
        return path.stat().st_dev

    with pytest.raises(CandidateDuplicateConflictError):
        prepare_candidate(
            identity=_identity(),
            source_file=source,
            final_path=final_path,
            media_root=media_root,
            media_probe=_probe_ok,
            device_of=competing_device_probe,
        )

    assert final_path.read_bytes() == b"competing-writer-bytes"


def test_prepare_candidate_rejects_existing_final_symlink(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    final_path = media_root / "demo" / "videos" / "cand-1.mp4"
    final_path.parent.mkdir(parents=True)
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(_CONTENT)
    final_path.symlink_to(outside)

    with pytest.raises(CandidateSymlinkEscapeError):
        prepare_candidate(
            identity=_identity(),
            source_file=_source(tmp_path),
            final_path=final_path,
            media_root=media_root,
            media_probe=_probe_ok,
        )

    assert final_path.is_symlink()
    assert outside.read_bytes() == _CONTENT


def test_prepare_candidate_rejects_parent_replaced_during_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    final_path = media_root / "demo" / "videos" / "cand-1.mp4"
    moved_parent = tmp_path / "moved-videos"
    real_link = os.link

    def move_parent_after_link(src: str | os.PathLike[str], dst: str | os.PathLike[str], **kwargs: object) -> None:
        real_link(src, dst, **kwargs)
        final_path.parent.rename(moved_parent)
        final_path.parent.symlink_to(moved_parent, target_is_directory=True)

    monkeypatch.setattr(os, "link", move_parent_after_link)
    with pytest.raises(CandidateSymlinkEscapeError):
        prepare_candidate(
            identity=_identity(),
            source_file=_source(tmp_path),
            final_path=final_path,
            media_root=media_root,
            media_probe=_probe_ok,
        )
    assert not (moved_parent / final_path.name).exists()


def test_parent_swap_cleanup_preserves_replacement_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    final_path = media_root / "demo" / "videos" / "cand-1.mp4"
    moved_parent = tmp_path / "moved-videos"
    real_link = os.link

    def replace_after_link(src: str | os.PathLike[str], dst: str | os.PathLike[str], **kwargs: object) -> None:
        real_link(src, dst, **kwargs)
        final_path.unlink()
        final_path.write_bytes(b"competitor")
        final_path.parent.rename(moved_parent)
        final_path.parent.symlink_to(moved_parent, target_is_directory=True)

    monkeypatch.setattr(os, "link", replace_after_link)
    with pytest.raises(CandidateSymlinkEscapeError):
        prepare_candidate(
            identity=_identity(),
            source_file=_source(tmp_path),
            final_path=final_path,
            media_root=media_root,
            media_probe=_probe_ok,
        )
    assert (moved_parent / final_path.name).read_bytes() == b"competitor"


def test_prepare_candidate_is_idempotent_after_kill_following_publication(tmp_path: Path) -> None:
    # Models a crash after immutable publication already succeeded but before the
    # caller recorded success: a fresh call with the same identity must return the
    # same verified object rather than re-writing or raising a duplicate conflict.
    media_root = tmp_path / "media"
    media_root.mkdir()
    final_path = media_root / "demo" / "videos" / "cand-1.mp4"

    first = prepare_candidate(
        identity=_identity(),
        source_file=_source(tmp_path),
        final_path=final_path,
        media_root=media_root,
        media_probe=_probe_ok,
    )

    second = prepare_candidate(
        identity=_identity(),
        source_file=_source(tmp_path, content=_CONTENT),
        final_path=final_path,
        media_root=media_root,
        media_probe=_probe_ok,
    )

    assert second == first
    assert final_path.read_bytes() == _CONTENT


def test_verify_candidate_detects_on_disk_corruption(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    final_path = media_root / "demo" / "videos" / "cand-1.mp4"

    verified = prepare_candidate(
        identity=_identity(),
        source_file=_source(tmp_path),
        final_path=final_path,
        media_root=media_root,
        media_probe=_probe_ok,
    )

    assert verify_candidate(object_ref=final_path, expected=verified, media_probe=_probe_ok) is True

    final_path.write_bytes(b"corrupted-after-the-fact")
    assert verify_candidate(object_ref=final_path, expected=verified, media_probe=_probe_ok) is False


def test_verify_candidate_false_when_object_missing(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    final_path = media_root / "demo" / "videos" / "cand-1.mp4"

    verified = prepare_candidate(
        identity=_identity(),
        source_file=_source(tmp_path),
        final_path=final_path,
        media_root=media_root,
        media_probe=_probe_ok,
    )
    final_path.unlink()

    assert verify_candidate(object_ref=final_path, expected=verified, media_probe=_probe_ok) is False


def test_quarantine_moves_the_file_with_a_reason_coded_name(tmp_path: Path) -> None:
    source = tmp_path / "bad.mp4"
    source.write_bytes(b"quarantine-me")
    quarantine_root = tmp_path / "quarantine"

    destination = quarantine(path=source, quarantine_root=quarantine_root, reason_code="digest_mismatch")

    assert not source.exists()
    assert destination.is_file()
    assert destination.read_bytes() == b"quarantine-me"
    assert "digest_mismatch" in destination.name
