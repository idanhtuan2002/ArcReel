from __future__ import annotations

import hashlib

from r2.contracts import (
    CANON_SCHEMA_V1,
    CANON_SCHEMA_V2,
    CanonContent,
    CanonDelta,
    CanonDeltaPayload,
    canonical_json_bytes,
    ensure_json_value,
)
from r2.contracts.common import JSONValue

from .errors import CanonIntegrityError, NarrativeSchemaVersionError

_SUPPORTED_ALGORITHM = "sha256"
_SUPPORTED_DELTA_HASH_VERSION = "r2-canon-delta-v1"
_SUPPORTED_CONTENT_HASH_VERSION = "r2-canon-content-v1"
_SUPPORTED_SCHEMA_VERSIONS: frozenset[str] = frozenset({CANON_SCHEMA_V1, CANON_SCHEMA_V2})

_V1_CONTENT_FIELDS = {"entities_by_id", "facts_by_id", "events_by_id"}
_V2_ONLY_CONTENT_FIELDS = {
    "epistemic_propositions_by_ref",
    "knowledge_states_by_id",
    "temporal_relations_by_id",
}


def _require_supported_selectors(*, kind: str, algorithm: str, hash_version: str, schema_version: str) -> None:
    expected_hash_version = _SUPPORTED_DELTA_HASH_VERSION if kind == "delta" else _SUPPORTED_CONTENT_HASH_VERSION
    if algorithm != _SUPPORTED_ALGORITHM:
        raise CanonIntegrityError(f"unsupported Canon {kind} hash algorithm {algorithm!r}")
    if hash_version != expected_hash_version:
        raise CanonIntegrityError(f"unsupported Canon {kind} hash version {hash_version!r}")
    if schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
        raise CanonIntegrityError(f"unsupported Canon {kind} schema version {schema_version!r}")


def canonical_canon_content_payload(content: CanonContent, *, schema_version: str) -> JSONValue:
    """Serialize Canon content under an explicit schema selector.

    ``r2-canon-schema-v1`` emits only the Entity/Fact/Event maps, so a v1 version keeps its
    recorded content hash even after the v2 maps exist on the model. ``r2-canon-schema-v2``
    additionally emits the epistemic/temporal maps. The base schema is never inferred from
    whether the v2 maps happen to be empty.
    """
    common = content.model_dump(mode="json", include=set(_V1_CONTENT_FIELDS))
    if schema_version == CANON_SCHEMA_V1:
        return ensure_json_value(common)
    if schema_version == CANON_SCHEMA_V2:
        extra = content.model_dump(mode="json", include=set(_V2_ONLY_CONTENT_FIELDS))
        return ensure_json_value({**common, **extra})
    raise NarrativeSchemaVersionError(f"unsupported Canon content schema version {schema_version!r}")


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
    payload = canonical_canon_content_payload(content, schema_version=schema_version)
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


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
