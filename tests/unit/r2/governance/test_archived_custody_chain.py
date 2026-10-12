"""Retained checkpoint history must be contiguous before public copies are trusted."""

from __future__ import annotations

import base64
import hashlib
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from lib.content_digest import canonical_json_bytes
from r2.governance.archived_custody_chain import ArchivedCustodyInvalid, validate_archived_custody_chain


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _checkpoint(
    key: Ed25519PrivateKey, sequence: int, previous: str | None, heads: list[dict[str, object]]
) -> tuple[bytes, str]:
    body = {
        "schema": "governance.grant_head_checkpoint.v1",
        "deployment_id": "deploy-a",
        "checkpoint_sequence": sequence,
        "previous_checkpoint_digest": previous,
        "issued_at": f"2026-10-12T00:00:{sequence:02d}Z",
        "signer_key_id": "checkpoint-key-a",
        "heads": heads,
    }
    body_raw = canonical_json_bytes(body, allow_nan=False)
    return canonical_json_bytes({"body": body, "signature": _b64(key.sign(body_raw))}, allow_nan=False), _digest(
        body_raw
    )


def _chain() -> tuple[bytes, bytes, list[tuple[bytes, bytes]], tuple[bytes, bytes, bytes, bytes]]:
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    event_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32, 64)))
    registry = canonical_json_bytes(
        {
            "schema": "governance.verifier_registry.v1",
            "deployment_id": "deploy-a",
            "registry_sequence": 1,
            "grant_event": {
                "key_id": "grant-key-a",
                "public_key": _b64(
                    event_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
                ),
            },
            "grant_checkpoint": {
                "key_id": "checkpoint-key-a",
                "public_key": _b64(
                    key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
                ),
            },
        },
        allow_nan=False,
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
    head = {
        "user_id": "tenant-a",
        "project_name": "show-a",
        "principal": "reviewer-a",
        "head_sequence": 1,
        "head_event_digest": "sha256:" + "b" * 64,
    }
    first, first_body_digest = _checkpoint(key, 1, None, [head])
    second, second_body_digest = _checkpoint(key, 2, first_body_digest, [head | {"head_sequence": 2}])
    first_high_water = canonical_json_bytes(
        {
            "schema": "governance.checkpoint_high_water.v1",
            "deployment_id": "deploy-a",
            "approved_deployment_digest": _digest(approval),
            "checkpoint_sequence": 1,
            "checkpoint_body_digest": first_body_digest,
            "checkpoint_file_digest": _digest(first),
            "previous_checkpoint_body_digest": None,
            "previous_high_water_digest": None,
            "signer_key_id": "checkpoint-key-a",
            "checkpoint_issued_at": "2026-10-12T00:00:01Z",
            "recorded_at": "2026-10-12T00:00:02Z",
            "operator_id": "operator-a",
        },
        allow_nan=False,
    )
    second_high_water = canonical_json_bytes(
        {
            **json.loads(first_high_water),
            "checkpoint_sequence": 2,
            "checkpoint_body_digest": second_body_digest,
            "checkpoint_file_digest": _digest(second),
            "previous_checkpoint_body_digest": first_body_digest,
            "previous_high_water_digest": _digest(first_high_water),
            "checkpoint_issued_at": "2026-10-12T00:00:02Z",
            "recorded_at": "2026-10-12T00:00:03Z",
        },
        allow_nan=False,
    )
    history = [(first_high_water, first), (second_high_water, second)]
    return approval, registry, history, (approval, registry, second_high_water, second)


def test_complete_chain_and_public_latest_bytes_pass() -> None:
    approval, registry, history, public = _chain()
    verified = validate_archived_custody_chain(approval, registry, history, public)
    assert verified.high_water.checkpoint_sequence == 2
    assert verified.checkpoint.body.heads[0].head_sequence == 2


def test_older_public_pair_denies_against_newer_retained_chain() -> None:
    approval, registry, history, _public = _chain()
    old_public = (approval, registry, *history[0])
    with pytest.raises(ArchivedCustodyInvalid):
        validate_archived_custody_chain(approval, registry, history, old_public)


@pytest.mark.parametrize("change", ["missing_genesis", "broken_link", "missing_envelope", "duplicate_successor"])
def test_broken_retained_chain_denies(change: str) -> None:
    approval, registry, history, public = _chain()
    if change == "missing_genesis":
        history = history[1:]
    elif change == "broken_link":
        changed = json.loads(history[1][0])
        changed["previous_high_water_digest"] = "sha256:" + "0" * 64
        history[1] = (canonical_json_bytes(changed, allow_nan=False), history[1][1])
    elif change == "missing_envelope":
        history[1] = (history[1][0], b"")
    elif change == "duplicate_successor":
        history = [history[0], history[1], history[1]]
    with pytest.raises(ArchivedCustodyInvalid):
        validate_archived_custody_chain(approval, registry, history, public)


def test_removed_scope_denies_even_with_valid_successor_signature() -> None:
    approval, registry, history, public = _chain()
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    old_body = json.loads(history[0][0])["checkpoint_body_digest"]
    second, body_digest = _checkpoint(key, 2, old_body, [])
    high_water = json.loads(history[1][0])
    high_water["checkpoint_body_digest"] = body_digest
    high_water["checkpoint_file_digest"] = _digest(second)
    history[1] = (canonical_json_bytes(high_water, allow_nan=False), second)
    public = (approval, registry, history[1][0], second)
    with pytest.raises(ArchivedCustodyInvalid):
        validate_archived_custody_chain(approval, registry, history, public)


def test_unchanged_head_sequence_cannot_switch_event_digest() -> None:
    approval, registry, history, _public = _chain()
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    old_body = json.loads(history[0][0])["checkpoint_body_digest"]
    old_head = json.loads(history[0][1])["body"]["heads"][0]
    second, body_digest = _checkpoint(key, 2, old_body, [old_head | {"head_event_digest": "sha256:" + "c" * 64}])
    high_water = json.loads(history[1][0])
    high_water["checkpoint_body_digest"] = body_digest
    high_water["checkpoint_file_digest"] = _digest(second)
    history[1] = (canonical_json_bytes(high_water, allow_nan=False), second)
    public = (approval, registry, history[1][0], second)
    with pytest.raises(ArchivedCustodyInvalid):
        validate_archived_custody_chain(approval, registry, history, public)
