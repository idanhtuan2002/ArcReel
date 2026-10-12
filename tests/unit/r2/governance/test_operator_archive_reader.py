"""Operator archive preflight reads only a bounded, owned custody tree."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from lib.content_digest import canonical_json_bytes
from r2.governance.operator_archive_reader import ArchiveReadLimits, OperatorArchiveInvalid, OperatorArchiveReader


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _encoded(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _put(path: Path, raw: bytes, mode: int) -> None:
    path.write_bytes(raw)
    path.chmod(mode)


def _tree(tmp_path: Path) -> tuple[Path, dict[str, Path]]:
    checkpoint_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    event_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32, 64)))
    root = tmp_path / "custody"
    root.mkdir(mode=0o700)
    archive = root / "archive"
    public = root / "read"
    archive.mkdir(mode=0o700)
    public.mkdir(mode=0o755)
    for name in ("approved", "registries", "high-water", "checkpoints", ".staging"):
        (archive / name).mkdir(mode=0o700)
    _put(archive / ".publisher.lock", b"", 0o600)
    registry = canonical_json_bytes(
        {
            "schema": "governance.verifier_registry.v1",
            "deployment_id": "deploy-a",
            "registry_sequence": 1,
            "grant_event": {
                "key_id": "grant-key-a",
                "public_key": _encoded(
                    event_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
                ),
            },
            "grant_checkpoint": {
                "key_id": "checkpoint-key-a",
                "public_key": _encoded(
                    checkpoint_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
                ),
            },
        },
        allow_nan=False,
    )
    body = {
        "schema": "governance.grant_head_checkpoint.v1",
        "deployment_id": "deploy-a",
        "checkpoint_sequence": 1,
        "previous_checkpoint_digest": None,
        "issued_at": "2026-10-12T00:00:00Z",
        "signer_key_id": "checkpoint-key-a",
        "heads": [],
    }
    body_raw = canonical_json_bytes(body, allow_nan=False)
    checkpoint = canonical_json_bytes(
        {"body": body, "signature": _encoded(checkpoint_key.sign(body_raw))}, allow_nan=False
    )
    approval = canonical_json_bytes(
        {
            "schema": "governance.approved_deployment.v1",
            "deployment_id": "deploy-a",
            "approval_sequence": 1,
            "previous_approval_digest": None,
            "image_ref": "arcreel/arcreel@sha256:" + "a" * 64,
            "image_platform": "linux/amd64",
            "registry_sequence": 1,
            "registry_file_digest": _digest(registry),
            "grant_event_key_id": "grant-key-a",
            "checkpoint_key_id": "checkpoint-key-a",
            "approved_at": "2026-10-12T00:00:00Z",
            "operator_id": "operator-a",
        },
        allow_nan=False,
    )
    high_water = canonical_json_bytes(
        {
            "schema": "governance.checkpoint_high_water.v1",
            "deployment_id": "deploy-a",
            "approved_deployment_digest": _digest(approval),
            "checkpoint_sequence": 1,
            "checkpoint_body_digest": _digest(body_raw),
            "checkpoint_file_digest": _digest(checkpoint),
            "previous_checkpoint_body_digest": None,
            "previous_high_water_digest": None,
            "signer_key_id": "checkpoint-key-a",
            "checkpoint_issued_at": "2026-10-12T00:00:00Z",
            "recorded_at": "2026-10-12T00:00:01Z",
            "operator_id": "operator-a",
        },
        allow_nan=False,
    )
    paths = {
        "approved": archive / "approved" / "00000000000000000001.json",
        "registry": archive / "registries" / f"sha256-{_digest(registry)[7:]}.json",
        "high_water": archive / "high-water" / "00000000000000000001.json",
        "checkpoint": archive / "checkpoints" / f"sha256-{_digest(checkpoint)[7:]}.json",
        "public_approved": public / "approved-deployment.json",
        "public_registry": public / "governance-verifiers-v1.json",
        "public_high_water": public / "high-water.json",
        "public_checkpoint": public / "grant-checkpoint.json",
        "lock": archive / ".publisher.lock",
    }
    for name, raw in (
        ("approved", approval),
        ("registry", registry),
        ("high_water", high_water),
        ("checkpoint", checkpoint),
    ):
        _put(paths[name], raw, 0o600)
        _put(paths[f"public_{name}"], raw, 0o644)
    return root, paths


def _append_successor(root: Path, paths: dict[str, Path]) -> None:
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    old_checkpoint = json.loads(paths["checkpoint"].read_bytes())
    old_high_water_raw = paths["high_water"].read_bytes()
    body = old_checkpoint["body"] | {
        "checkpoint_sequence": 2,
        "previous_checkpoint_digest": _digest(canonical_json_bytes(old_checkpoint["body"], allow_nan=False)),
        "issued_at": "2026-10-12T00:00:02Z",
    }
    checkpoint = canonical_json_bytes(
        {"body": body, "signature": _encoded(key.sign(canonical_json_bytes(body, allow_nan=False)))},
        allow_nan=False,
    )
    high_water = json.loads(old_high_water_raw) | {
        "checkpoint_sequence": 2,
        "checkpoint_body_digest": _digest(canonical_json_bytes(body, allow_nan=False)),
        "checkpoint_file_digest": _digest(checkpoint),
        "previous_checkpoint_body_digest": body["previous_checkpoint_digest"],
        "previous_high_water_digest": _digest(old_high_water_raw),
        "checkpoint_issued_at": "2026-10-12T00:00:02Z",
        "recorded_at": "2026-10-12T00:00:03Z",
    }
    high_water_raw = canonical_json_bytes(high_water, allow_nan=False)
    _put(root / "archive" / "high-water" / "00000000000000000002.json", high_water_raw, 0o600)
    _put(root / "archive" / "checkpoints" / f"sha256-{_digest(checkpoint)[7:]}.json", checkpoint, 0o600)
    _put(paths["public_high_water"], high_water_raw, 0o644)
    _put(paths["public_checkpoint"], checkpoint, 0o644)


def test_reader_accepts_exact_owned_genesis_and_returns_latest_bytes(tmp_path: Path) -> None:
    root, paths = _tree(tmp_path)
    result = OperatorArchiveReader(root, expected_uid=os.getuid()).read()
    assert result.snapshot.high_water.checkpoint_sequence == 1
    assert result.approved_raw == paths["approved"].read_bytes()
    assert result.checkpoint_raw == paths["checkpoint"].read_bytes()


def test_reader_accepts_retained_successor_and_denies_old_public_pair(tmp_path: Path) -> None:
    root, paths = _tree(tmp_path)
    old_high_water = paths["public_high_water"].read_bytes()
    old_checkpoint = paths["public_checkpoint"].read_bytes()
    _append_successor(root, paths)
    assert OperatorArchiveReader(root, expected_uid=os.getuid()).read().snapshot.high_water.checkpoint_sequence == 2
    _put(paths["public_high_water"], old_high_water, 0o644)
    _put(paths["public_checkpoint"], old_checkpoint, 0o644)
    with pytest.raises(OperatorArchiveInvalid):
        OperatorArchiveReader(root, expected_uid=os.getuid()).read()


@pytest.mark.parametrize(
    "fault", ["old_public", "wrong_registry_name", "missing_record", "extra_record", "sequence_gap", "staging_file"]
)
def test_reader_denies_archive_or_public_divergence(tmp_path: Path, fault: str) -> None:
    root, paths = _tree(tmp_path)
    if fault == "old_public":
        _put(paths["public_checkpoint"], b"old", 0o644)
    elif fault == "wrong_registry_name":
        paths["registry"].rename(paths["registry"].with_name("sha256-" + "0" * 64 + ".json"))
    elif fault == "missing_record":
        paths["high_water"].unlink()
    elif fault == "extra_record":
        _put(paths["high_water"].with_name("00000000000000000002.json"), b"{}", 0o600)
    elif fault == "sequence_gap":
        _append_successor(root, paths)
        (root / "archive" / "high-water" / "00000000000000000002.json").rename(
            root / "archive" / "high-water" / "00000000000000000003.json"
        )
    elif fault == "staging_file":
        _put(root / "archive" / ".staging" / "unfinished", b"partial", 0o600)
    with pytest.raises(OperatorArchiveInvalid):
        OperatorArchiveReader(root, expected_uid=os.getuid()).read()


@pytest.mark.parametrize(
    "fault",
    [
        "symlink_root",
        "symlink_parent",
        "symlink_subdir",
        "symlink_file",
        "wrong_mode",
        "hardlink",
        "wrong_owner",
        "fifo",
        "oversized",
    ],
)
def test_reader_denies_unsafe_path_or_metadata(tmp_path: Path, fault: str) -> None:
    root, paths = _tree(tmp_path)
    expected_uid = os.getuid()
    if fault == "symlink_root":
        link = tmp_path / "custody-link"
        link.symlink_to(root, target_is_directory=True)
        root = link
    elif fault == "symlink_parent":
        link = tmp_path / "parent-link"
        link.symlink_to(tmp_path, target_is_directory=True)
        root = link / "custody"
    elif fault == "symlink_subdir":
        target = root / "archive" / "approved-real"
        paths["approved"].parent.rename(target)
        paths["approved"].parent.symlink_to(target, target_is_directory=True)
    elif fault == "symlink_file":
        target = paths["public_checkpoint"].with_name("checkpoint-target")
        paths["public_checkpoint"].rename(target)
        paths["public_checkpoint"].symlink_to(target)
    elif fault == "wrong_mode":
        paths["approved"].chmod(0o666)
    elif fault == "hardlink":
        os.link(paths["checkpoint"], root / "archive" / "checkpoints" / "outside-copy")
    elif fault == "wrong_owner":
        expected_uid += 1
    elif fault == "fifo":
        paths["public_checkpoint"].unlink()
        os.mkfifo(paths["public_checkpoint"], 0o644)
    elif fault == "oversized":
        _put(paths["high_water"], b"x" * 8193, 0o600)
    with pytest.raises(OperatorArchiveInvalid):
        OperatorArchiveReader(root, expected_uid=expected_uid).read()


def test_reader_denies_busy_operator_lock(tmp_path: Path) -> None:
    import portalocker

    root, paths = _tree(tmp_path)
    with paths["lock"].open("rb") as handle:
        portalocker.lock(handle, portalocker.LOCK_EX | portalocker.LOCK_NB)
        try:
            with pytest.raises(OperatorArchiveInvalid):
                OperatorArchiveReader(root, expected_uid=os.getuid()).read()
        finally:
            portalocker.unlock(handle)


@pytest.mark.parametrize("limit", [ArchiveReadLimits(max_entries=10), ArchiveReadLimits(max_bytes=100)])
def test_reader_denies_when_bounded_inventory_exceeds_limit(tmp_path: Path, limit: ArchiveReadLimits) -> None:
    root, _paths = _tree(tmp_path)
    with pytest.raises(OperatorArchiveInvalid):
        OperatorArchiveReader(root, expected_uid=os.getuid(), limits=limit).read()


@pytest.mark.parametrize("limits", [{"max_entries": 10_001}, {"max_bytes": 64 * 1024 * 1024 + 1}])
def test_reader_limits_cannot_raise_hard_caps(limits: dict[str, int]) -> None:
    with pytest.raises(ValueError, match="invalid archive read limits"):
        ArchiveReadLimits(**limits)


def test_reader_sanitizes_invalid_root_bytes() -> None:
    with pytest.raises(OperatorArchiveInvalid, match="operator Governance archive is unavailable"):
        OperatorArchiveReader(Path("/tmp/custody\x00invalid"), expected_uid=os.getuid()).read()
