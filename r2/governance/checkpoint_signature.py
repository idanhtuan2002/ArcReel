"""Verify a grant-head checkpoint with caller-pinned deployment and key material."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from r2.contracts.grant_checkpoint import (
    CheckpointInvalid,
    GrantHeadRecordV1,
    ParsedGrantCheckpointV1,
    parse_grant_checkpoint,
)


@dataclass(frozen=True)
class VerifiedGrantCheckpointV1(ParsedGrantCheckpointV1):
    """A signed checkpoint with exact-scope lookup after key verification."""

    _head_by_scope: Mapping[tuple[str, str, str], GrantHeadRecordV1] = field(repr=False, compare=False)

    def head_for_scope(self, *, user_id: str, project_name: str, principal: str) -> GrantHeadRecordV1 | None:
        return self._head_by_scope.get((user_id, project_name, principal))


def verify_grant_checkpoint(
    raw: bytes, *, deployment_id: str, key_id: str, public_key: bytes
) -> VerifiedGrantCheckpointV1:
    """Verify one checkpoint; predecessor and database equality remain custody responsibilities."""

    parsed = parse_grant_checkpoint(raw)
    if deployment_id != parsed.body.deployment_id or key_id != parsed.body.signer_key_id or len(public_key) != 32:
        raise CheckpointInvalid("signature")
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(parsed.signature, parsed.signed_bytes)
    except (InvalidSignature, UnsupportedAlgorithm, ValueError, TypeError):
        raise CheckpointInvalid("signature") from None
    heads = MappingProxyType({(head.user_id, head.project_name, head.principal): head for head in parsed.body.heads})
    return VerifiedGrantCheckpointV1(
        body=parsed.body,
        signature=parsed.signature,
        signed_bytes=parsed.signed_bytes,
        checkpoint_digest=parsed.checkpoint_digest,
        _head_by_scope=heads,
    )


__all__ = ["VerifiedGrantCheckpointV1", "verify_grant_checkpoint"]
