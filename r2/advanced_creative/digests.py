"""Canonical JSON bytes and the M8 version-1 domain digests (spec §3 item 10, §4).

Canonical bytes are UTF-8 JSON with no whitespace, unescaped Unicode, lexicographically sorted
object keys and arrays in order. Integers are base-10. Finite decimals use fixed notation with
trailing fractional zeroes removed and negative zero written as ``0``. Timestamps are
timezone-aware and written in UTC. A digest is ``sha256:`` plus the lowercase hex of those bytes.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from fractions import Fraction

from pydantic import BaseModel

from r2.contracts.advanced_creative import CandidatePayload, CanonicalJsonObject, LineageBinding

CONTRACT_VERSION = "1"


def _number(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("canonical JSON numbers must be finite")
    if value == 0:
        return "0"
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _encode(value: object) -> str:
    if isinstance(value, CanonicalJsonObject):
        return _encode(value.model_dump(mode="python"))
    if isinstance(value, BaseModel):
        return _encode(value.model_dump(mode="python"))
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Enum):
        return _encode(value.value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _number(Decimal(str(value)))
    if isinstance(value, Decimal):
        return _number(value)
    if isinstance(value, Fraction):
        return json.dumps(f"{value.numerator}/{value.denominator}")
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("canonical timestamps must be timezone-aware")
        return json.dumps(value.astimezone(UTC).isoformat().replace("+00:00", "Z"))
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("canonical JSON object keys must be strings")
        items = sorted(value.items())
        return "{" + ",".join(f"{json.dumps(key, ensure_ascii=False)}:{_encode(item)}" for key, item in items) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_encode(item) for item in value) + "]"
    raise ValueError(f"{type(value).__name__} is outside the canonical JSON domain")


def canonical_json_bytes(value: object) -> bytes:
    return _encode(value).encode("utf-8")


def digest_canonical(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def digest_payload(payload: CandidatePayload, lineage: LineageBinding) -> str:
    """The revision payload digest: exactly ``{contract_version, kind, payload, lineage}``."""
    return digest_canonical(
        {"contract_version": CONTRACT_VERSION, "kind": payload.kind, "payload": payload, "lineage": lineage}
    )


def digest_command(operation: str, user_id: str, project_name: str, actor_scope: str, request: object) -> str:
    return digest_canonical(
        {
            "contract_version": CONTRACT_VERSION,
            "operation": operation,
            "user_id": user_id,
            "project_name": project_name,
            "actor_scope": actor_scope,
            "request": request,
        }
    )


__all__ = ["CONTRACT_VERSION", "canonical_json_bytes", "digest_canonical", "digest_command", "digest_payload"]
