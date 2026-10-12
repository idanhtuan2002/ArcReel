"""Canonical signed checkpoint bytes for exact Governance grant heads."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, StrictInt, StringConstraints, ValidationError, field_validator, model_validator

from r2.contracts.common import R2ContractModel
from r2.contracts.fingerprints import canonical_json_bytes

MAX_GRANT_CHECKPOINT_BYTES = 4_194_304
MAX_GRANT_CHECKPOINT_HEADS = 10_000
_UTC_SECOND = re.compile(r"\A[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
_SIGNATURE = re.compile(r"\A[A-Za-z0-9_-]{86}\Z")
_ExactIdentity = Annotated[str, StringConstraints(min_length=1, pattern=r"^\S(?:.*\S)?$")]
_Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]


class CheckpointInvalid(ValueError):
    """Sanitized rejection of a submitted grant-head checkpoint."""

    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


def _timestamp(value: str) -> None:
    if not _UTC_SECOND.fullmatch(value):
        raise ValueError("timestamp")
    datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")


class GrantHeadRecordV1(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    user_id: _ExactIdentity
    project_name: _ExactIdentity
    principal: _ExactIdentity
    head_sequence: StrictInt = Field(ge=1)
    head_event_digest: _Digest

    @field_validator("user_id", "project_name", "principal")
    @classmethod
    def no_wildcard(cls, value: str) -> str:
        if value == "*":
            raise ValueError("wildcard identity")
        return value


class GrantHeadCheckpointBodyV1(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, serialize_by_alias=True)

    checkpoint_schema: Literal["governance.grant_head_checkpoint.v1"] = Field(alias="schema")
    deployment_id: _ExactIdentity
    checkpoint_sequence: StrictInt = Field(ge=1)
    previous_checkpoint_digest: _Digest | None
    issued_at: str
    signer_key_id: _ExactIdentity
    heads: tuple[GrantHeadRecordV1, ...]

    @field_validator("deployment_id", "signer_key_id")
    @classmethod
    def no_wildcard(cls, value: str) -> str:
        if value == "*":
            raise ValueError("wildcard identity")
        return value

    @model_validator(mode="after")
    def valid_checkpoint_shape(self) -> Self:
        _timestamp(self.issued_at)
        if (self.checkpoint_sequence == 1) != (self.previous_checkpoint_digest is None):
            raise ValueError("checkpoint predecessor")
        scopes = [(head.user_id, head.project_name, head.principal) for head in self.heads]
        if scopes != sorted(set(scopes)):
            raise ValueError("checkpoint heads are not unique and sorted")
        return self


@dataclass(frozen=True)
class ParsedGrantCheckpointV1:
    body: GrantHeadCheckpointBodyV1
    signature: bytes
    signed_bytes: bytes
    checkpoint_digest: str


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CheckpointInvalid("duplicate_key")
        result[key] = value
    return result


def _nonfinite(_value: str) -> None:
    raise CheckpointInvalid("nonfinite_number")


def parse_grant_checkpoint(raw: bytes) -> ParsedGrantCheckpointV1:
    """Parse exact wire bytes without trusting or verifying the signature."""

    if not 0 < len(raw) <= MAX_GRANT_CHECKPOINT_BYTES:
        raise CheckpointInvalid("checkpoint_size")
    try:
        decoded = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs, parse_constant=_nonfinite)
        if not isinstance(decoded, dict) or set(decoded) != {"body", "signature"}:
            raise CheckpointInvalid("envelope_shape")
        if canonical_json_bytes(decoded) != raw:
            raise CheckpointInvalid("noncanonical_bytes")
        body_raw = decoded["body"]
        signature_text = decoded["signature"]
        if (
            not isinstance(body_raw, dict)
            or not isinstance(signature_text, str)
            or not _SIGNATURE.fullmatch(signature_text)
        ):
            raise CheckpointInvalid("envelope_shape")
        heads = body_raw.get("heads")
        if isinstance(heads, list) and len(heads) > MAX_GRANT_CHECKPOINT_HEADS:
            raise CheckpointInvalid("scope_count")
        signature = base64.urlsafe_b64decode(signature_text + "==")
        if len(signature) != 64 or base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=") != signature_text:
            raise CheckpointInvalid("signature_encoding")
        signed_bytes = canonical_json_bytes(body_raw)
        body = GrantHeadCheckpointBodyV1.model_validate_json(signed_bytes)
    except CheckpointInvalid:
        raise
    except (
        UnicodeDecodeError,
        UnicodeEncodeError,
        json.JSONDecodeError,
        ValidationError,
        ValueError,
        TypeError,
        OverflowError,
        RecursionError,
        binascii.Error,
    ):
        raise CheckpointInvalid("invalid_checkpoint") from None
    return ParsedGrantCheckpointV1(
        body=body,
        signature=signature,
        signed_bytes=signed_bytes,
        checkpoint_digest="sha256:" + hashlib.sha256(signed_bytes).hexdigest(),
    )


__all__ = [
    "MAX_GRANT_CHECKPOINT_BYTES",
    "MAX_GRANT_CHECKPOINT_HEADS",
    "CheckpointInvalid",
    "GrantHeadCheckpointBodyV1",
    "GrantHeadRecordV1",
    "ParsedGrantCheckpointV1",
    "parse_grant_checkpoint",
]
