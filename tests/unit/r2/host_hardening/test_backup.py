"""Pure-logic backup-set guards that need neither PostgreSQL nor real media:
source/target aliasing, path-escape rejection, and empty-target checks."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from r2.contracts.host_hardening import BackupSetManifest, BackupSetState, MediaInventoryEntry
from r2.host_hardening.backup import (
    NonEmptyRestoreTargetError,
    PathEscapesMediaRootError,
    SourceTargetAliasError,
    _assert_target_is_empty,
    _paths_alias,
    _restore_media,
    _under_root,
    _verify_restored_media,
    restore_backup_set,
)


def _manifest(*, media_ref: str = "video.mp4", dump_ref: str = "database.dump") -> BackupSetManifest:
    return BackupSetManifest(
        backup_set_id="set-1",
        source_deployment_id="source-1",
        release_git_sha="deadbeef",
        release_image_digest="sha256:image",
        postgres_version="18",
        alembic_head="head-1",
        database_backup_ref=dump_ref,
        recovery_target="2026-09-25T00:00:00Z",
        configuration_digest="sha256:config",
        media=(
            MediaInventoryEntry(
                project_name="demo",
                artifact_key="video-1",
                object_ref=media_ref,
                object_version="candidate-1",
                byte_size=5,
                content_digest="sha256:content",
            ),
        ),
        state=BackupSetState.COMPLETE,
    )


class _UnexpectedDatabase:
    async def execute(self, _statement: object) -> None:
        raise AssertionError("database access preceded manifest path validation")


def test_identical_paths_alias() -> None:
    assert _paths_alias(Path("/a/b"), Path("/a/b"))


def test_a_path_nested_under_the_other_aliases() -> None:
    assert _paths_alias(Path("/a/b"), Path("/a/b/c"))
    assert _paths_alias(Path("/a/b/c"), Path("/a/b"))


def test_disjoint_paths_do_not_alias() -> None:
    assert not _paths_alias(Path("/a/b"), Path("/a/c"))


def test_under_root_accepts_a_nested_path() -> None:
    root = Path("/data/media")
    assert _under_root(root / "videos" / "x.mp4", root) == (root / "videos" / "x.mp4").resolve()


def test_under_root_rejects_a_path_escaping_the_root() -> None:
    with pytest.raises(PathEscapesMediaRootError):
        _under_root(Path("/etc/passwd"), Path("/data/media"))


def test_under_root_rejects_traversal_that_resolves_outside(tmp_path: Path) -> None:
    root = tmp_path / "media"
    root.mkdir()
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"x")
    with pytest.raises(PathEscapesMediaRootError):
        _under_root(root / ".." / "outside.mp4", root)


def test_assert_target_is_empty_accepts_a_missing_directory(tmp_path: Path) -> None:
    _assert_target_is_empty(tmp_path / "does-not-exist-yet")


def test_assert_target_is_empty_accepts_an_empty_directory(tmp_path: Path) -> None:
    target = tmp_path / "empty"
    target.mkdir()
    _assert_target_is_empty(target)


def test_assert_target_is_empty_rejects_a_directory_with_files(tmp_path: Path) -> None:
    target = tmp_path / "occupied"
    target.mkdir()
    (target / "leftover.mp4").write_bytes(b"x")
    with pytest.raises(NonEmptyRestoreTargetError):
        _assert_target_is_empty(target)


def test_source_target_alias_error_is_a_backup_set_error() -> None:
    from r2.host_hardening.backup import BackupSetError

    assert issubclass(SourceTargetAliasError, BackupSetError)


def test_restore_media_rejects_parent_ref_before_writing_outside_target(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backup"
    (backup_dir / "media").mkdir(parents=True)
    (backup_dir / "outside.mp4").write_bytes(b"owned")
    outside_target = tmp_path / "outside.mp4"
    outside_target.write_bytes(b"safe")

    with pytest.raises(PathEscapesMediaRootError):
        _restore_media(
            _manifest(media_ref="../outside.mp4"), backup_dir=backup_dir, target_media_root=tmp_path / "target"
        )

    assert outside_target.read_bytes() == b"safe"


def test_restore_media_rejects_symlink_even_within_backup_root(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backup"
    media_dir = backup_dir / "media"
    media_dir.mkdir(parents=True)
    (media_dir / "actual.mp4").write_bytes(b"owned")
    (media_dir / "link.mp4").symlink_to(media_dir / "actual.mp4")
    target_media_root = tmp_path / "target"

    with pytest.raises(PathEscapesMediaRootError):
        _restore_media(_manifest(media_ref="link.mp4"), backup_dir=backup_dir, target_media_root=target_media_root)

    assert not target_media_root.exists()


def test_verify_media_does_not_read_outside_restore_root(tmp_path: Path) -> None:
    media_root = tmp_path / "target"
    media_root.mkdir()
    (tmp_path / "outside.mp4").write_bytes(b"owned")

    with pytest.raises(PathEscapesMediaRootError):
        _verify_restored_media(_manifest(media_ref="../outside.mp4"), media_root=media_root)


@pytest.mark.parametrize(
    ("dump_ref", "media_ref"),
    [
        ("../outside.dump", "video.mp4"),
        ("/outside.dump", "video.mp4"),
        ("database.dump", "../outside.mp4"),
        ("database.dump", "/outside.mp4"),
    ],
)
async def test_restore_rejects_manifest_escape_before_database_access(
    tmp_path: Path, dump_ref: str, media_ref: str
) -> None:
    target_media_root = tmp_path / "target"
    with pytest.raises(PathEscapesMediaRootError):
        await restore_backup_set(
            manifest=_manifest(media_ref=media_ref, dump_ref=dump_ref),
            backup_dir=tmp_path / "backup",
            target_database_url="postgresql://unused",
            target_session=cast(AsyncSession, _UnexpectedDatabase()),
            target_media_root=target_media_root,
        )
    assert not target_media_root.exists()


async def test_restore_rejects_symlink_target_with_empty_media_inventory(tmp_path: Path) -> None:
    actual_target = tmp_path / "actual-target"
    actual_target.mkdir()
    target_media_root = tmp_path / "target"
    target_media_root.symlink_to(actual_target, target_is_directory=True)
    empty_manifest = _manifest().model_copy(update={"media": ()})

    with pytest.raises(PathEscapesMediaRootError):
        await restore_backup_set(
            manifest=empty_manifest,
            backup_dir=tmp_path / "backup",
            target_database_url="postgresql://unused",
            target_session=cast(AsyncSession, _UnexpectedDatabase()),
            target_media_root=target_media_root,
        )
    assert target_media_root.is_symlink()
    assert not any(actual_target.iterdir())
