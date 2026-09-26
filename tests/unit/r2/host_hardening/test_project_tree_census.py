"""Physical H6 tree census preserves bytes and rejects unsafe entries."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from r2.host_hardening.project_tree_census import CensusError, CensusLimits, scan_project_tree


def _limits(**overrides: int) -> CensusLimits:
    values = {"max_files": 10, "max_entries": 20, "max_file_bytes": 100, "max_total_bytes": 200, "max_depth": 5}
    values.update(overrides)
    return CensusLimits(**values)


def test_census_keeps_hidden_lock_named_and_empty_directory(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / ".claude").mkdir(parents=True)
    (root / "empty").mkdir()
    (root / ".claude" / "CLAUDE.md").write_bytes(b"abc")
    (root / ".project.json.lock").write_bytes(b"")

    result = scan_project_tree(root, limits=_limits())

    assert tuple(item.relative_path for item in result.directories) == ("", ".claude", "empty")
    assert [(item.relative_path, item.byte_size, item.content_digest) for item in result.files] == [
        (".claude/CLAUDE.md", 3, "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"),
        (".project.json.lock", 0, "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
    ]
    assert result.total_bytes == 3


@pytest.mark.parametrize("position", ["root", "directory", "file"])
def test_census_rejects_symlinks_without_following_them(tmp_path: Path, position: str) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "file.txt").write_bytes(b"secret")
    root = tmp_path / "project"
    if position == "root":
        root.symlink_to(real, target_is_directory=True)
    else:
        root.mkdir()
        if position == "directory":
            (root / "alias").symlink_to(real, target_is_directory=True)
        else:
            (root / ".project.json.lock").symlink_to(real / "file.txt")

    with pytest.raises(CensusError) as error:
        scan_project_tree(root, limits=_limits())

    assert error.value.code in {"ROOT_INVALID", "ENTRY_UNSUPPORTED"}
    assert "secret" not in str(error.value)


def test_census_rejects_fifo_without_opening_it(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    os.mkfifo(root / "pipe")

    with pytest.raises(CensusError) as error:
        scan_project_tree(root, limits=_limits())

    assert error.value.code == "ENTRY_UNSUPPORTED"


@pytest.mark.parametrize(
    ("files", "limit_overrides"),
    [
        ([b"abc"], {"max_file_bytes": 2}),
        ([b"abc", b"def"], {"max_files": 1}),
        ([b"abc", b"def"], {"max_total_bytes": 5}),
    ],
)
def test_census_rejects_bounds_instead_of_truncating(
    tmp_path: Path, files: list[bytes], limit_overrides: dict[str, int]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    for index, data in enumerate(files):
        (root / f"{index}.bin").write_bytes(data)

    with pytest.raises(CensusError) as error:
        scan_project_tree(root, limits=_limits(**limit_overrides))

    assert error.value.code == "LIMIT_EXCEEDED"


def test_census_rejects_depth_limit(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / "one" / "two").mkdir(parents=True)

    with pytest.raises(CensusError) as error:
        scan_project_tree(root, limits=_limits(max_depth=1))

    assert error.value.code == "LIMIT_EXCEEDED"


def test_census_rejects_many_empty_directories(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "one").mkdir()
    (root / "two").mkdir()

    with pytest.raises(CensusError) as error:
        scan_project_tree(root, limits=_limits(max_entries=2))

    assert error.value.code == "LIMIT_EXCEEDED"


def test_census_rejects_missing_root(tmp_path: Path) -> None:
    with pytest.raises(CensusError) as error:
        scan_project_tree(tmp_path / "missing", limits=_limits())

    assert error.value.code == "ROOT_INVALID"


def test_census_rejects_nul_root_with_sanitized_error(tmp_path: Path) -> None:
    with pytest.raises(CensusError) as error:
        scan_project_tree(tmp_path / "project\x00secret", limits=_limits())

    assert error.value.code == "ROOT_INVALID"
    assert "secret" not in str(error.value)
