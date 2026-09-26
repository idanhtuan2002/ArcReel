"""Canonical, non-secret V1 configuration fingerprint for H6 recovery."""

from __future__ import annotations

import hashlib
import re
from typing import Annotated, Literal, cast

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictBool, model_validator

from .backup_fence import FenceRecordInvalid, parse_canonical_fence_record
from .common import ensure_json_value
from .fingerprints import canonical_json_bytes


class RecoveryConfigInvalid(ValueError):
    """A configuration record cannot be used as a V1 fingerprint."""

    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


class _RecoveryModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _exact_schema_version(value: object) -> int:
    if type(value) is not int or value != 1:
        raise ValueError("unsupported_schema_version")
    return cast("int", value)


def _logical_id(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value) is None:
        raise ValueError("invalid_logical_id")
    return value


def _sha256_digest(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise ValueError("invalid_sha256_digest")
    return value


def _tool_version(value: object) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 256 or value != value.strip() or not value.isprintable():
        raise ValueError("invalid_tool_version")
    return value


SchemaVersionV1 = Annotated[int, BeforeValidator(_exact_schema_version)]
LogicalId = Annotated[str, BeforeValidator(_logical_id)]
Sha256Digest = Annotated[str, BeforeValidator(_sha256_digest)]
ToolVersion = Annotated[str, BeforeValidator(_tool_version)]

_WRITER_KINDS = frozenset({"app", "worker", "recovery_scanner", "gc_cleanup"})


class ToolIdentityV1(_RecoveryModel):
    version: ToolVersion
    binary_digest: Sha256Digest


class ServiceIdentityV1(_RecoveryModel):
    service_id: LogicalId
    kind: Literal["postgres", "app", "worker", "recovery_scanner", "gc_cleanup", "other"]
    image_digest: Sha256Digest
    can_write: StrictBool
    instance_ids: tuple[LogicalId, ...]

    @model_validator(mode="after")
    def _validate_instances_and_write_role(self) -> ServiceIdentityV1:
        if not self.instance_ids or tuple(sorted(set(self.instance_ids))) != self.instance_ids:
            raise ValueError("invalid_service_instances")
        if self.can_write != (self.kind != "other"):
            raise ValueError("invalid_service_write_role")
        return self


class RecoveryConfigV1(_RecoveryModel):
    schema_version: SchemaVersionV1
    backup_mechanism: Literal["logical_pg_dump_v1"]
    source_deployment_id: LogicalId
    release_git_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$", strict=True)]
    release_image_digest: Sha256Digest
    postgres_server_image_digest: Sha256Digest
    pg_dump: ToolIdentityV1
    pg_restore: ToolIdentityV1
    ffprobe: ToolIdentityV1
    ffmpeg: ToolIdentityV1
    db_root_id: LogicalId
    project_root_id: LogicalId
    media_root_id: LogicalId
    service_inventory: tuple[ServiceIdentityV1, ...]
    writer_inventory_digest: Sha256Digest
    effective_compose_digest: Sha256Digest
    network_egress_policy_digest: Sha256Digest
    provider_route_policy_digest: Sha256Digest
    paid_routes_enabled: StrictBool
    capability_registry_digest: Sha256Digest
    agent_runtime_profile_digest: Sha256Digest

    @model_validator(mode="after")
    def _validate_inventory(self) -> RecoveryConfigV1:
        if self.paid_routes_enabled:
            raise ValueError("paid_routes_unsupported")
        if len({self.db_root_id, self.project_root_id, self.media_root_id}) != 3:
            raise ValueError("aliased_roots")
        services = self.service_inventory
        if not services or tuple(sorted(services, key=lambda item: (item.service_id, item.kind))) != services:
            raise ValueError("unsorted_service_inventory")
        if len({service.service_id for service in services}) != len(services):
            raise ValueError("duplicate_service_id")
        if sum(service.kind == "postgres" for service in services) != 1:
            raise ValueError("invalid_postgres_inventory")
        if not _WRITER_KINDS.issubset({service.kind for service in services}):
            raise ValueError("missing_writer_kind")
        pairs = [(service.kind, instance_id) for service in services for instance_id in service.instance_ids]
        if len(pairs) != len(set(pairs)):
            raise ValueError("duplicate_service_instance")
        writer_pairs = sorted(pair for pair in pairs if pair[0] in _WRITER_KINDS)
        writer_payload = ensure_json_value([list(pair) for pair in writer_pairs])
        expected = "sha256:" + hashlib.sha256(canonical_json_bytes(writer_payload)).hexdigest()
        if self.writer_inventory_digest != expected:
            raise ValueError("writer_inventory_mismatch")
        return self


def parse_recovery_config_v1(raw: bytes) -> tuple[RecoveryConfigV1, str]:
    """Validate canonical configuration bytes and fingerprint their full body."""

    try:
        record, _ = parse_canonical_fence_record(raw, RecoveryConfigV1)
    except FenceRecordInvalid as exc:
        category = exc.category
    else:
        return record, "sha256:" + hashlib.sha256(raw).hexdigest()
    raise RecoveryConfigInvalid(category)


__all__ = [
    "RecoveryConfigInvalid",
    "RecoveryConfigV1",
    "ServiceIdentityV1",
    "ToolIdentityV1",
    "parse_recovery_config_v1",
]
