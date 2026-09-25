from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from lib.content_digest import canonical_json_bytes
from r2.contracts.backup_fence import (
    CaptureFenceClosureV1,
    CaptureFenceStartV1,
    EvidenceBlobRefV1,
    FenceRecordInvalid,
    parse_canonical_fence_record,
)


def valid_start_mapping() -> dict[str, object]:
    blob = {
        "store_id": "operator-evidence",
        "object_ref": "status/app-1",
        "object_version": "v1",
        "byte_size": 4,
        "sha256": "sha256:" + "a" * 64,
    }
    services = []
    for kind in ("app", "worker", "recovery_scanner", "gc_cleanup"):
        item = {
            "service_kind": kind,
            "instance_id": kind + "-1",
            "observed_state": "STOPPED",
            "observed_at": "2026-09-25T12:00:00Z",
            "evidence_type": "SERVICE_MANAGER_STATUS",
            "blob": {**blob, "object_ref": "status/" + kind + "-1"},
        }
        services.append(item)
    return {
        "schema_version": 1,
        "backup_set_id": "bset-1",
        "source_deployment_id": "deployment-1",
        "release_git_sha": "a" * 40,
        "release_image_digest": "sha256:" + "b" * 64,
        "db_root_id": "db-1",
        "file_root_ids": ["projects-1", "media-1"],
        "writer_inventory_digest": "sha256:" + "c" * 64,
        "custodian_id": "operator-1",
        "custodian_role": "backup-custodian",
        "fence_started_at": "2026-09-25T11:59:00Z",
        "quiescence_confirmed_at": "2026-09-25T12:00:00Z",
        "fence_expires_at": "2026-09-25T12:30:00Z",
        "services": services,
        "postgres_writer_check": {
            "database_id": "db-1",
            "monitor_session_id": "monitor-1",
            "active_writer_sessions": 0,
            "active_writer_transactions": 0,
            "checked_at": "2026-09-25T12:00:00Z",
            "blob": {**blob, "object_ref": "status/postgres"},
        },
        "root_mount_check": {
            "root_ids": ["db-1", "projects-1", "media-1"],
            "mount_identities": ["mount-db", "mount-projects", "mount-media"],
            "no_alias": True,
            "no_symlink": True,
            "checked_at": "2026-09-25T12:00:00Z",
            "blob": {**blob, "object_ref": "status/roots"},
        },
        "signer_key_id": "operator-key-1",
        "signature": "fixture-signature",
    }


def test_canonical_start_round_trips_without_losing_signed_fields() -> None:
    data = valid_start_mapping()
    record, decoded = parse_canonical_fence_record(canonical_json_bytes(data, allow_nan=False), CaptureFenceStartV1)
    assert record.schema_version == 1
    assert record.backup_set_id == "bset-1"
    assert record.signature == "fixture-signature"
    assert decoded == data
    assert len(record.services) == 4


def test_canonical_closure_requires_its_two_end_times() -> None:
    data = valid_start_mapping()
    data["capture_checks_completed_at"] = "2026-09-25T12:08:00Z"
    data["fenced_capture_ended_at"] = "2026-09-25T12:09:00Z"
    record, _ = parse_canonical_fence_record(canonical_json_bytes(data, allow_nan=False), CaptureFenceClosureV1)
    assert record.fenced_capture_ended_at.minute == 9


@pytest.mark.parametrize(
    "raw",
    [b'{"schema_version":1,"schema_version":1}', b'{"schema_version":NaN}', b'{"schema_version":Infinity}'],
)
def test_noncanonical_or_ambiguous_json_rejects_before_model_validation(raw: bytes) -> None:
    with pytest.raises(FenceRecordInvalid):
        parse_canonical_fence_record(raw, CaptureFenceStartV1)


def test_equivalent_whitespace_is_not_the_signed_canonical_body() -> None:
    raw = canonical_json_bytes(valid_start_mapping(), allow_nan=False)
    with pytest.raises(FenceRecordInvalid):
        parse_canonical_fence_record(raw.replace(b'"schema_version":1', b'"schema_version": 1'), CaptureFenceStartV1)


def test_unknown_schema_rejects() -> None:
    data = valid_start_mapping()
    data["schema_version"] = 2
    with pytest.raises(FenceRecordInvalid):
        parse_canonical_fence_record(canonical_json_bytes(data, allow_nan=False), CaptureFenceStartV1)


@pytest.mark.parametrize("version", [True, 1.0, "1"])
def test_schema_version_requires_json_integer_one(version: object) -> None:
    data = valid_start_mapping()
    data["schema_version"] = version
    with pytest.raises(FenceRecordInvalid):
        parse_canonical_fence_record(canonical_json_bytes(data, allow_nan=False), CaptureFenceStartV1)


def test_zero_size_blob_rejects() -> None:
    data = valid_start_mapping()
    blob = data["postgres_writer_check"]
    assert isinstance(blob, dict)
    blob["blob"]["byte_size"] = 0
    with pytest.raises(FenceRecordInvalid):
        parse_canonical_fence_record(canonical_json_bytes(data, allow_nan=False), CaptureFenceStartV1)


def test_naive_timestamp_rejects() -> None:
    data = valid_start_mapping()
    data["fence_started_at"] = "2026-09-25T11:59:00"
    with pytest.raises(FenceRecordInvalid):
        parse_canonical_fence_record(canonical_json_bytes(data, allow_nan=False), CaptureFenceStartV1)


def test_unknown_field_rejects() -> None:
    data = valid_start_mapping()
    data["unsafe_extra"] = "x"
    with pytest.raises(FenceRecordInvalid):
        parse_canonical_fence_record(canonical_json_bytes(data, allow_nan=False), CaptureFenceStartV1)


def test_contracts_are_frozen_and_digest_must_be_lowercase() -> None:
    ref = EvidenceBlobRefV1(
        store_id="operator-evidence",
        object_ref="status/app-1",
        object_version="v1",
        byte_size=4,
        sha256="sha256:" + "a" * 64,
    )
    with pytest.raises(ValidationError):
        ref.byte_size = 5
    with pytest.raises(ValidationError):
        EvidenceBlobRefV1.model_validate({**ref.model_dump(), "sha256": "sha256:" + "A" * 64})


def test_contract_rejects_coerced_size() -> None:
    data = deepcopy(valid_start_mapping())
    writer = data["services"]
    assert isinstance(writer, list)
    writer[0]["blob"]["byte_size"] = "4"
    with pytest.raises(FenceRecordInvalid):
        parse_canonical_fence_record(canonical_json_bytes(data, allow_nan=False), CaptureFenceStartV1)


@pytest.mark.parametrize("timestamp", [1790337540, "2026-09-25T18:59:00+07:00"])
def test_start_time_requires_an_explicit_utc_string(timestamp: object) -> None:
    data = valid_start_mapping()
    data["fence_started_at"] = timestamp
    with pytest.raises(FenceRecordInvalid):
        parse_canonical_fence_record(canonical_json_bytes(data, allow_nan=False), CaptureFenceStartV1)


def test_identity_padding_is_not_silently_normalized() -> None:
    data = valid_start_mapping()
    data["backup_set_id"] = " bset-1 "
    with pytest.raises(FenceRecordInvalid):
        parse_canonical_fence_record(canonical_json_bytes(data, allow_nan=False), CaptureFenceStartV1)


def test_validation_error_does_not_expose_raw_evidence_in_exception_chain() -> None:
    data = valid_start_mapping()
    data["custodian_id"] = "/private/operator-credential"
    data["schema_version"] = 2
    with pytest.raises(FenceRecordInvalid) as exc:
        parse_canonical_fence_record(canonical_json_bytes(data, allow_nan=False), CaptureFenceStartV1)
    assert exc.value.__cause__ is None
    assert "/private/operator-credential" not in str(exc.value)


def test_oversized_record_rejects_before_json_decode() -> None:
    with pytest.raises(FenceRecordInvalid) as exc:
        parse_canonical_fence_record(b" " * 1_048_577, CaptureFenceStartV1)
    assert exc.value.category == "record_size"


def test_deeply_nested_record_rejects_without_recursion_error() -> None:
    raw = b'{"x":' + b"[" * 2_000 + b"0" + b"]" * 2_000 + b"}"
    with pytest.raises(FenceRecordInvalid):
        parse_canonical_fence_record(raw, CaptureFenceStartV1)
