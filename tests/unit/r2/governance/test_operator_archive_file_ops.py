"""Create-only retained files preserve exact bytes across interrupted publication."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from r2.governance.operator_archive_file_ops import (
    ArchivePublicationInvalid,
    publish_retained_file,
    remove_linked_staging_if_exact,
    remove_staged_file_if_exact,
    replace_public_file,
)


def _directories(tmp_path: Path) -> tuple[Path, Path, int, int]:
    staging = tmp_path / "staging"
    final = tmp_path / "final"
    staging.mkdir(mode=0o700)
    final.mkdir(mode=0o700)
    staging_fd = os.open(staging, os.O_RDONLY | os.O_DIRECTORY)
    final_fd = os.open(final, os.O_RDONLY | os.O_DIRECTORY)
    return staging, final, staging_fd, final_fd


def test_publish_retained_file_creates_one_durable_exact_name(tmp_path: Path) -> None:
    staging, final, staging_fd, final_fd = _directories(tmp_path)
    phases: list[str] = []
    try:
        publish_retained_file(
            staging_fd=staging_fd,
            final_fd=final_fd,
            staging_name="candidate.tmp",
            final_name="00000000000000000002.json",
            raw=b"exact candidate bytes",
            maximum=8192,
            expected_uid=os.getuid(),
            after_phase=phases.append,
        )
    finally:
        os.close(staging_fd)
        os.close(final_fd)
    assert phases == [
        "file_written",
        "file_fsync",
        "staging_fsync",
        "link_created",
        "link_fsync",
        "stage_unlinked",
        "unlink_fsync",
    ]
    assert list(staging.iterdir()) == []
    target = final / "00000000000000000002.json"
    assert target.read_bytes() == b"exact candidate bytes"
    assert target.stat().st_nlink == 1
    assert target.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "phase",
    ["file_written", "file_fsync", "staging_fsync", "link_created", "link_fsync", "stage_unlinked", "unlink_fsync"],
)
def test_interrupted_publish_preserves_recoverable_or_quarantined_bytes(tmp_path: Path, phase: str) -> None:
    staging, final, staging_fd, final_fd = _directories(tmp_path)

    def interrupt(current: str) -> None:
        if current == phase:
            raise RuntimeError("simulated interruption")

    try:
        with pytest.raises(RuntimeError, match="simulated interruption"):
            publish_retained_file(
                staging_fd=staging_fd,
                final_fd=final_fd,
                staging_name="candidate.tmp",
                final_name="00000000000000000002.json",
                raw=b"exact candidate bytes",
                maximum=8192,
                expected_uid=os.getuid(),
                after_phase=interrupt,
            )
    finally:
        os.close(staging_fd)
        os.close(final_fd)
    staged = staging / "candidate.tmp"
    target = final / "00000000000000000002.json"
    if phase not in {"stage_unlinked", "unlink_fsync"}:
        assert staged.read_bytes() == b"exact candidate bytes"
    else:
        assert not staged.exists()
    if phase in {"file_written", "file_fsync", "staging_fsync"}:
        assert not target.exists()
    else:
        assert target.read_bytes() == b"exact candidate bytes"
        assert target.stat().st_nlink == (2 if phase in {"link_created", "link_fsync"} else 1)


@pytest.mark.parametrize("fault", ["match", "wrong_bytes", "separate_inode", "extra_link", "wrong_mode"])
def test_linked_staging_cleanup_requires_exact_candidate_inode(tmp_path: Path, fault: str) -> None:
    staging, final, staging_fd, final_fd = _directories(tmp_path)
    staged = staging / "candidate.tmp"
    target = final / "00000000000000000002.json"
    staged.write_bytes(b"exact candidate bytes")
    staged.chmod(0o600)
    if fault == "separate_inode":
        target.write_bytes(b"exact candidate bytes")
        target.chmod(0o600)
    else:
        os.link(staged, target)
    if fault == "extra_link":
        os.link(staged, staging / "unexpected")
    if fault == "wrong_mode":
        staged.chmod(0o644)
    try:
        if fault == "match":
            remove_linked_staging_if_exact(
                staging_fd=staging_fd,
                final_fd=final_fd,
                staging_name=staged.name,
                final_name=target.name,
                raw=b"exact candidate bytes",
                maximum=8192,
                expected_uid=os.getuid(),
            )
        else:
            with pytest.raises(ArchivePublicationInvalid):
                remove_linked_staging_if_exact(
                    staging_fd=staging_fd,
                    final_fd=final_fd,
                    staging_name=staged.name,
                    final_name=target.name,
                    raw=b"different bytes" if fault == "wrong_bytes" else b"exact candidate bytes",
                    maximum=8192,
                    expected_uid=os.getuid(),
                )
    finally:
        os.close(staging_fd)
        os.close(final_fd)
    assert staged.exists() == (fault != "match")
    assert target.read_bytes() == b"exact candidate bytes"
    assert target.stat().st_nlink == (1 if fault in {"match", "separate_inode"} else 3 if fault == "extra_link" else 2)


def test_linked_staging_cleanup_completes_actual_interrupted_publication(tmp_path: Path) -> None:
    staging, final, staging_fd, final_fd = _directories(tmp_path)

    def interrupt(phase: str) -> None:
        if phase == "link_created":
            raise RuntimeError("interrupted")

    try:
        with pytest.raises(RuntimeError, match="interrupted"):
            publish_retained_file(
                staging_fd=staging_fd,
                final_fd=final_fd,
                staging_name="candidate.tmp",
                final_name="00000000000000000002.json",
                raw=b"exact candidate bytes",
                maximum=8192,
                expected_uid=os.getuid(),
                after_phase=interrupt,
            )
        assert (staging / "candidate.tmp").stat().st_nlink == 2
        remove_linked_staging_if_exact(
            staging_fd=staging_fd,
            final_fd=final_fd,
            staging_name="candidate.tmp",
            final_name="00000000000000000002.json",
            raw=b"exact candidate bytes",
            maximum=8192,
            expected_uid=os.getuid(),
        )
    finally:
        os.close(staging_fd)
        os.close(final_fd)
    assert list(staging.iterdir()) == []
    assert (final / "00000000000000000002.json").stat().st_nlink == 1


@pytest.mark.parametrize("fault", ["match", "wrong_bytes", "extra_link", "wrong_mode", "final_exists"])
def test_staged_file_cleanup_requires_exact_unlinked_candidate(tmp_path: Path, fault: str) -> None:
    staging, final, staging_fd, final_fd = _directories(tmp_path)
    staged = staging / "candidate.tmp"
    staged.write_bytes(b"exact candidate bytes")
    staged.chmod(0o600)
    if fault == "extra_link":
        os.link(staged, staging / "unexpected")
    elif fault == "wrong_mode":
        staged.chmod(0o644)
    elif fault == "final_exists":
        (final / "candidate.json").write_bytes(b"existing")
    try:
        if fault == "match":
            remove_staged_file_if_exact(
                staging_fd=staging_fd,
                final_fd=final_fd,
                staging_name=staged.name,
                final_name="candidate.json",
                raw=b"exact candidate bytes",
                maximum=8192,
                expected_uid=os.getuid(),
            )
        else:
            with pytest.raises(ArchivePublicationInvalid):
                remove_staged_file_if_exact(
                    staging_fd=staging_fd,
                    final_fd=final_fd,
                    staging_name=staged.name,
                    final_name="candidate.json",
                    raw=b"different bytes" if fault == "wrong_bytes" else b"exact candidate bytes",
                    maximum=8192,
                    expected_uid=os.getuid(),
                )
    finally:
        os.close(staging_fd)
        os.close(final_fd)
    assert staged.exists() == (fault != "match")


@pytest.mark.parametrize("old_raw", [b"prior different bytes", b"new candidate bytes"])
def test_create_only_collision_never_overwrites_existing_record(tmp_path: Path, old_raw: bytes) -> None:
    staging, final, staging_fd, final_fd = _directories(tmp_path)
    target = final / "00000000000000000002.json"
    target.write_bytes(old_raw)
    try:
        with pytest.raises(ArchivePublicationInvalid):
            publish_retained_file(
                staging_fd=staging_fd,
                final_fd=final_fd,
                staging_name="candidate.tmp",
                final_name=target.name,
                raw=b"new candidate bytes",
                maximum=8192,
                expected_uid=os.getuid(),
            )
    finally:
        os.close(staging_fd)
        os.close(final_fd)
    assert target.read_bytes() == old_raw
    assert (staging / "candidate.tmp").read_bytes() == b"new candidate bytes"


@pytest.mark.parametrize("name", ["", ".", "..", "../outside", "nested/name", "bad\x00name"])
def test_invalid_names_cannot_escape_dirfd(tmp_path: Path, name: str) -> None:
    staging, final, staging_fd, final_fd = _directories(tmp_path)
    try:
        with pytest.raises(ArchivePublicationInvalid):
            publish_retained_file(
                staging_fd=staging_fd,
                final_fd=final_fd,
                staging_name=name,
                final_name="00000000000000000002.json",
                raw=b"bytes",
                maximum=8192,
                expected_uid=os.getuid(),
            )
    finally:
        os.close(staging_fd)
        os.close(final_fd)
    assert list(staging.iterdir()) == []
    assert list(final.iterdir()) == []


@pytest.mark.parametrize("fault", ["wrong_uid", "wrong_mode"])
def test_unowned_or_writable_directory_denies_before_file_creation(tmp_path: Path, fault: str) -> None:
    staging, final, staging_fd, final_fd = _directories(tmp_path)
    expected_uid = os.getuid()
    if fault == "wrong_uid":
        expected_uid += 1
    else:
        final.chmod(0o777)
    try:
        with pytest.raises(ArchivePublicationInvalid):
            publish_retained_file(
                staging_fd=staging_fd,
                final_fd=final_fd,
                staging_name="candidate.tmp",
                final_name="00000000000000000002.json",
                raw=b"bytes",
                maximum=8192,
                expected_uid=expected_uid,
            )
    finally:
        os.close(staging_fd)
        os.close(final_fd)
    assert list(staging.iterdir()) == []
    assert list(final.iterdir()) == []


@pytest.mark.parametrize("occupied", ["staging_symlink", "final_symlink"])
def test_existing_link_cannot_be_overwritten(tmp_path: Path, occupied: str) -> None:
    staging, final, staging_fd, final_fd = _directories(tmp_path)
    outside = tmp_path / "outside"
    outside.write_bytes(b"outside bytes")
    if occupied == "staging_symlink":
        (staging / "candidate.tmp").symlink_to(outside)
    else:
        (final / "00000000000000000002.json").symlink_to(outside)
    try:
        with pytest.raises(ArchivePublicationInvalid):
            publish_retained_file(
                staging_fd=staging_fd,
                final_fd=final_fd,
                staging_name="candidate.tmp",
                final_name="00000000000000000002.json",
                raw=b"candidate bytes",
                maximum=8192,
                expected_uid=os.getuid(),
            )
    finally:
        os.close(staging_fd)
        os.close(final_fd)
    assert outside.read_bytes() == b"outside bytes"
    assert (staging / "candidate.tmp").is_symlink() == (occupied == "staging_symlink")
    assert (final / "00000000000000000002.json").is_symlink() == (occupied == "final_symlink")


def test_replace_public_file_fsyncs_exact_new_copy(tmp_path: Path) -> None:
    read = tmp_path / "read"
    read.mkdir(mode=0o755)
    target = read / "high-water.json"
    target.write_bytes(b"old")
    target.chmod(0o644)
    phases: list[str] = []
    read_fd = os.open(read, os.O_RDONLY | os.O_DIRECTORY)
    try:
        replace_public_file(
            read_fd=read_fd,
            temp_name=".high-water.candidate.tmp",
            public_name="high-water.json",
            raw=b"new exact bytes",
            maximum=8192,
            expected_uid=os.getuid(),
            after_phase=phases.append,
        )
    finally:
        os.close(read_fd)
    assert phases == ["file_written", "file_fsync", "renamed", "directory_fsync"]
    assert target.read_bytes() == b"new exact bytes"
    assert target.stat().st_mode & 0o777 == 0o644
    assert {path.name for path in read.iterdir()} == {"high-water.json"}


@pytest.mark.parametrize("phase", ["file_written", "file_fsync", "renamed", "directory_fsync"])
def test_interrupted_public_replace_exposes_old_or_new_copy(tmp_path: Path, phase: str) -> None:
    read = tmp_path / "read"
    read.mkdir(mode=0o755)
    target = read / "grant-checkpoint.json"
    target.write_bytes(b"old")
    target.chmod(0o644)

    def interrupt(current: str) -> None:
        if current == phase:
            raise RuntimeError("simulated interruption")

    read_fd = os.open(read, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(RuntimeError, match="simulated interruption"):
            replace_public_file(
                read_fd=read_fd,
                temp_name=".checkpoint.candidate.tmp",
                public_name="grant-checkpoint.json",
                raw=b"new exact bytes",
                maximum=8192,
                expected_uid=os.getuid(),
                after_phase=interrupt,
            )
    finally:
        os.close(read_fd)
    assert target.read_bytes() == (b"old" if phase in {"file_written", "file_fsync"} else b"new exact bytes")
    assert (read / ".checkpoint.candidate.tmp").exists() == (phase in {"file_written", "file_fsync"})


@pytest.mark.parametrize("fault", ["unknown_public", "symlink_target", "wrong_mode"])
def test_public_replace_denies_unapproved_or_unsafe_target(tmp_path: Path, fault: str) -> None:
    read = tmp_path / "read"
    read.mkdir(mode=0o755)
    target = read / ("other.json" if fault == "unknown_public" else "high-water.json")
    outside = tmp_path / "outside"
    outside.write_bytes(b"outside")
    if fault == "symlink_target":
        target.symlink_to(outside)
    else:
        target.write_bytes(b"old")
        target.chmod(0o666 if fault == "wrong_mode" else 0o644)
    read_fd = os.open(read, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(ArchivePublicationInvalid):
            replace_public_file(
                read_fd=read_fd,
                temp_name=".candidate.tmp",
                public_name=target.name,
                raw=b"new",
                maximum=8192,
                expected_uid=os.getuid(),
            )
    finally:
        os.close(read_fd)
    assert outside.read_bytes() == b"outside"
    assert not (read / ".candidate.tmp").exists()
