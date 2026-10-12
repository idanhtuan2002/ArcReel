"""Parse canonical public verifier metadata without assigning it trust."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass

from r2.contracts.fingerprints import canonical_json_bytes

MAX_VERIFIER_REGISTRY_BYTES = 4_096
_IDENTIFIER = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:-]{0,254}\Z")
_PUBLIC_KEY = re.compile(r"\A[A-Za-z0-9_-]{43}\Z")
_SCHEMA = "governance.verifier_registry.v1"


class VerifierRegistryInvalid(ValueError):
    """Registry bytes cannot be used as bounded canonical verifier data."""

    def __init__(self) -> None:
        super().__init__("invalid verifier registry")


@dataclass(frozen=True)
class PublicVerifierV1:
    key_id: str
    public_key: bytes


@dataclass(frozen=True)
class ParsedVerifierRegistryV1:
    deployment_id: str
    registry_sequence: int
    grant_event: PublicVerifierV1
    grant_checkpoint: PublicVerifierV1
    registry_digest: str


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise VerifierRegistryInvalid
        result[key] = value
    return result


def _nonfinite(_value: str) -> None:
    raise VerifierRegistryInvalid


def _verifier(value: object) -> PublicVerifierV1:
    if not isinstance(value, dict) or set(value) != {"key_id", "public_key"}:
        raise VerifierRegistryInvalid
    key_id = value["key_id"]
    encoded = value["public_key"]
    if (
        not isinstance(key_id, str)
        or not _IDENTIFIER.fullmatch(key_id)
        or not isinstance(encoded, str)
        or not _PUBLIC_KEY.fullmatch(encoded)
    ):
        raise VerifierRegistryInvalid
    public_key = base64.urlsafe_b64decode(encoded + "=")
    if len(public_key) != 32 or base64.urlsafe_b64encode(public_key).decode("ascii").rstrip("=") != encoded:
        raise VerifierRegistryInvalid
    return PublicVerifierV1(key_id, public_key)


def parse_verifier_registry(raw: bytes) -> ParsedVerifierRegistryV1:
    """Return exact purpose keys; caller must pin the returned digest externally."""

    if not 0 < len(raw) <= MAX_VERIFIER_REGISTRY_BYTES:
        raise VerifierRegistryInvalid
    try:
        decoded = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs, parse_constant=_nonfinite)
        if (
            not isinstance(decoded, dict)
            or set(decoded) != {"schema", "deployment_id", "registry_sequence", "grant_event", "grant_checkpoint"}
            or canonical_json_bytes(decoded) != raw
            or decoded["schema"] != _SCHEMA
        ):
            raise VerifierRegistryInvalid
        deployment_id = decoded["deployment_id"]
        sequence = decoded["registry_sequence"]
        if (
            not isinstance(deployment_id, str)
            or not _IDENTIFIER.fullmatch(deployment_id)
            or type(sequence) is not int
            or sequence < 1
        ):
            raise VerifierRegistryInvalid
        grant_event = _verifier(decoded["grant_event"])
        checkpoint = _verifier(decoded["grant_checkpoint"])
        if grant_event.key_id == checkpoint.key_id or grant_event.public_key == checkpoint.public_key:
            raise VerifierRegistryInvalid
    except VerifierRegistryInvalid:
        raise
    except (
        UnicodeDecodeError,
        UnicodeEncodeError,
        json.JSONDecodeError,
        ValueError,
        TypeError,
        OverflowError,
        binascii.Error,
    ):
        raise VerifierRegistryInvalid from None
    return ParsedVerifierRegistryV1(
        deployment_id=deployment_id,
        registry_sequence=sequence,
        grant_event=grant_event,
        grant_checkpoint=checkpoint,
        registry_digest="sha256:" + hashlib.sha256(raw).hexdigest(),
    )


__all__ = [
    "MAX_VERIFIER_REGISTRY_BYTES",
    "ParsedVerifierRegistryV1",
    "PublicVerifierV1",
    "VerifierRegistryInvalid",
    "parse_verifier_registry",
]
