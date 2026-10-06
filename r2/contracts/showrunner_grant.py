"""Canonical signed-event wire contract for project-scoped Showrunner grants."""

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

from lib.content_digest import canonical_json_bytes
from r2.contracts.common import R2ContractModel

MAX_GRANT_EVENT_BYTES = 65_536
_UTC_SECOND = re.compile(r"\A[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
_SIGNATURE = re.compile(r"\A[A-Za-z0-9_-]{86}\Z")

_ExactIdentity = Annotated[str, StringConstraints(min_length=1, pattern=r"^\S(?:.*\S)?$")]
_Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]


class GrantEventInvalid(ValueError):
    """Sanitized rejection of a submitted grant event."""

    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


def _timestamp(value: str) -> datetime:
    if not _UTC_SECOND.fullmatch(value):
        raise ValueError("timestamp")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")


class GrantEventBodyV1(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, serialize_by_alias=True)

    event_schema: Literal["governance.showrunner_grant_event.v1"] = Field(alias="schema")
    event_type: Literal["ISSUE", "REVOKE"]
    user_id: _ExactIdentity
    project_name: _ExactIdentity
    principal: _ExactIdentity
    role: Literal["HUMAN_SHOWRUNNER"]
    sequence: StrictInt = Field(ge=1)
    previous_event_digest: _Digest | None
    issued_at: str
    signer_key_id: _ExactIdentity
    not_before: str | None = None
    expires_at: str | None = None

    @field_validator("user_id", "project_name", "principal", "signer_key_id")
    @classmethod
    def no_wildcard(cls, value: str) -> str:
        if value == "*":
            raise ValueError("wildcard identity")
        return value

    @model_validator(mode="after")
    def valid_transition_shape(self) -> Self:
        issued = _timestamp(self.issued_at)
        if (self.sequence == 1) != (self.previous_event_digest is None):
            raise ValueError("event predecessor")
        if self.event_type == "ISSUE":
            if self.not_before is None or self.expires_at is None:
                raise ValueError("issue window")
            if not issued <= _timestamp(self.not_before) < _timestamp(self.expires_at):
                raise ValueError("issue window")
        elif "not_before" in self.model_fields_set or "expires_at" in self.model_fields_set:
            raise ValueError("revoke window")
        return self


@dataclass(frozen=True)
class ParsedGrantEventV1:
    body: GrantEventBodyV1
    signature: bytes
    signed_bytes: bytes
    event_digest: str


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise GrantEventInvalid("duplicate_key")
        result[key] = value
    return result


def _nonfinite(_value: str) -> None:
    raise GrantEventInvalid("nonfinite_number")


def parse_grant_event(raw: bytes) -> ParsedGrantEventV1:
    """Parse exact wire bytes without trusting or verifying the signature."""

    if not 0 < len(raw) <= MAX_GRANT_EVENT_BYTES:
        raise GrantEventInvalid("event_size")
    try:
        decoded = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs, parse_constant=_nonfinite)
        if not isinstance(decoded, dict) or set(decoded) != {"body", "signature"}:
            raise GrantEventInvalid("envelope_shape")
        if canonical_json_bytes(decoded, allow_nan=False) != raw:
            raise GrantEventInvalid("noncanonical_bytes")
        body_raw = decoded["body"]
        signature_text = decoded["signature"]
        if (
            not isinstance(body_raw, dict)
            or not isinstance(signature_text, str)
            or not _SIGNATURE.fullmatch(signature_text)
        ):
            raise GrantEventInvalid("envelope_shape")
        signature = base64.urlsafe_b64decode(signature_text + "==")
        if len(signature) != 64 or base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=") != signature_text:
            raise GrantEventInvalid("signature_encoding")
        body = GrantEventBodyV1.model_validate(body_raw)
        signed_bytes = canonical_json_bytes(body_raw, allow_nan=False)
    except GrantEventInvalid:
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
        raise GrantEventInvalid("invalid_event") from None
    return ParsedGrantEventV1(
        body=body,
        signature=signature,
        signed_bytes=signed_bytes,
        event_digest="sha256:" + hashlib.sha256(signed_bytes).hexdigest(),
    )


__all__ = ["MAX_GRANT_EVENT_BYTES", "GrantEventBodyV1", "GrantEventInvalid", "ParsedGrantEventV1", "parse_grant_event"]
