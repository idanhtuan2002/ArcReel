from __future__ import annotations

import hashlib

from r2.contracts import (
    CanonContent,
    CanonDelta,
    CanonDeltaPayload,
    canonical_json_bytes,
    ensure_json_value,
)

from .errors import CanonIntegrityError

_SUPPORTED_ALGORITHM = "sha256"
_SUPPORTED_DELTA_HASH_VERSION = "r2-canon-delta-v1"
_SUPPORTED_CONTENT_HASH_VERSION = "r2-canon-content-v1"
_SUPPORTED_SCHEMA_VERSION = "r2-canon-schema-v1"


def _require_supported_selectors(*, kind: str, algorithm: str, hash_version: str, schema_version: str) -> None:
    expected_hash_version = _SUPPORTED_DELTA_HASH_VERSION if kind == "delta" else _SUPPORTED_CONTENT_HASH_VERSION
    if algorithm != _SUPPORTED_ALGORITHM:
        raise CanonIntegrityError(f"unsupported Canon {kind} hash algorithm {algorithm!r}")
    if hash_version != expected_hash_version:
        raise CanonIntegrityError(f"unsupported Canon {kind} hash version {hash_version!r}")
    if schema_version != _SUPPORTED_SCHEMA_VERSION:
        raise CanonIntegrityError(f"unsupported Canon {kind} schema version {schema_version!r}")


def compute_canon_delta_hash(payload: CanonDeltaPayload) -> str:
    _require_supported_selectors(
        kind="delta",
        algorithm=payload.payload_hash_algorithm,
        hash_version=payload.payload_hash_version,
        schema_version=payload.content_schema_version,
    )
    value = {
        "canon_delta_id": payload.canon_delta_id,
        "target_branch_id": payload.target_branch_id,
        "base_canon_version_id": payload.base_canon_version_id,
        "operations": [operation.model_dump(mode="json") for operation in payload.operations],
        "source_change_set_refs": sorted(set(payload.source_change_set_refs)),
        "author_decision_refs": sorted(set(payload.author_decision_refs)),
        "validation_report_refs": sorted(set(payload.validation_report_refs)),
        "payload_hash_version": payload.payload_hash_version,
        "content_schema_version": payload.content_schema_version,
    }
    return hashlib.sha256(canonical_json_bytes(ensure_json_value(value))).hexdigest()


def seal_canon_delta(payload: CanonDeltaPayload) -> CanonDelta:
    return CanonDelta.model_validate(
        {**payload.model_dump(mode="json"), "payload_hash": compute_canon_delta_hash(payload)}
    )


def verify_canon_delta_hash(delta: CanonDelta) -> None:
    recomputed = compute_canon_delta_hash(delta)
    if recomputed != delta.payload_hash:
        raise CanonIntegrityError(
            f"Canon delta payload hash mismatch: stored {delta.payload_hash!r}, recomputed {recomputed!r}"
        )


def compute_canon_content_hash(
    content: CanonContent,
    *,
    algorithm: str = "sha256",
    hash_version: str = "r2-canon-content-v1",
    schema_version: str = "r2-canon-schema-v1",
) -> str:
    _require_supported_selectors(
        kind="content", algorithm=algorithm, hash_version=hash_version, schema_version=schema_version
    )
    return hashlib.sha256(canonical_json_bytes(ensure_json_value(content.model_dump(mode="json")))).hexdigest()


def verify_canon_content_hash(
    content: CanonContent,
    *,
    expected_hash: str,
    algorithm: str,
    hash_version: str,
    schema_version: str,
) -> None:
    recomputed = compute_canon_content_hash(
        content, algorithm=algorithm, hash_version=hash_version, schema_version=schema_version
    )
    if recomputed != expected_hash:
        raise CanonIntegrityError(f"Canon content hash mismatch: expected {expected_hash!r}, recomputed {recomputed!r}")
