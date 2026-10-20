"""Verify original manual-material bytes with a host-pinned public key."""

from __future__ import annotations

import base64
import hashlib
import json
import re

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from r2.advanced_creative.digests import canonical_json_bytes
from r2.opportunity.errors import OpportunityError, StopCode
from r2.opportunity.manual_admission import PublicationHeader, PublicationReceiptMetadata, SealExpectation

_MATERIAL_DOMAIN = b"m9.manual-material-seal.v1\x00"
_SIGNATURE = re.compile(r"[A-Za-z0-9_-]{86}\Z")


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    body: dict[str, object] = {}
    for key, value in pairs:
        if key in body:
            raise ValueError("duplicate seal key")
        body[key] = value
    return body


def verify_manual_seal(
    raw_seal: bytes,
    actual_bytes: bytes,
    *,
    public_key: bytes,
    expected: SealExpectation,
) -> None:
    """Authenticate exact original bytes and their complete expected custody binding."""
    try:
        if (
            type(raw_seal) is not bytes
            or not 0 < len(raw_seal) <= 65_536
            or type(actual_bytes) is not bytes
            or len(actual_bytes) > 2_097_152
            or type(public_key) is not bytes
            or len(public_key) != 32
        ):
            raise ValueError("invalid material verification input")
        expected = SealExpectation.model_validate(expected.model_dump())
        envelope = json.loads(raw_seal, object_pairs_hook=_object)
        if not isinstance(envelope, dict) or set(envelope) != {"body", "signature"}:
            raise ValueError("invalid seal envelope")
        if canonical_json_bytes(envelope) != raw_seal:
            raise ValueError("seal must use canonical bytes")
        body, encoded = envelope["body"], envelope["signature"]
        if not isinstance(body, dict) or set(body) != {"binding", "material_digest"}:
            raise ValueError("invalid material seal body")
        if not isinstance(encoded, str) or _SIGNATURE.fullmatch(encoded) is None:
            raise ValueError("invalid material signature encoding")
        signature = base64.urlsafe_b64decode(encoded + "==")
        if len(signature) != 64 or base64.urlsafe_b64encode(signature).decode().rstrip("=") != encoded:
            raise ValueError("invalid material signature encoding")
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, _MATERIAL_DOMAIN + canonical_json_bytes(body))
        if canonical_json_bytes(body["binding"]) != canonical_json_bytes(expected):
            raise ValueError("original material binding differs")
        if body["material_digest"] != "sha256:" + hashlib.sha256(actual_bytes).hexdigest():
            raise ValueError("original material bytes differ")
    except UnsupportedAlgorithm:
        raise OpportunityError(StopCode.M9_SOURCE_CAPABILITY_UNAVAILABLE) from None
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError, KeyError, InvalidSignature):
        raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH) from None


def verify_publication_receipt(
    raw_receipt: bytes, *, public_key: bytes, expected: PublicationReceiptMetadata
) -> PublicationHeader:
    """Verify content-free original refs, including after the material access deadline."""
    try:
        if (
            type(raw_receipt) is not bytes
            or not 0 < len(raw_receipt) <= 65_536
            or type(public_key) is not bytes
            or len(public_key) != 32
        ):
            raise ValueError("invalid publication receipt input")
        expected = PublicationReceiptMetadata.model_validate(expected.model_dump())
        raw = json.loads(raw_receipt, object_pairs_hook=_object)
        if canonical_json_bytes(raw) != raw_receipt:
            raise ValueError("publication receipt must be canonical")
        header = PublicationHeader.model_validate(raw)
        body = {"metadata": raw["metadata"], "metadata_digest": raw["metadata_digest"]}
        signature = base64.urlsafe_b64decode(header.signature + "==")
        if len(signature) != 64 or base64.urlsafe_b64encode(signature).decode().rstrip("=") != header.signature:
            raise ValueError("invalid publication receipt signature encoding")
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            signature, b"m9.manual-publication-receipt.v1\x00" + canonical_json_bytes(body)
        )
        if canonical_json_bytes(raw["metadata"]) != canonical_json_bytes(expected):
            raise ValueError("publication receipt binding differs")
        return header
    except UnsupportedAlgorithm:
        raise OpportunityError(StopCode.M9_SOURCE_CAPABILITY_UNAVAILABLE) from None
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError, KeyError, InvalidSignature):
        raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH) from None
