"""Parse canonical host custody records without assigning operator trust."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, StrictInt, StringConstraints, ValidationError, field_validator, model_validator

from lib.content_digest import canonical_json_bytes
from r2.contracts.common import R2ContractModel

MAX_HOST_RECORD_BYTES = 8_192
_IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$"
_DIGEST = r"^sha256:[0-9a-f]{64}$"
_IMAGE_REF = r"^[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-f]{64}$"
_PLATFORM = r"^linux/[a-z0-9_]+$"
_UTC_SECOND = re.compile(r"\A[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
_Identifier = Annotated[str, StringConstraints(pattern=_IDENTIFIER)]
_Digest = Annotated[str, StringConstraints(pattern=_DIGEST)]


class HostRecordInvalid(ValueError):
    """A bounded host record is unavailable or malformed."""

    def __init__(self) -> None:
        super().__init__("invalid host custody record")


def _timestamp(value: str) -> str:
    if not _UTC_SECOND.fullmatch(value):
        raise ValueError("timestamp")
    datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    return value


class ApprovedDeploymentBodyV1(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, serialize_by_alias=True)

    approval_schema: Literal["governance.approved_deployment.v1"] = Field(alias="schema")
    deployment_id: _Identifier
    approval_sequence: StrictInt = Field(ge=1)
    previous_approval_digest: _Digest | None
    image_ref: Annotated[str, StringConstraints(pattern=_IMAGE_REF)]
    image_platform: Annotated[str, StringConstraints(pattern=_PLATFORM)]
    registry_sequence: StrictInt = Field(ge=1)
    registry_file_digest: _Digest
    grant_event_key_id: _Identifier
    checkpoint_key_id: _Identifier
    approved_at: str
    operator_id: _Identifier

    @field_validator("approved_at")
    @classmethod
    def valid_timestamp(cls, value: str) -> str:
        return _timestamp(value)

    @model_validator(mode="after")
    def valid_predecessor(self) -> Self:
        if (self.approval_sequence == 1) != (self.previous_approval_digest is None):
            raise ValueError("approval predecessor")
        if self.grant_event_key_id == self.checkpoint_key_id:
            raise ValueError("purpose key identity")
        return self


class CheckpointHighWaterBodyV1(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, serialize_by_alias=True)

    high_water_schema: Literal["governance.checkpoint_high_water.v1"] = Field(alias="schema")
    deployment_id: _Identifier
    approved_deployment_digest: _Digest
    checkpoint_sequence: StrictInt = Field(ge=1)
    checkpoint_body_digest: _Digest
    checkpoint_file_digest: _Digest
    previous_checkpoint_body_digest: _Digest | None
    previous_high_water_digest: _Digest | None
    signer_key_id: _Identifier
    checkpoint_issued_at: str
    recorded_at: str
    operator_id: _Identifier

    @field_validator("checkpoint_issued_at", "recorded_at")
    @classmethod
    def valid_timestamp(cls, value: str) -> str:
        return _timestamp(value)

    @model_validator(mode="after")
    def valid_predecessor(self) -> Self:
        if (self.checkpoint_sequence == 1) != (self.previous_checkpoint_body_digest is None):
            raise ValueError("checkpoint predecessor")
        if (self.checkpoint_sequence == 1) != (self.previous_high_water_digest is None):
            raise ValueError("high-water predecessor")
        return self


@dataclass(frozen=True)
class ParsedApprovedDeploymentV1:
    body: ApprovedDeploymentBodyV1
    record_digest: str

    @property
    def deployment_id(self) -> str:
        return self.body.deployment_id

    @property
    def approval_sequence(self) -> int:
        return self.body.approval_sequence


@dataclass(frozen=True)
class ParsedCheckpointHighWaterV1:
    body: CheckpointHighWaterBodyV1
    record_digest: str

    @property
    def deployment_id(self) -> str:
        return self.body.deployment_id

    @property
    def checkpoint_sequence(self) -> int:
        return self.body.checkpoint_sequence


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise HostRecordInvalid
        result[key] = value
    return result


def _nonfinite(_value: str) -> None:
    raise HostRecordInvalid


def _decode(raw: bytes) -> dict[str, object]:
    if not 0 < len(raw) <= MAX_HOST_RECORD_BYTES:
        raise HostRecordInvalid
    try:
        decoded = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs, parse_constant=_nonfinite)
        if not isinstance(decoded, dict) or canonical_json_bytes(decoded, allow_nan=False) != raw:
            raise HostRecordInvalid
        return decoded
    except HostRecordInvalid:
        raise
    except (
        UnicodeDecodeError,
        UnicodeEncodeError,
        json.JSONDecodeError,
        ValueError,
        TypeError,
        OverflowError,
        RecursionError,
    ):
        raise HostRecordInvalid from None


def parse_approved_deployment(raw: bytes) -> ParsedApprovedDeploymentV1:
    """Parse one approval record; the caller checks it against trusted custody."""

    try:
        body = ApprovedDeploymentBodyV1.model_validate(_decode(raw))
    except ValidationError:
        raise HostRecordInvalid from None
    return ParsedApprovedDeploymentV1(body, "sha256:" + hashlib.sha256(raw).hexdigest())


def parse_checkpoint_high_water(raw: bytes) -> ParsedCheckpointHighWaterV1:
    """Parse one high-water record; the caller checks its retained chain."""

    try:
        body = CheckpointHighWaterBodyV1.model_validate(_decode(raw))
    except ValidationError:
        raise HostRecordInvalid from None
    return ParsedCheckpointHighWaterV1(body, "sha256:" + hashlib.sha256(raw).hexdigest())


__all__ = [
    "MAX_HOST_RECORD_BYTES",
    "ApprovedDeploymentBodyV1",
    "CheckpointHighWaterBodyV1",
    "HostRecordInvalid",
    "ParsedApprovedDeploymentV1",
    "ParsedCheckpointHighWaterV1",
    "parse_approved_deployment",
    "parse_checkpoint_high_water",
]
