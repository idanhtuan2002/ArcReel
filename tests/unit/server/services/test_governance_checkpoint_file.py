"""Checkpoint byte loading observes complete pathname replacements and fails closed."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from r2.contracts.grant_checkpoint import MAX_GRANT_CHECKPOINT_BYTES
from server.services.governance_checkpoint_file import CheckpointFileUnavailable, GovernanceCheckpointFile


@pytest.mark.asyncio
async def test_loader_reopens_complete_file_after_same_directory_rename(tmp_path: Path) -> None:
    current = tmp_path / "grant-checkpoint.json"
    current.write_bytes(b"old")
    loader = GovernanceCheckpointFile(tmp_path)
    assert await loader.load() == b"old"

    pending = tmp_path / "checkpoint.pending"
    pending.write_bytes(b"new-complete")
    assert await loader.load() == b"old"
    os.replace(pending, current)
    assert await loader.load() == b"new-complete"


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["missing", "empty", "oversized", "symlink", "directory", "fifo"])
async def test_loader_rejects_unavailable_or_nonregular_checkpoint(tmp_path: Path, state: str) -> None:
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
        await GovernanceCheckpointFile(tmp_path).load()
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
