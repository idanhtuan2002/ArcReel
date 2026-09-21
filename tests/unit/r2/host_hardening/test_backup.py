"""Pure-logic backup-set guards that need neither PostgreSQL nor real media:
source/target aliasing, path-escape rejection, and empty-target checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from r2.host_hardening.backup import (
    NonEmptyRestoreTargetError,
    PathEscapesMediaRootError,
    SourceTargetAliasError,
    _assert_target_is_empty,
    _paths_alias,
    _under_root,
)


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
