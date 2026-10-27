"""Probe snapshots bind bounded regular bytes beneath an anchored project root."""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path

import pytest

from r2.quality.errors import OperationalEnvelopeExceededError, RequiredEvidenceMissingError


def inputs():
    try:
        return importlib.import_module("server.services.quality_probe_inputs")
    except ModuleNotFoundError:
        pytest.fail("Anchored probe snapshots are unavailable")


def digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


@pytest.fixture
def media_paths(tmp_path: Path):
    project, scratch = (tmp_path / "project", tmp_path / "scratch")
    project.mkdir(mode=448)
    scratch.mkdir(mode=448)
    source = project / "master.mp4"
    source.write_bytes(b"measured-master")
    return (project, scratch, source)


def test_snapshot_is_readonly_hash_bound_and_removed_after_context(media_paths) -> None:
    project, scratch, source = media_paths
    expected = digest(source.read_bytes())
    with inputs().verified_probe_file(
        project_root=project, object_ref=str(source), expected_digest=expected, directory=scratch
    ) as snapshot:
        path = snapshot.path
        assert path.read_bytes() == b"measured-master"
        assert snapshot.digest == expected
        assert snapshot.size_bytes == len(b"measured-master")
        assert path.stat().st_mode & 511 == 256
        source.write_bytes(b"new-master")
        assert path.read_bytes() == b"measured-master"
    assert not path.exists()
    assert source.read_bytes() == b"new-master"
    assert list(scratch.iterdir()) == []


@pytest.mark.parametrize(
    "case", ["relative", "parent", "foreign", "leaf_symlink", "parent_symlink", "fifo", "directory"]
)
def test_unsafe_or_special_source_is_refused_without_leaving_a_snapshot(media_paths, case: str) -> None:
    import os

    project, scratch, source = media_paths
    outside = project.parent / "outside.mp4"
    outside.write_bytes(b"measured-master")
    if case == "relative":
        ref = "master.mp4"
    elif case == "parent":
        ref = str(project / ".." / "outside.mp4")
    elif case == "foreign":
        ref = str(outside)
    elif case == "leaf_symlink":
        linked = project / "linked.mp4"
        linked.symlink_to(source)
        ref = str(linked)
    elif case == "parent_symlink":
        parent = project / "linked"
        parent.symlink_to(project, target_is_directory=True)
        ref = str(parent / "master.mp4")
    elif case == "fifo":
        fifo = project / "pipe.mp4"
        os.mkfifo(fifo)
        ref = str(fifo)
    else:
        ref = str(project)
    with (
        pytest.raises(RequiredEvidenceMissingError),
        inputs().verified_probe_file(
            project_root=project, object_ref=ref, expected_digest=digest(b"measured-master"), directory=scratch
        ),
    ):
        pytest.fail("unsafe source was admitted")
    assert list(scratch.iterdir()) == []


def test_wrong_hash_and_oversized_input_leave_no_partial_copy(media_paths) -> None:
    project, scratch, source = media_paths
    with (
        pytest.raises(RequiredEvidenceMissingError),
        inputs().verified_probe_file(
            project_root=project, object_ref=str(source), expected_digest=digest(b"wrong"), directory=scratch
        ),
    ):
        pytest.fail("changed bytes admitted")
    with (
        pytest.raises(OperationalEnvelopeExceededError),
        inputs().verified_probe_file(
            project_root=project,
            object_ref=str(source),
            expected_digest=digest(source.read_bytes()),
            directory=scratch,
            max_bytes=3,
        ),
    ):
        pytest.fail("oversized bytes admitted")
    assert list(scratch.iterdir()) == []


def test_snapshot_directory_must_be_private_and_never_a_symlink(media_paths) -> None:
    project, scratch, source = media_paths
    expected = digest(source.read_bytes())
    scratch.chmod(493)
    with (
        pytest.raises(RequiredEvidenceMissingError),
        inputs().verified_probe_file(
            project_root=project, object_ref=str(source), expected_digest=expected, directory=scratch
        ),
    ):
        pytest.fail("nonprivate scratch admitted")
    scratch.chmod(448)
    linked = scratch.parent / "scratch-link"
    linked.symlink_to(scratch, target_is_directory=True)
    with (
        pytest.raises(RequiredEvidenceMissingError),
        inputs().verified_probe_file(
            project_root=project, object_ref=str(source), expected_digest=expected, directory=linked
        ),
    ):
        pytest.fail("symlinked scratch admitted")


def test_file_growing_after_initial_stat_is_stopped_at_the_read_ceiling(media_paths, monkeypatch) -> None:
    import os

    project, scratch, source = media_paths
    original_read = os.read
    identity = source.stat().st_ino
    grew = False

    def growing_read(descriptor: int, count: int) -> bytes:
        nonlocal grew
        chunk = original_read(descriptor, count)
        if chunk and not grew and os.fstat(descriptor).st_ino == identity:
            grew = True
            with source.open("ab") as handle:
                handle.write(b"x" * 32)
        return chunk

    monkeypatch.setattr(os, "read", growing_read)
    with (
        pytest.raises(OperationalEnvelopeExceededError),
        inputs().verified_probe_file(
            project_root=project,
            object_ref=str(source),
            expected_digest=digest(b"measured-master"),
            directory=scratch,
            max_bytes=16,
        ),
    ):
        pytest.fail("growing input was admitted")
    assert grew
    assert list(scratch.iterdir()) == []


def test_source_replaced_mid_copy_never_substitutes_unverified_bytes(media_paths, monkeypatch) -> None:
    import os

    project, scratch, source = media_paths
    original_read = os.read
    identity = source.stat().st_ino
    replaced = False

    def replacing_read(descriptor: int, count: int) -> bytes:
        nonlocal replaced
        chunk = original_read(descriptor, count)
        if chunk and not replaced and os.fstat(descriptor).st_ino == identity:
            replaced = True
            source.unlink()
            source.write_bytes(b"replacement")
        return chunk

    monkeypatch.setattr(os, "read", replacing_read)
    with inputs().verified_probe_file(
        project_root=project, object_ref=str(source), expected_digest=digest(b"measured-master"), directory=scratch
    ) as snapshot:
        assert snapshot.path.read_bytes() == b"measured-master"
    assert replaced
    assert source.read_bytes() == b"replacement"
    assert list(scratch.iterdir()) == []


async def test_existing_verified_snapshot_and_new_snapshot_match_on_the_same_bytes(media_paths) -> None:
    from server.services.format_render import verified_snapshot

    project, scratch, source = media_paths
    expected = digest(source.read_bytes())
    legacy_directory = scratch.parent / "legacy"
    async with verified_snapshot(source, expected, legacy_directory) as legacy:
        legacy_bytes = legacy.read_bytes()
    assert not legacy.exists()
    with inputs().verified_probe_file(
        project_root=project, object_ref=str(source), expected_digest=expected, directory=scratch
    ) as current:
        assert current.path.read_bytes() == legacy_bytes
        assert current.digest == expected
