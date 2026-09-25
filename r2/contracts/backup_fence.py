"""Canonical wire contracts for an operator-observed backup write fence."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    ValidationError,
)

from .common import NonEmptyStr, ensure_json_value
from .fingerprints import canonical_json_bytes

type ServiceKind = Literal["app", "worker", "recovery_scanner", "gc_cleanup"]
type ServiceObservation = Literal["STOPPED", "DRAINED"]
type ServiceEvidenceType = Literal["SERVICE_MANAGER_STATUS", "OPERATOR_COMMAND_TRANSCRIPT"]
MAX_FENCE_RECORD_BYTES = 1_048_576
_MAX_JSON_DEPTH = 64
_MAX_JSON_NODES = 16_384


class FenceRecordInvalid(ValueError):
    """A submitted fence record is not canonical V1 evidence."""

    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


def _require_utc(value: datetime) -> datetime:
    if value.utcoffset() != timedelta(0):
        raise ValueError("timestamp_must_be_utc")
    return value


def _require_timestamp_text(value: object) -> object:
    if not isinstance(value, str):
        raise ValueError("timestamp_must_be_text")
    return value


def _require_exact_identity(value: object) -> object:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("identity_must_be_exact")
    return value


def _require_integer_one(value: object) -> object:
    if type(value) is not int or value != 1:
        raise ValueError("unsupported_schema_version")
    return value


type ExactIdentity = Annotated[NonEmptyStr, BeforeValidator(_require_exact_identity)]
type UtcTimestamp = Annotated[datetime, BeforeValidator(_require_timestamp_text), AfterValidator(_require_utc)]
type Sha256Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
type SchemaVersion = Annotated[Literal[1], BeforeValidator(_require_integer_one)]


class _FenceModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EvidenceBlobRefV1(_FenceModel):
    store_id: ExactIdentity
    object_ref: ExactIdentity
    object_version: ExactIdentity
    byte_size: int = Field(strict=True, ge=1)
    sha256: Sha256Digest


class ServiceStopEvidenceV1(_FenceModel):
    service_kind: ServiceKind
    instance_id: ExactIdentity
    observed_state: ServiceObservation
    observed_at: UtcTimestamp
    evidence_type: ServiceEvidenceType
    blob: EvidenceBlobRefV1


class PostgresWriterCheckV1(_FenceModel):
    database_id: ExactIdentity
    monitor_session_id: ExactIdentity
    active_writer_sessions: StrictInt = Field(ge=0)
    active_writer_transactions: StrictInt = Field(ge=0)
    checked_at: UtcTimestamp
    blob: EvidenceBlobRefV1


class RootMountCheckV1(_FenceModel):
    root_ids: tuple[ExactIdentity, ...] = Field(min_length=1)
    mount_identities: tuple[ExactIdentity, ...] = Field(min_length=1)
    no_alias: StrictBool
    no_symlink: StrictBool
    checked_at: UtcTimestamp
    blob: EvidenceBlobRefV1


class CaptureFenceStartV1(_FenceModel):
    schema_version: SchemaVersion
    backup_set_id: ExactIdentity
    source_deployment_id: ExactIdentity
    release_git_sha: ExactIdentity
    release_image_digest: Sha256Digest
    db_root_id: ExactIdentity
    file_root_ids: tuple[ExactIdentity, ...] = Field(min_length=1)
    writer_inventory_digest: Sha256Digest
    custodian_id: ExactIdentity
    custodian_role: ExactIdentity
    fence_started_at: UtcTimestamp
    quiescence_confirmed_at: UtcTimestamp
    fence_expires_at: UtcTimestamp
    services: tuple[ServiceStopEvidenceV1, ...] = Field(min_length=1)
    postgres_writer_check: PostgresWriterCheckV1
    root_mount_check: RootMountCheckV1
    signer_key_id: ExactIdentity
    signature: ExactIdentity


class CaptureFenceClosureV1(CaptureFenceStartV1):
    capture_checks_completed_at: UtcTimestamp
    fenced_capture_ended_at: UtcTimestamp


def _unique_object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise FenceRecordInvalid("duplicate_key")
        result[key] = value
    return result


def _reject_nonfinite(_value: str) -> None:
    raise FenceRecordInvalid("nonfinite_number")


def _check_json_shape(value: object) -> None:
    stack: list[tuple[object, int]] = [(value, 0)]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if depth > _MAX_JSON_DEPTH or nodes > _MAX_JSON_NODES:
            raise FenceRecordInvalid("record_shape")
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)


def _valid_record_bytes(value: object) -> bool:
    return isinstance(value, bytes) and 0 < len(value) <= MAX_FENCE_RECORD_BYTES


def parse_canonical_fence_record[FenceModelT: BaseModel](
    raw: bytes, model: type[FenceModelT]
) -> tuple[FenceModelT, dict[str, object]]:
    """Parse exact canonical JSON bytes without discarding signed fields."""

    if not _valid_record_bytes(raw):
        raise FenceRecordInvalid("record_size")
    try:
        decoded = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object_pairs,
            parse_constant=_reject_nonfinite,
        )
        if not isinstance(decoded, dict):
            raise FenceRecordInvalid("top_level_object")
        _check_json_shape(decoded)
        if canonical_json_bytes(ensure_json_value(decoded)) != raw:
            raise FenceRecordInvalid("noncanonical_bytes")
        record = model.model_validate(decoded)
    except FenceRecordInvalid:
        raise
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValidationError,
        TypeError,
        ValueError,
        OverflowError,
        RecursionError,
    ):
        raise FenceRecordInvalid("invalid_record") from None
    return record, decoded


__all__ = [
    "MAX_FENCE_RECORD_BYTES",
    "CaptureFenceClosureV1",
    "CaptureFenceStartV1",
    "EvidenceBlobRefV1",
    "FenceRecordInvalid",
    "PostgresWriterCheckV1",
    "RootMountCheckV1",
    "ServiceEvidenceType",
    "ServiceKind",
    "ServiceObservation",
    "ServiceStopEvidenceV1",
    "parse_canonical_fence_record",
]
