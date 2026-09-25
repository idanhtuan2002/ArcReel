from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from lib.content_digest import canonical_json_bytes, canonical_json_digest
from r2.contracts.backup_fence import CaptureFenceStartV1, EvidenceBlobRefV1
from r2.host_hardening.fence_evidence import (
    FenceEvidenceError,
    FenceExpectationV1,
    FenceFailureCode,
    verify_capture_fence_closure,
    verify_capture_fence_start,
)
from tests.unit.r2.contracts.test_backup_fence import valid_start_mapping

_BLOB = b"stopped and independently observed"
_KINDS = ("app", "worker", "recovery_scanner", "gc_cleanup")


class MemoryReader:
    def __init__(self, blobs: dict[tuple[str, str, str], bytes]) -> None:
        self.blobs = blobs
        self.calls: list[tuple[str, str, str, int]] = []

    def read_exact(self, ref: EvidenceBlobRefV1, *, max_bytes: int) -> bytes:
        self.calls.append((ref.store_id, ref.object_ref, ref.object_version, max_bytes))
        return self.blobs[(ref.store_id, ref.object_ref, ref.object_version)]


class FixtureSignatures:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes, str]] = []

    def verify_ed25519(self, key_id: str, payload: bytes, signature: str) -> bool:
        self.calls.append((key_id, payload, signature))
        return key_id == "operator-key-1" and signature == hashlib.sha256(payload).hexdigest()


def valid_expectation() -> FenceExpectationV1:
    return FenceExpectationV1(
        backup_set_id="bset-1",
        source_deployment_id="deployment-1",
        release_git_sha="a" * 40,
        release_image_digest="sha256:" + "b" * 64,
        db_root_id="db-1",
        file_root_ids=("projects-1", "media-1"),
        approved_writers=tuple((kind, kind + "-1") for kind in _KINDS),
        allowed_signer_ids=frozenset({"operator-key-1"}),
        allowed_evidence_store_ids=frozenset({"operator-evidence"}),
        custodian_id="operator-1",
        custodian_role="backup-custodian",
        evaluated_at=datetime(2026, 9, 25, 12, 5, tzinfo=UTC),
    )


def signed_start() -> tuple[bytes, MemoryReader, FixtureSignatures]:
    data = deepcopy(valid_start_mapping())
    data["writer_inventory_digest"] = "sha256:" + canonical_json_digest(
        sorted([kind, kind + "-1"] for kind in _KINDS), allow_nan=False
    )
    blobs: dict[tuple[str, str, str], bytes] = {}
    items: list[dict[str, Any]] = list(data["services"])
    items.extend((data["postgres_writer_check"], data["root_mount_check"]))
    for item in items:
        blob = item["blob"]
        blob["byte_size"] = len(_BLOB)
        blob["sha256"] = "sha256:" + hashlib.sha256(_BLOB).hexdigest()
        blobs[(blob["store_id"], blob["object_ref"], blob["object_version"])] = _BLOB
    unsigned = {key: value for key, value in data.items() if key != "signature"}
    data["signature"] = hashlib.sha256(canonical_json_bytes(unsigned, allow_nan=False)).hexdigest()
    return canonical_json_bytes(data, allow_nan=False), MemoryReader(blobs), FixtureSignatures()


def altered_start(raw: bytes, **changes: object) -> bytes:
    import json

    data = json.loads(raw)
    data.update(changes)
    unsigned = {key: value for key, value in data.items() if key != "signature"}
    data["signature"] = hashlib.sha256(canonical_json_bytes(unsigned, allow_nan=False)).hexdigest()
    return canonical_json_bytes(data, allow_nan=False)


def test_valid_start_verifies_signature_and_all_versioned_blobs() -> None:
    raw, reader, signatures = signed_start()
    record = verify_capture_fence_start(raw, expected=valid_expectation(), reader=reader, signatures=signatures)
    assert record.backup_set_id == "bset-1"
    assert len(reader.calls) == 6
    assert all(call[0] == "operator-evidence" and call[2] == "v1" for call in reader.calls)
    assert len(signatures.calls) == 1


def test_absent_start_is_typed_and_has_no_side_effects() -> None:
    class UnusedPort:
        def __getattr__(self, name: str) -> Any:
            raise AssertionError(f"unexpected port access: {name}")

    with pytest.raises(FenceEvidenceError) as exc:
        verify_capture_fence_start(None, expected=UnusedPort(), reader=UnusedPort(), signatures=UnusedPort())
    assert exc.value.code is FenceFailureCode.BACKUP_FENCE_EVIDENCE_INVALID


@pytest.mark.parametrize(
    "change",
    [
        {"backup_set_id": "other-set"},
        {"source_deployment_id": "other-deployment"},
        {"release_git_sha": "f" * 40},
        {"release_image_digest": "sha256:" + "f" * 64},
        {"db_root_id": "other-db"},
        {"file_root_ids": ["other-root"]},
        {"signer_key_id": "untrusted-key"},
        {"custodian_id": "forged-operator"},
        {"writer_inventory_digest": "sha256:" + "0" * 64},
        {"fence_expires_at": "2026-09-25T12:04:00Z"},
    ],
)
def test_independent_identity_trust_and_window_mismatches_reject(change: dict[str, object]) -> None:
    raw, reader, signatures = signed_start()
    with pytest.raises(FenceEvidenceError) as exc:
        verify_capture_fence_start(
            altered_start(raw, **change), expected=valid_expectation(), reader=reader, signatures=signatures
        )
    assert exc.value.code is FenceFailureCode.BACKUP_FENCE_EVIDENCE_INVALID


@pytest.mark.parametrize("mutation", ["missing_writer", "db_writer", "root_alias", "root_symlink", "duplicate_writer"])
def test_incomplete_or_unfenced_writer_state_rejects(mutation: str) -> None:
    import json

    raw, reader, signatures = signed_start()
    data = json.loads(raw)
    if mutation == "missing_writer":
        data["services"].pop()
    elif mutation == "duplicate_writer":
        data["services"].append(data["services"][0])
    elif mutation == "db_writer":
        data["postgres_writer_check"]["active_writer_sessions"] = 1
    elif mutation == "root_alias":
        data["root_mount_check"]["no_alias"] = False
    else:
        data["root_mount_check"]["no_symlink"] = False
    with pytest.raises(FenceEvidenceError) as exc:
        verify_capture_fence_start(
            altered_start(canonical_json_bytes(data, allow_nan=False)),
            expected=valid_expectation(),
            reader=reader,
            signatures=signatures,
        )
    assert exc.value.code is FenceFailureCode.BACKUP_FENCE_EVIDENCE_INVALID


@pytest.mark.parametrize(
    "mutation", ["missing", "changed", "wrong_size", "oversized", "overread", "untrusted_store", "reused_ref"]
)
def test_blob_integrity_and_bounds_reject(mutation: str) -> None:
    import json

    raw, reader, signatures = signed_start()
    data = json.loads(raw)
    first_ref = data["services"][0]["blob"]
    key = (first_ref["store_id"], first_ref["object_ref"], first_ref["object_version"])
    if mutation == "missing":
        del reader.blobs[key]
    elif mutation == "changed":
        reader.blobs[key] = b"tampered secret evidence"
    elif mutation == "wrong_size":
        first_ref["byte_size"] += 1
    elif mutation == "oversized":
        first_ref["byte_size"] = 65_537
    elif mutation == "overread":
        reader.blobs[key] = _BLOB + b"extra"
    elif mutation == "reused_ref":
        data["services"][1]["blob"] = first_ref
    else:
        first_ref["store_id"] = "attacker-store"
    with pytest.raises(FenceEvidenceError) as exc:
        verify_capture_fence_start(
            altered_start(canonical_json_bytes(data, allow_nan=False)),
            expected=valid_expectation(),
            reader=reader,
            signatures=signatures,
        )
    assert exc.value.code is FenceFailureCode.BACKUP_FENCE_EVIDENCE_INVALID
    assert "tampered secret evidence" not in str(exc.value)
    assert "/" not in str(exc.value)


def test_invalid_signature_and_malformed_record_reject_without_reading() -> None:
    raw, reader, signatures = signed_start()
    import json

    data = json.loads(raw)
    data["signature"] = "invalid"
    with pytest.raises(FenceEvidenceError):
        verify_capture_fence_start(
            canonical_json_bytes(data, allow_nan=False),
            expected=valid_expectation(),
            reader=reader,
            signatures=signatures,
        )
    assert reader.calls == []
    with pytest.raises(FenceEvidenceError):
        verify_capture_fence_start(
            b'{"schema_version":1,"schema_version":1}',
            expected=valid_expectation(),
            reader=reader,
            signatures=signatures,
        )
    assert reader.calls == []


def test_port_failures_do_not_retain_sensitive_exception_context() -> None:
    raw, reader, signatures = signed_start()

    class FailingReader(MemoryReader):
        def read_exact(self, ref: EvidenceBlobRefV1, *, max_bytes: int) -> bytes:
            raise ValueError("/private/operator/transcript")

    class FailingSignatures(FixtureSignatures):
        def verify_ed25519(self, key_id: str, payload: bytes, signature: str) -> bool:
            raise ValueError("/private/operator/key")

    with pytest.raises(FenceEvidenceError) as signature_error:
        verify_capture_fence_start(raw, expected=valid_expectation(), reader=reader, signatures=FailingSignatures())
    assert signature_error.value.__context__ is None
    with pytest.raises(FenceEvidenceError) as reader_error:
        verify_capture_fence_start(raw, expected=valid_expectation(), reader=FailingReader({}), signatures=signatures)
    assert reader_error.value.__context__ is None


def valid_start() -> CaptureFenceStartV1:
    raw, reader, signatures = signed_start()
    return verify_capture_fence_start(raw, expected=valid_expectation(), reader=reader, signatures=signatures)


def closure_expectation() -> FenceExpectationV1:
    return replace(valid_expectation(), evaluated_at=datetime(2026, 9, 25, 12, 10, tzinfo=UTC))


def unused_reader() -> MemoryReader:
    return MemoryReader({})


def unused_signatures() -> FixtureSignatures:
    return FixtureSignatures()


def signed_closure() -> tuple[bytes, CaptureFenceStartV1, MemoryReader, FixtureSignatures]:
    import json

    start_raw, reader, signatures = signed_start()
    start = verify_capture_fence_start(start_raw, expected=valid_expectation(), reader=reader, signatures=signatures)
    reader.calls.clear()
    signatures.calls.clear()
    data = json.loads(start_raw)
    items = [*data["services"], data["postgres_writer_check"], data["root_mount_check"]]
    for item in items:
        item["observed_at" if "service_kind" in item else "checked_at"] = "2026-09-25T12:08:30Z"
        item["blob"]["object_version"] = "v2"
        ref = item["blob"]
        reader.blobs[(ref["store_id"], ref["object_ref"], ref["object_version"])] = _BLOB
    data["capture_checks_completed_at"] = "2026-09-25T12:08:00Z"
    data["fenced_capture_ended_at"] = "2026-09-25T12:09:00Z"
    return altered_start(canonical_json_bytes(data, allow_nan=False)), start, reader, signatures


def test_valid_closure_checks_all_final_immutable_versions() -> None:
    raw, start, reader, signatures = signed_closure()
    closure = verify_capture_fence_closure(
        raw, start=start, expected=closure_expectation(), reader=reader, signatures=signatures
    )
    assert closure.fenced_capture_ended_at.minute == 9
    assert len(reader.calls) == 6
    assert all(call[2] == "v2" for call in reader.calls)
    assert len(signatures.calls) == 1


def test_closure_missing_is_not_a_window_end() -> None:
    with pytest.raises(FenceEvidenceError) as exc:
        verify_capture_fence_closure(
            None,
            start=valid_start(),
            expected=closure_expectation(),
            reader=unused_reader(),
            signatures=unused_signatures(),
        )
    assert exc.value.code is FenceFailureCode.BACKUP_FENCE_EVIDENCE_INVALID


@pytest.mark.parametrize(
    "change",
    [
        {"backup_set_id": "other-set"},
        {"source_deployment_id": "other-deployment"},
        {"release_git_sha": "f" * 40},
        {"file_root_ids": ["other-root"]},
        {"writer_inventory_digest": "sha256:" + "0" * 64},
        {"fence_started_at": "2026-09-25T11:58:00Z"},
        {"fence_expires_at": "2026-09-25T12:31:00Z"},
        {"fenced_capture_ended_at": "2026-09-25T12:31:00Z"},
        {"fenced_capture_ended_at": "2026-09-25T12:07:00Z"},
    ],
)
def test_closure_identity_or_window_drift_rejects(change: dict[str, object]) -> None:
    raw, start, reader, signatures = signed_closure()
    with pytest.raises(FenceEvidenceError) as exc:
        verify_capture_fence_closure(
            altered_start(raw, **change),
            start=start,
            expected=closure_expectation(),
            reader=reader,
            signatures=signatures,
        )
    assert exc.value.code is FenceFailureCode.BACKUP_FENCE_EVIDENCE_INVALID


@pytest.mark.parametrize(
    "mutation", ["missing_blob", "tampered_blob", "incomplete_writers", "db_writer", "bad_signature"]
)
def test_closure_final_evidence_rejects_failures(mutation: str) -> None:
    import json

    raw, start, reader, signatures = signed_closure()
    data = json.loads(raw)
    if mutation == "missing_blob":
        ref = data["services"][0]["blob"]
        del reader.blobs[(ref["store_id"], ref["object_ref"], ref["object_version"])]
    elif mutation == "tampered_blob":
        ref = data["root_mount_check"]["blob"]
        reader.blobs[(ref["store_id"], ref["object_ref"], ref["object_version"])] = b"wrong status"
    elif mutation == "incomplete_writers":
        data["services"].pop()
    elif mutation == "db_writer":
        data["postgres_writer_check"]["active_writer_transactions"] = 1
    else:
        data["signature"] = "invalid"
    if mutation != "bad_signature":
        raw = altered_start(canonical_json_bytes(data, allow_nan=False))
    else:
        raw = canonical_json_bytes(data, allow_nan=False)
    with pytest.raises(FenceEvidenceError) as exc:
        verify_capture_fence_closure(
            raw, start=start, expected=closure_expectation(), reader=reader, signatures=signatures
        )
    assert exc.value.code is FenceFailureCode.BACKUP_FENCE_EVIDENCE_INVALID


def test_expectation_cannot_alias_database_and_file_root() -> None:
    raw, reader, signatures = signed_start()
    expected = replace(valid_expectation(), file_root_ids=("db-1", "media-1"))
    with pytest.raises(FenceEvidenceError) as exc:
        verify_capture_fence_start(raw, expected=expected, reader=reader, signatures=signatures)
    assert exc.value.code is FenceFailureCode.BACKUP_FENCE_EVIDENCE_INVALID
    assert exc.value.category == "expectation"


@pytest.mark.parametrize("mutation", ["replay_start_ref", "switch_approved_store"])
def test_closure_must_capture_new_evidence_in_the_start_store(mutation: str) -> None:
    import json

    raw, start, reader, signatures = signed_closure()
    data = json.loads(raw)
    ref = data["services"][0]["blob"]
    if mutation == "replay_start_ref":
        ref["object_version"] = "v1"
    else:
        original = (ref["store_id"], ref["object_ref"], ref["object_version"])
        ref["store_id"] = "alternate-evidence"
        reader.blobs[(ref["store_id"], ref["object_ref"], ref["object_version"])] = reader.blobs[original]
    expected = replace(
        closure_expectation(), allowed_evidence_store_ids=frozenset({"operator-evidence", "alternate-evidence"})
    )
    with pytest.raises(FenceEvidenceError) as exc:
        verify_capture_fence_closure(
            altered_start(canonical_json_bytes(data, allow_nan=False)),
            start=start,
            expected=expected,
            reader=reader,
            signatures=signatures,
        )
    assert exc.value.code is FenceFailureCode.BACKUP_FENCE_EVIDENCE_INVALID
