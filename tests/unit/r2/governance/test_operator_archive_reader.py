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
from r2.governance.operator_archive_reader import (
    ArchiveReadLimits,
    OperatorArchiveInvalid,
    OperatorArchiveReader,
    _locked_archive,
    classify_public_copies,
)


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


def test_locked_session_verifies_retained_successor_with_old_public_pair(tmp_path: Path) -> None:
    root, paths = _tree(tmp_path)
    old_high_water = paths["public_high_water"].read_bytes()
    old_checkpoint = paths["public_checkpoint"].read_bytes()
    _append_successor(root, paths)
    _put(paths["public_high_water"], old_high_water, 0o644)
    _put(paths["public_checkpoint"], old_checkpoint, 0o644)
    with _locked_archive(root, uid=os.getuid(), limits=ArchiveReadLimits()) as session:
        state = session.read_retained()
        assert state.snapshot.high_water.checkpoint_sequence == 2
        assert state.public[2:] == (old_high_water, old_checkpoint)
        with pytest.raises(OperatorArchiveInvalid):
            OperatorArchiveReader(root, expected_uid=os.getuid()).read()
    with pytest.raises(OperatorArchiveInvalid):
        OperatorArchiveReader(root, expected_uid=os.getuid()).read()


@pytest.mark.parametrize("fault", ["unknown_staging", "orphan_envelope"])
def test_locked_retained_scan_denies_incomplete_archive(tmp_path: Path, fault: str) -> None:
    root, _paths = _tree(tmp_path)
    if fault == "unknown_staging":
        _put(root / "archive" / ".staging" / "unknown.tmp", b"partial", 0o600)
    else:
        _put(root / "archive" / "checkpoints" / ("sha256-" + "0" * 64 + ".json"), b"{}", 0o600)
    with (
        _locked_archive(root, uid=os.getuid(), limits=ArchiveReadLimits()) as session,
        pytest.raises(OperatorArchiveInvalid),
    ):
        session.read_retained()


@pytest.mark.parametrize(
    ("public_state", "expected"),
    [
        ("current", "current"),
        ("previous", "previous"),
        ("new_high_water", "new_high_water"),
    ],
)
def test_classify_complete_retained_archive_public_state(tmp_path: Path, public_state: str, expected: str) -> None:
    root, paths = _tree(tmp_path)
    old_high_water = paths["public_high_water"].read_bytes()
    old_checkpoint = paths["public_checkpoint"].read_bytes()
    _append_successor(root, paths)
    if public_state == "previous":
        _put(paths["public_high_water"], old_high_water, 0o644)
        _put(paths["public_checkpoint"], old_checkpoint, 0o644)
    elif public_state == "new_high_water":
        _put(paths["public_checkpoint"], old_checkpoint, 0o644)
    with _locked_archive(root, uid=os.getuid(), limits=ArchiveReadLimits()) as session:
        assert classify_public_copies(session.read_retained()) == expected


@pytest.mark.parametrize("fault", ["reverse_order", "unknown_high_water", "approval_changed", "registry_changed"])
def test_classify_public_state_denies_unexpected_bytes(tmp_path: Path, fault: str) -> None:
    root, paths = _tree(tmp_path)
    old_high_water = paths["public_high_water"].read_bytes()
    _append_successor(root, paths)
    if fault == "reverse_order":
        _put(paths["public_high_water"], old_high_water, 0o644)
    elif fault == "unknown_high_water":
        _put(paths["public_high_water"], b"{}", 0o644)
    elif fault == "approval_changed":
        _put(paths["public_approved"], b"{}", 0o644)
    else:
        _put(paths["public_registry"], b"{}", 0o644)
    with (
        _locked_archive(root, uid=os.getuid(), limits=ArchiveReadLimits()) as session,
        pytest.raises(OperatorArchiveInvalid),
    ):
        classify_public_copies(session.read_retained())


@pytest.mark.parametrize("fault", ["matching", "wrong_bytes", "wrong_name"])
def test_locked_recovery_scan_accepts_only_exact_retained_public_temporaries(tmp_path: Path, fault: str) -> None:
    root, paths = _tree(tmp_path)
    _append_successor(root, paths)
    latest_high_water = (root / "archive" / "high-water" / "00000000000000000002.json").read_bytes()
    name = ".high-water.00000000000000000002.tmp" if fault != "wrong_name" else ".unknown.tmp"
    temporary = root / "read" / name
    _put(temporary, latest_high_water if fault != "wrong_bytes" else b"{}", 0o644)
    with _locked_archive(root, uid=os.getuid(), limits=ArchiveReadLimits()) as session:
        with pytest.raises(OperatorArchiveInvalid):
            session.read_retained()
        if fault == "matching":
            state = session.read_retained(allow_public_temps=True)
            assert state.public_temps == (name,)
        else:
            with pytest.raises(OperatorArchiveInvalid):
                session.read_retained(allow_public_temps=True)


@pytest.mark.parametrize("fault", ["matching", "wrong_bytes", "wrong_name", "wrong_mode", "stale_public"])
def test_locked_orphan_checkpoint_scan_requires_exact_candidate(tmp_path: Path, fault: str) -> None:
    root, paths = _tree(tmp_path)
    old_high_water = paths["public_high_water"].read_bytes()
    old_checkpoint = paths["public_checkpoint"].read_bytes()
    _append_successor(root, paths)
    candidate = paths["public_checkpoint"].read_bytes()
    orphan = root / "archive" / "checkpoints" / f"sha256-{_digest(candidate)[7:]}.json"
    (root / "archive" / "high-water" / "00000000000000000002.json").unlink()
    _put(paths["public_high_water"], old_high_water, 0o644)
    _put(paths["public_checkpoint"], old_checkpoint, 0o644)
    if fault == "wrong_bytes":
        _put(orphan, b"{}", 0o600)
    elif fault == "wrong_name":
        orphan.rename(orphan.with_name("sha256-" + "0" * 64 + ".json"))
    elif fault == "wrong_mode":
        orphan.chmod(0o644)
    elif fault == "stale_public":
        _put(paths["public_checkpoint"], candidate, 0o644)
    with _locked_archive(root, uid=os.getuid(), limits=ArchiveReadLimits()) as session:
        with pytest.raises(OperatorArchiveInvalid):
            session.read_retained()
        if fault == "matching":
            state = session.read_orphan_checkpoint(candidate)
            assert state.snapshot.high_water.checkpoint_sequence == 1
            assert state.history[-1] == (old_high_water, old_checkpoint)
        else:
            with pytest.raises(OperatorArchiveInvalid):
                session.read_orphan_checkpoint(candidate)


@pytest.mark.parametrize("fault", ["matching", "wrong_bytes", "wrong_name", "wrong_mode", "extra_link"])
def test_locked_staged_checkpoint_scan_requires_exact_unlinked_candidate(tmp_path: Path, fault: str) -> None:
    root, paths = _tree(tmp_path)
    old_high_water = paths["public_high_water"].read_bytes()
    old_checkpoint = paths["public_checkpoint"].read_bytes()
    _append_successor(root, paths)
    candidate = paths["public_checkpoint"].read_bytes()
    orphan = root / "archive" / "checkpoints" / f"sha256-{_digest(candidate)[7:]}.json"
    (root / "archive" / "high-water" / "00000000000000000002.json").unlink()
    staged = root / "archive" / ".staging" / ".checkpoint.00000000000000000002.tmp"
    orphan.rename(staged)
    _put(paths["public_high_water"], old_high_water, 0o644)
    _put(paths["public_checkpoint"], old_checkpoint, 0o644)
    if fault == "wrong_bytes":
        _put(staged, b"{}", 0o600)
    elif fault == "wrong_name":
        staged.rename(staged.with_name("unexpected.tmp"))
    elif fault == "wrong_mode":
        staged.chmod(0o644)
    elif fault == "extra_link":
        os.link(staged, root / "archive" / ".staging" / "unexpected")
    with _locked_archive(root, uid=os.getuid(), limits=ArchiveReadLimits()) as session:
        with pytest.raises(OperatorArchiveInvalid):
            session.read_retained()
        if fault == "matching":
            state = session.read_staged_checkpoint(candidate)
            assert state.snapshot.high_water.checkpoint_sequence == 1
            assert state.history[-1] == (old_high_water, old_checkpoint)
        else:
            with pytest.raises(OperatorArchiveInvalid):
                session.read_staged_checkpoint(candidate)


@pytest.mark.parametrize("fault", ["matching", "different_inode", "wrong_bytes", "extra_link", "wrong_name"])
def test_locked_linked_checkpoint_scan_requires_same_two_link_inode(tmp_path: Path, fault: str) -> None:
    root, paths = _tree(tmp_path)
    old_high_water = paths["public_high_water"].read_bytes()
    old_checkpoint = paths["public_checkpoint"].read_bytes()
    _append_successor(root, paths)
    candidate = paths["public_checkpoint"].read_bytes()
    orphan = root / "archive" / "checkpoints" / f"sha256-{_digest(candidate)[7:]}.json"
    (root / "archive" / "high-water" / "00000000000000000002.json").unlink()
    staged = root / "archive" / ".staging" / ".checkpoint.00000000000000000002.tmp"
    if fault == "different_inode":
        _put(staged, candidate, 0o600)
    else:
        os.link(orphan, staged)
    _put(paths["public_high_water"], old_high_water, 0o644)
    _put(paths["public_checkpoint"], old_checkpoint, 0o644)
    if fault == "wrong_bytes":
        _put(orphan, b"{}", 0o600)
    elif fault == "extra_link":
        os.link(orphan, root / "archive" / ".staging" / "unexpected")
    elif fault == "wrong_name":
        staged.rename(staged.with_name("unexpected.tmp"))
    with _locked_archive(root, uid=os.getuid(), limits=ArchiveReadLimits()) as session:
        with pytest.raises(OperatorArchiveInvalid):
            session.read_retained()
        if fault == "matching":
            state = session.read_linked_checkpoint(candidate)
            assert state.snapshot.high_water.checkpoint_sequence == 1
            assert orphan.stat().st_ino == staged.stat().st_ino
        else:
            with pytest.raises(OperatorArchiveInvalid):
                session.read_linked_checkpoint(candidate)


@pytest.mark.parametrize("fault", ["matching", "wrong_bytes", "wrong_name", "wrong_mode", "extra_link"])
def test_locked_staged_high_water_scan_requires_exact_signed_pair(tmp_path: Path, fault: str) -> None:
    root, paths = _tree(tmp_path)
    old_high_water = paths["public_high_water"].read_bytes()
    old_checkpoint = paths["public_checkpoint"].read_bytes()
    _append_successor(root, paths)
    candidate_high_water = paths["public_high_water"].read_bytes()
    candidate_checkpoint = paths["public_checkpoint"].read_bytes()
    retained_high_water = root / "archive" / "high-water" / "00000000000000000002.json"
    staged = root / "archive" / ".staging" / ".high-water.00000000000000000002.tmp"
    retained_high_water.rename(staged)
    _put(paths["public_high_water"], old_high_water, 0o644)
    _put(paths["public_checkpoint"], old_checkpoint, 0o644)
    if fault == "wrong_bytes":
        _put(staged, b"{}", 0o600)
    elif fault == "wrong_name":
        staged.rename(staged.with_name("unexpected.tmp"))
    elif fault == "wrong_mode":
        staged.chmod(0o644)
    elif fault == "extra_link":
        os.link(staged, root / "archive" / ".staging" / "unexpected")
    with _locked_archive(root, uid=os.getuid(), limits=ArchiveReadLimits()) as session:
        with pytest.raises(OperatorArchiveInvalid):
            session.read_retained()
        if fault == "matching":
            state = session.read_staged_high_water(candidate_high_water, candidate_checkpoint)
            assert state.snapshot.high_water.checkpoint_sequence == 1
            assert state.history[-1] == (old_high_water, old_checkpoint)
        else:
            with pytest.raises(OperatorArchiveInvalid):
                session.read_staged_high_water(candidate_high_water, candidate_checkpoint)


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
