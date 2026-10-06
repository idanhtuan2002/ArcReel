"""Verify a canonical Showrunner grant event against a caller-pinned public key."""

from __future__ import annotations

from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from r2.contracts.showrunner_grant import GrantEventInvalid, ParsedGrantEventV1, parse_grant_event


@dataclass(frozen=True)
class VerifiedGrantEventV1(ParsedGrantEventV1):
    """An event whose exact canonical body verified under the supplied key."""


def verify_grant_event(raw: bytes, *, key_id: str, public_key: bytes) -> VerifiedGrantEventV1:
    """Verify one event; scope/sequence/currentness remain importer responsibilities."""

    parsed = parse_grant_event(raw)
    if key_id != parsed.body.signer_key_id or len(public_key) != 32:
        raise GrantEventInvalid("signature")
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(parsed.signature, parsed.signed_bytes)
    except (InvalidSignature, UnsupportedAlgorithm, ValueError):
        raise GrantEventInvalid("signature") from None
    return VerifiedGrantEventV1(
        body=parsed.body,
        signature=parsed.signature,
        signed_bytes=parsed.signed_bytes,
        event_digest=parsed.event_digest,
    )


__all__ = ["VerifiedGrantEventV1", "verify_grant_event"]
