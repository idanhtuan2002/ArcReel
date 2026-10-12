"""Public custody copies must agree before a signed checkpoint is usable."""

from __future__ import annotations

import base64
import hashlib
import json
from copy import deepcopy

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from lib.content_digest import canonical_json_bytes
from r2.governance.public_custody_snapshot import PublicCustodyMismatch, validate_public_custody_snapshot


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _encoded(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _public(key: Ed25519PrivateKey) -> str:
    return _encoded(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))


def _copies() -> tuple[bytes, bytes, bytes, bytes]:
    event_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32, 64)))
    checkpoint_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    registry = canonical_json_bytes(
        {
            "schema": "governance.verifier_registry.v1",
            "deployment_id": "deploy-a",
            "registry_sequence": 1,
            "grant_event": {"key_id": "grant-key-a", "public_key": _public(event_key)},
            "grant_checkpoint": {"key_id": "checkpoint-key-a", "public_key": _public(checkpoint_key)},
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
    return approval, registry, high_water, checkpoint


def test_public_copies_bind_exact_registry_and_signed_checkpoint() -> None:
    snapshot = validate_public_custody_snapshot(*_copies())
    assert snapshot.approval.deployment_id == "deploy-a"
    assert snapshot.registry.grant_checkpoint.key_id == "checkpoint-key-a"
    assert snapshot.high_water.checkpoint_sequence == snapshot.checkpoint.body.checkpoint_sequence == 1
    assert snapshot.checkpoint.body.heads == ()


def test_well_formed_successor_approval_is_not_activated_by_v1_snapshot() -> None:
    copies = list(_copies())
    approval = json.loads(copies[0])
    approval["approval_sequence"] = 2
    approval["previous_approval_digest"] = "sha256:" + "f" * 64
    copies[0] = canonical_json_bytes(approval, allow_nan=False)
    high_water = json.loads(copies[2])
    high_water["approved_deployment_digest"] = _digest(copies[0])
    copies[2] = canonical_json_bytes(high_water, allow_nan=False)
    with pytest.raises(PublicCustodyMismatch):
        validate_public_custody_snapshot(*copies)


@pytest.mark.parametrize(
    ("copy_index", "field", "value"),
    [
        (0, "registry_file_digest", "sha256:" + "0" * 64),
        (0, "checkpoint_key_id", "wrong-key"),
        (0, "approval_sequence", 2),
        (2, "approved_deployment_digest", "sha256:" + "0" * 64),
        (2, "checkpoint_body_digest", "sha256:" + "0" * 64),
        (2, "checkpoint_file_digest", "sha256:" + "0" * 64),
        (2, "checkpoint_sequence", 2),
        (2, "signer_key_id", "wrong-key"),
        (2, "deployment_id", "deploy-b"),
        (2, "checkpoint_issued_at", "2026-10-12T00:00:02Z"),
    ],
)
def test_public_copy_mismatch_denies(copy_index: int, field: str, value: object) -> None:
    copies = list(_copies())
    changed = deepcopy(json.loads(copies[copy_index]))
    changed[field] = value
    copies[copy_index] = canonical_json_bytes(changed, allow_nan=False)
    with pytest.raises(PublicCustodyMismatch):
        validate_public_custody_snapshot(*copies)


def test_checkpoint_signed_by_other_key_denies_even_if_public_file_digest_is_updated() -> None:
    copies = list(_copies())
    other_key = Ed25519PrivateKey.from_private_bytes(bytes(range(64, 96)))
    checkpoint = json.loads(copies[3])
    checkpoint["signature"] = _encoded(other_key.sign(canonical_json_bytes(checkpoint["body"], allow_nan=False)))
    copies[3] = canonical_json_bytes(checkpoint, allow_nan=False)
    high_water = json.loads(copies[2])
    high_water["checkpoint_file_digest"] = _digest(copies[3])
    copies[2] = canonical_json_bytes(high_water, allow_nan=False)
    with pytest.raises(PublicCustodyMismatch):
        validate_public_custody_snapshot(*copies)
