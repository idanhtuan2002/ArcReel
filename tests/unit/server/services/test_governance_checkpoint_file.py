"""Checkpoint byte loading observes complete pathname replacements and fails closed."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from r2.contracts.grant_checkpoint import MAX_GRANT_CHECKPOINT_BYTES
from server.services.governance_checkpoint_file import CheckpointFileUnavailable, GovernanceCheckpointFile

_PUBLIC_FILES = (
    "approved-deployment.json",
    "governance-verifiers-v1.json",
    "high-water.json",
    "grant-checkpoint.json",
)


@pytest.mark.asyncio
async def test_public_loader_reads_exact_four_complete_files(tmp_path: Path) -> None:
    os.chmod(tmp_path, 0o755)
    for index, name in enumerate(_PUBLIC_FILES):
        path = tmp_path / name
        path.write_bytes(f"copy-{index}".encode())
        path.chmod(0o644)
    loader = GovernanceCheckpointFile(tmp_path, expected_uid=os.getuid(), expected_gid=os.getgid())
    assert await loader.load_public_copies() == (b"copy-0", b"copy-1", b"copy-2", b"copy-3")


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["missing", "symlink", "fifo", "extra", "oversized"])
async def test_public_loader_rejects_incomplete_or_unexpected_set(tmp_path: Path, state: str) -> None:
    os.chmod(tmp_path, 0o755)
    for name in _PUBLIC_FILES:
        path = tmp_path / name
        path.write_bytes(b"valid")
        path.chmod(0o644)
    target = tmp_path / _PUBLIC_FILES[1]
    if state == "missing":
        target.unlink()
    elif state == "symlink":
        target.unlink()
        target.symlink_to(tmp_path / _PUBLIC_FILES[0])
    elif state == "fifo":
        target.unlink()
        os.mkfifo(target)
    elif state == "extra":
        (tmp_path / "unexpected").write_bytes(b"x")
    elif state == "oversized":
        target.write_bytes(b"x" * (MAX_GRANT_CHECKPOINT_BYTES + 1))
    with pytest.raises(CheckpointFileUnavailable) as exc:
        await GovernanceCheckpointFile(
            tmp_path, expected_uid=os.getuid(), expected_gid=os.getgid()
        ).load_public_copies()
    assert str(tmp_path) not in str(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["wrong_owner", "wrong_directory_mode", "wrong_file_mode", "hardlink"])
async def test_public_loader_rejects_missing_host_custody(tmp_path: Path, state: str) -> None:
    os.chmod(tmp_path, 0o755)
    for name in _PUBLIC_FILES:
        path = tmp_path / name
        path.write_bytes(b"valid")
        path.chmod(0o644)
    expected_uid = os.getuid()
    if state == "wrong_owner":
        expected_uid += 1
    elif state == "wrong_directory_mode":
        os.chmod(tmp_path, 0o777)
    elif state == "wrong_file_mode":
        (tmp_path / _PUBLIC_FILES[0]).chmod(0o666)
    elif state == "hardlink":
        os.link(tmp_path / _PUBLIC_FILES[0], tmp_path.parent / f"{tmp_path.name}-hardlink")
    with pytest.raises(CheckpointFileUnavailable):
        await GovernanceCheckpointFile(
            tmp_path, expected_uid=expected_uid, expected_gid=os.getgid()
        ).load_public_copies()


@pytest.mark.asyncio
async def test_loader_reopens_complete_file_after_same_directory_rename(tmp_path: Path) -> None:
    os.chmod(tmp_path, 0o755)
    current = tmp_path / "grant-checkpoint.json"
    current.write_bytes(b"old")
    current.chmod(0o644)
    loader = GovernanceCheckpointFile(tmp_path, expected_uid=os.getuid(), expected_gid=os.getgid())
    assert await loader.load() == b"old"

    pending = tmp_path / "checkpoint.pending"
    pending.write_bytes(b"new-complete")
    pending.chmod(0o644)
    assert await loader.load() == b"old"
    os.replace(pending, current)
    assert await loader.load() == b"new-complete"


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["wrong_owner", "wrong_directory_mode", "wrong_file_mode", "hardlink"])
async def test_transaction_loader_rechecks_custody_after_valid_read(tmp_path: Path, state: str) -> None:
    os.chmod(tmp_path, 0o755)
    current = tmp_path / "grant-checkpoint.json"
    current.write_bytes(b"signed-checkpoint")
    current.chmod(0o644)
    loader = GovernanceCheckpointFile(tmp_path, expected_uid=os.getuid(), expected_gid=os.getgid())
    assert await loader.load() == b"signed-checkpoint"
    if state == "wrong_owner":
        loader = GovernanceCheckpointFile(tmp_path, expected_uid=os.getuid() + 1, expected_gid=os.getgid())
    elif state == "wrong_directory_mode":
        os.chmod(tmp_path, 0o777)
    elif state == "wrong_file_mode":
        current.chmod(0o666)
    else:
        os.link(current, tmp_path / "checkpoint-alias")
    with pytest.raises(CheckpointFileUnavailable):
        await loader.load()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["missing", "empty", "oversized", "symlink", "directory", "fifo"])
async def test_loader_rejects_unavailable_or_nonregular_checkpoint(tmp_path: Path, state: str) -> None:
    os.chmod(tmp_path, 0o755)
    current = tmp_path / "grant-checkpoint.json"
    if state == "empty":
        current.write_bytes(b"")
    elif state == "oversized":
        current.write_bytes(b"x" * (MAX_GRANT_CHECKPOINT_BYTES + 1))
    elif state == "symlink":
        target = tmp_path / "target.json"
        target.write_bytes(b"valid")
        current.symlink_to(target)
    elif state == "directory":
        current.mkdir()
    elif state == "fifo":
        os.mkfifo(current)
    with pytest.raises(CheckpointFileUnavailable) as exc:
        await GovernanceCheckpointFile(tmp_path, expected_uid=os.getuid(), expected_gid=os.getgid()).load()
    assert str(tmp_path) not in str(exc.value)


@pytest.mark.asyncio
async def test_loader_rejects_symlinked_directory(tmp_path: Path) -> None:
    owned = tmp_path / "owned"
    owned.mkdir()
    (owned / "grant-checkpoint.json").write_bytes(b"valid")
    alias = tmp_path / "alias"
    alias.symlink_to(owned, target_is_directory=True)
    with pytest.raises(CheckpointFileUnavailable):
        await GovernanceCheckpointFile(alias).load()
