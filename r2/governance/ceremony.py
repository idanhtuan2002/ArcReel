"""Build the canonical records of an ADR-0103 activation ceremony.

Every builder re-parses its output with the verifier the host and app use, so a ceremony can never
produce bytes those verifiers would reject. Signing takes raw Ed25519 private key bytes and belongs only
to the offline signer; the application never holds a signing key.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from r2.contracts.fingerprints import canonical_json_bytes
from r2.contracts.governance_host_records import (
    ParsedCheckpointHighWaterV1,
    parse_approved_deployment,
    parse_checkpoint_high_water,
)
from r2.contracts.governance_verifier_registry import ParsedVerifierRegistryV1, parse_verifier_registry
from r2.contracts.grant_checkpoint import GrantHeadRecordV1, ParsedGrantCheckpointV1, parse_grant_checkpoint
from r2.contracts.showrunner_grant import ParsedGrantEventV1, parse_grant_event

ARCHIVE_SEQUENCE_WIDTH = 20


class CeremonyInvalid(ValueError):
    """The requested ceremony record cannot be built."""


@dataclass(frozen=True)
class KeyPair:
    private_raw: bytes
    public_encoded: str


def utc_second(moment: datetime | None = None) -> str:
    return (moment or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _encoded(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_public_key(encoded: str) -> bytes:
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    except (ValueError, TypeError) as exc:
        raise CeremonyInvalid("public key encoding") from exc
    if len(raw) != 32 or _encoded(raw) != encoded:
        raise CeremonyInvalid("public key encoding")
    return raw


def _private(private_raw: bytes) -> Ed25519PrivateKey:
    if type(private_raw) is not bytes or len(private_raw) != 32:
        raise CeremonyInvalid("private key")
    return Ed25519PrivateKey.from_private_bytes(private_raw)


def generate_key() -> KeyPair:
    key = Ed25519PrivateKey.generate()
    private_raw = key.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    return KeyPair(private_raw=private_raw, public_encoded=public_key_of(private_raw))


def public_key_of(private_raw: bytes) -> str:
    public = _private(private_raw).public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return _encoded(public)


def _canonical(value: dict[str, object]) -> bytes:
    return canonical_json_bytes(value)  # type: ignore[arg-type]


def _signed(body: dict[str, object], private_raw: bytes) -> bytes:
    return _canonical({"body": body, "signature": _encoded(_private(private_raw).sign(_canonical(body)))})


def build_registry(
    *,
    deployment_id: str,
    grant_key_id: str,
    grant_public_key: str,
    checkpoint_key_id: str,
    checkpoint_public_key: str,
) -> tuple[bytes, ParsedVerifierRegistryV1]:
    """The first public verifier registry; the two keys must be distinct."""
    if grant_public_key == checkpoint_public_key or grant_key_id == checkpoint_key_id:
        raise CeremonyInvalid("grant and checkpoint keys must differ")
    raw = _canonical(
        {
            "schema": "governance.verifier_registry.v1",
            "deployment_id": deployment_id,
            "registry_sequence": 1,
            "grant_event": {"key_id": grant_key_id, "public_key": grant_public_key},
            "grant_checkpoint": {"key_id": checkpoint_key_id, "public_key": checkpoint_public_key},
        }
    )
    return raw, parse_verifier_registry(raw)


def build_approved_deployment(
    registry_raw: bytes, *, image_ref: str, image_platform: str, operator_id: str, approved_at: str | None = None
) -> bytes:
    """Approval sequence 1 binding the pinned image to the exact registry bytes."""
    registry = parse_verifier_registry(registry_raw)
    raw = _canonical(
        {
            "schema": "governance.approved_deployment.v1",
            "deployment_id": registry.deployment_id,
            "approval_sequence": 1,
            "previous_approval_digest": None,
            "image_ref": image_ref,
            "image_platform": image_platform,
            "registry_sequence": registry.registry_sequence,
            "registry_file_digest": digest(registry_raw),
            "grant_event_key_id": registry.grant_event.key_id,
            "checkpoint_key_id": registry.grant_checkpoint.key_id,
            "approved_at": approved_at or utc_second(),
            "operator_id": operator_id,
        }
    )
    parse_approved_deployment(raw)
    return raw


def checkpoint_body(
    *,
    deployment_id: str,
    signer_key_id: str,
    sequence: int,
    previous: ParsedGrantCheckpointV1 | None,
    heads: tuple[GrantHeadRecordV1, ...],
    issued_at: str | None = None,
) -> bytes:
    """The unsigned body of checkpoint ``sequence``; genesis names no predecessor and no heads."""
    if (sequence == 1) != (previous is None) or (sequence == 1 and heads):
        raise CeremonyInvalid("genesis checkpoint must be sequence 1 with no heads")
    if previous is not None and previous.body.checkpoint_sequence != sequence - 1:
        raise CeremonyInvalid("checkpoint sequence must advance by one")
    body = {
        "schema": "governance.grant_head_checkpoint.v1",
        "deployment_id": deployment_id,
        "checkpoint_sequence": sequence,
        "previous_checkpoint_digest": None if previous is None else previous.checkpoint_digest,
        "issued_at": issued_at or utc_second(),
        "signer_key_id": signer_key_id,
        "heads": [head.model_dump(mode="json") for head in heads],
    }
    return _canonical(body)


def sign_checkpoint(body_raw: bytes, private_raw: bytes) -> bytes:
    """Sign an exact unsigned checkpoint body the host exported."""
    try:
        body = json.loads(body_raw)
    except ValueError as exc:
        raise CeremonyInvalid("checkpoint body") from exc
    if not isinstance(body, dict) or _canonical(body) != body_raw:
        raise CeremonyInvalid("checkpoint body is not canonical")
    raw = _signed(body, private_raw)
    parse_grant_checkpoint(raw)
    return raw


def sign_grant_event(
    *,
    private_raw: bytes,
    signer_key_id: str,
    event_type: str,
    user_id: str,
    project_name: str,
    principal: str,
    sequence: int,
    previous_event_digest: str | None,
    expires_at: str | None = None,
    issued_at: str | None = None,
) -> tuple[bytes, ParsedGrantEventV1]:
    """One signed ISSUE (with its validity interval) or REVOKE event for an exact scope."""
    issued = issued_at or utc_second()
    body: dict[str, object] = {
        "schema": "governance.showrunner_grant_event.v1",
        "event_type": event_type,
        "user_id": user_id,
        "project_name": project_name,
        "principal": principal,
        "role": "HUMAN_SHOWRUNNER",
        "sequence": sequence,
        "previous_event_digest": previous_event_digest,
        "issued_at": issued,
        "signer_key_id": signer_key_id,
    }
    if event_type == "REVOKE" and expires_at is not None:
        raise CeremonyInvalid("a REVOKE takes no expires_at")
    if event_type == "ISSUE":
        if expires_at is None:
            raise CeremonyInvalid("an ISSUE needs expires_at")
        body["not_before"] = issued
        body["expires_at"] = expires_at
    raw = _signed(body, private_raw)
    return raw, parse_grant_event(raw)


def high_water_record(
    *,
    approved_raw: bytes,
    checkpoint_raw: bytes,
    previous: ParsedCheckpointHighWaterV1 | None,
    previous_raw: bytes | None,
    operator_id: str,
    recorded_at: str | None = None,
) -> bytes:
    """The high-water record that retains ``checkpoint_raw`` after ``previous`` (None at genesis)."""
    approved = parse_approved_deployment(approved_raw)
    checkpoint = parse_grant_checkpoint(checkpoint_raw)
    body = checkpoint.body
    if (previous is None) != (previous_raw is None) or (previous is None) != (body.checkpoint_sequence == 1):
        raise CeremonyInvalid("high-water predecessor")
    raw = _canonical(
        {
            "schema": "governance.checkpoint_high_water.v1",
            "deployment_id": approved.deployment_id,
            "approved_deployment_digest": approved.record_digest,
            "checkpoint_sequence": body.checkpoint_sequence,
            "checkpoint_body_digest": checkpoint.checkpoint_digest,
            "checkpoint_file_digest": digest(checkpoint_raw),
            "previous_checkpoint_body_digest": body.previous_checkpoint_digest,
            "previous_high_water_digest": None if previous_raw is None else digest(previous_raw),
            "signer_key_id": body.signer_key_id,
            "checkpoint_issued_at": body.issued_at,
            "recorded_at": recorded_at or utc_second(),
            "operator_id": operator_id,
        }
    )
    parse_checkpoint_high_water(raw)
    return raw


def sequence_name(sequence: int) -> str:
    return f"{sequence:0{ARCHIVE_SEQUENCE_WIDTH}d}.json"


def digest_name(raw: bytes) -> str:
    return f"sha256-{hashlib.sha256(raw).hexdigest()}.json"


__all__ = [
    "CeremonyInvalid",
    "KeyPair",
    "build_approved_deployment",
    "build_registry",
    "checkpoint_body",
    "decode_public_key",
    "digest",
    "digest_name",
    "generate_key",
    "high_water_record",
    "public_key_of",
    "sequence_name",
    "sign_checkpoint",
    "sign_grant_event",
    "utc_second",
]
