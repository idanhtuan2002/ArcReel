"""A verifier registry is canonical data until an operator pins its digest."""

from __future__ import annotations

import base64
from copy import deepcopy

import pytest

from lib.content_digest import canonical_json_bytes
from r2.contracts.governance_verifier_registry import VerifierRegistryInvalid, parse_verifier_registry


def _key(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _registry() -> dict[str, object]:
    return {
        "schema": "governance.verifier_registry.v1",
        "deployment_id": "deploy-a",
        "registry_sequence": 1,
        "grant_event": {"key_id": "grant-key-a", "public_key": _key(bytes(range(32)))},
        "grant_checkpoint": {"key_id": "checkpoint-key-a", "public_key": _key(bytes(range(32, 64)))},
    }


def test_registry_returns_exact_purpose_keys_and_content_digest() -> None:
    raw = canonical_json_bytes(_registry(), allow_nan=False)
    parsed = parse_verifier_registry(raw)
    assert parsed.deployment_id == "deploy-a"
    assert parsed.registry_sequence == 1
    assert parsed.grant_event.key_id == "grant-key-a"
    assert parsed.grant_event.public_key == bytes(range(32))
    assert parsed.grant_checkpoint.key_id == "checkpoint-key-a"
    assert parsed.grant_checkpoint.public_key == bytes(range(32, 64))
    assert parsed.registry_digest == "sha256:ece43fdabd5cf41838e27fc5a19bf4729543cf6cc096f4d5707bff44ca739b65"


@pytest.mark.parametrize(
    "change",
    [
        "unknown_field",
        "missing_purpose",
        "wrong_schema",
        "wrong_deployment",
        "boolean_sequence",
        "zero_sequence",
        "same_key_id",
        "same_public_key",
        "short_public_key",
        "padded_public_key",
        "unknown_purpose_field",
    ],
)
def test_registry_rejects_invalid_shape_or_key_separation(change: str) -> None:
    registry = deepcopy(_registry())
    grant = registry["grant_event"]
    checkpoint = registry["grant_checkpoint"]
    assert isinstance(grant, dict)
    assert isinstance(checkpoint, dict)
    if change == "unknown_field":
        registry["ignored"] = "x"
    elif change == "missing_purpose":
        del registry["grant_checkpoint"]
    elif change == "wrong_schema":
        registry["schema"] = "governance.verifier_registry.v2"
    elif change == "wrong_deployment":
        registry["deployment_id"] = "*"
    elif change == "boolean_sequence":
        registry["registry_sequence"] = True
    elif change == "zero_sequence":
        registry["registry_sequence"] = 0
    elif change == "same_key_id":
        checkpoint["key_id"] = grant["key_id"]
    elif change == "same_public_key":
        checkpoint["public_key"] = grant["public_key"]
    elif change == "short_public_key":
        checkpoint["public_key"] = _key(b"short")
    elif change == "padded_public_key":
        checkpoint["public_key"] = str(checkpoint["public_key"]) + "="
    elif change == "unknown_purpose_field":
        checkpoint["extra"] = "x"
    with pytest.raises(VerifierRegistryInvalid) as exc:
        parse_verifier_registry(canonical_json_bytes(registry, allow_nan=False))
    assert "grant-key-a" not in str(exc.value)


@pytest.mark.parametrize("change", ["duplicate", "noncanonical", "invalid_utf8", "oversized", "empty"])
def test_registry_rejects_invalid_wire_bytes(change: str) -> None:
    raw = canonical_json_bytes(_registry(), allow_nan=False)
    if change == "duplicate":
        raw = raw.replace(b'"registry_sequence":1', b'"registry_sequence":1,"registry_sequence":1')
    elif change == "noncanonical":
        raw = b" " + raw
    elif change == "invalid_utf8":
        raw = raw[:-1] + b"\xff"
    elif change == "oversized":
        raw = b"x" * 4097
    elif change == "empty":
        raw = b""
    with pytest.raises(VerifierRegistryInvalid):
        parse_verifier_registry(raw)
