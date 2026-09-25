from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from lib.content_digest import canonical_json_bytes, canonical_json_digest
from r2.contracts.backup_fence import (
    EvidenceBlobRefV1,
    PostgresWriterCheckV1,
    RootMountCheckV1,
    ServiceStopEvidenceV1,
)
from r2.host_hardening.fence_evidence import (
    EvidenceSemantics,
    FenceEvidenceError,
    FenceExpectationV1,
    FenceFailureCode,
    verify_capture_fence_closure,
    verify_capture_fence_start,
)
from tests.unit.r2.contracts.test_backup_fence import valid_start_mapping

_KINDS = ("app", "worker", "recovery_scanner", "gc_cleanup")


def _observation_body(item: dict[str, Any]) -> bytes:
    if "service_kind" in item:
        payload = {
            "evidence_type": item["evidence_type"],
            "service_kind": item["service_kind"],
            "instance_id": item["instance_id"],
            "observed_state": item["observed_state"],
            "observed_at": item["observed_at"],
        }
    elif "database_id" in item:
        payload = {
            "evidence_type": "POSTGRES_WRITER_SESSION_CHECK",
            "database_id": item["database_id"],
            "monitor_session_id": item["monitor_session_id"],
            "active_writer_sessions": item["active_writer_sessions"],
            "active_writer_transactions": item["active_writer_transactions"],
            "checked_at": item["checked_at"],
        }
    else:
        payload = {
            "evidence_type": "ROOT_MOUNT_IDENTITY_CHECK",
            "root_ids": item["root_ids"],
            "mount_identities": item["mount_identities"],
            "no_alias": item["no_alias"],
            "no_symlink": item["no_symlink"],
            "checked_at": item["checked_at"],
        }
    return canonical_json_bytes(payload, allow_nan=False)


class FixtureSemantics:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def validate_service(self, item: ServiceStopEvidenceV1, blob: bytes) -> bool:
        self.calls.append("service")
        return blob == _observation_body(item.model_dump(mode="json"))

    def validate_postgres(self, item: PostgresWriterCheckV1, blob: bytes) -> bool:
        self.calls.append("postgres")
        return blob == _observation_body(item.model_dump(mode="json"))

    def validate_roots(self, item: RootMountCheckV1, blob: bytes) -> bool:
        self.calls.append("roots")
        return blob == _observation_body(item.model_dump(mode="json"))


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
        body = _observation_body(item)
        blob["byte_size"] = len(body)
        blob["sha256"] = "sha256:" + hashlib.sha256(body).hexdigest()
        blobs[(blob["store_id"], blob["object_ref"], blob["object_version"])] = body
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
    semantics: EvidenceSemantics = FixtureSemantics()
    record = verify_capture_fence_start(
        raw, expected=valid_expectation(), reader=reader, signatures=signatures, semantics=semantics
    )
    assert record.backup_set_id == "bset-1"
    assert len(reader.calls) == 6
    assert all(call[0] == "operator-evidence" and call[2] == "v1" for call in reader.calls)
    assert len(signatures.calls) == 1
    assert isinstance(semantics, FixtureSemantics)
    assert semantics.calls == ["service"] * 4 + ["postgres", "roots"]


@pytest.mark.parametrize("kind", ["service", "postgres", "roots"])
def test_hash_valid_but_semantically_contradictory_blob_rejects(kind: str) -> None:
    import json

    raw, reader, signatures = signed_start()
    data = json.loads(raw)
    item = (
        data["services"][0]
        if kind == "service"
        else data["postgres_writer_check"]
        if kind == "postgres"
        else data["root_mount_check"]
    )
    ref = item["blob"]
    contradictory = b"ALL SERVICES RUNNING; WRITERS ACTIVE; MOUNT REPLACED"
    ref["byte_size"] = len(contradictory)
    ref["sha256"] = "sha256:" + hashlib.sha256(contradictory).hexdigest()
    reader.blobs[(ref["store_id"], ref["object_ref"], ref["object_version"])] = contradictory
    with pytest.raises(FenceEvidenceError) as exc:
        verify_capture_fence_start(
            altered_start(canonical_json_bytes(data, allow_nan=False)),
            expected=valid_expectation(),
            reader=reader,
            signatures=signatures,
            semantics=FixtureSemantics(),
        )
    assert exc.value.code is FenceFailureCode.BACKUP_FENCE_EVIDENCE_INVALID


def test_missing_or_throwing_semantic_inspector_is_typed() -> None:
    raw, reader, signatures = signed_start()

    class ThrowingSemantics(FixtureSemantics):
        def validate_service(self, item: ServiceStopEvidenceV1, blob: bytes) -> bool:
            raise ValueError("/private/operator/command-output")

    with pytest.raises(FenceEvidenceError) as missing:
        verify_capture_fence_start(raw, expected=valid_expectation(), reader=reader, signatures=signatures)
    assert missing.value.category == "blob_semantics"
    assert reader.calls == []
    with pytest.raises(FenceEvidenceError) as throwing:
        verify_capture_fence_start(
            raw,
            expected=valid_expectation(),
            reader=reader,
            signatures=signatures,
            semantics=ThrowingSemantics(),
        )
    assert throwing.value.category == "blob_semantics"
    assert throwing.value.__context__ is None


def test_absent_start_is_typed_and_has_no_side_effects() -> None:
    class UnusedPort:
        def __getattr__(self, name: str) -> Any:
            raise AssertionError(f"unexpected port access: {name}")

    with pytest.raises(FenceEvidenceError) as exc:
        verify_capture_fence_start(
            None, expected=UnusedPort(), reader=UnusedPort(), signatures=UnusedPort(), semantics=UnusedPort()
        )
    assert exc.value.code is FenceFailureCode.BACKUP_FENCE_EVIDENCE_INVALID


@pytest.mark.parametrize("raw", [b" " * 1_048_577, b'{"x":' + b"[" * 2_000 + b"0" + b"]" * 2_000 + b"}"])
def test_untrusted_record_shape_is_typed_before_port_access(raw: bytes) -> None:
    class NoAccess:
        def __getattr__(self, name: str) -> Any:
            raise AssertionError(f"unexpected port access: {name}")

    with pytest.raises(FenceEvidenceError) as exc:
        verify_capture_fence_start(
            raw, expected=NoAccess(), reader=NoAccess(), signatures=NoAccess(), semantics=NoAccess()
        )
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
            altered_start(raw, **change),
            expected=valid_expectation(),
            reader=reader,
            signatures=signatures,
            semantics=FixtureSemantics(),
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
            semantics=FixtureSemantics(),
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
        reader.blobs[key] += b"extra"
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
            semantics=FixtureSemantics(),
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
            semantics=FixtureSemantics(),
        )
    assert reader.calls == []
    with pytest.raises(FenceEvidenceError):
        verify_capture_fence_start(
            b'{"schema_version":1,"schema_version":1}',
            expected=valid_expectation(),
            reader=reader,
            signatures=signatures,
            semantics=FixtureSemantics(),
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
        verify_capture_fence_start(
            raw,
            expected=valid_expectation(),
            reader=reader,
            signatures=FailingSignatures(),
            semantics=FixtureSemantics(),
        )
    assert signature_error.value.__context__ is None
    with pytest.raises(FenceEvidenceError) as reader_error:
        verify_capture_fence_start(
            raw,
            expected=valid_expectation(),
            reader=FailingReader({}),
            signatures=signatures,
            semantics=FixtureSemantics(),
        )
    assert reader_error.value.__context__ is None


def closure_expectation() -> FenceExpectationV1:
    return replace(valid_expectation(), evaluated_at=datetime(2026, 9, 25, 12, 10, tzinfo=UTC))


def unused_reader() -> MemoryReader:
    return MemoryReader({})


def unused_signatures() -> FixtureSignatures:
    return FixtureSignatures()


def signed_closure() -> tuple[bytes, bytes, MemoryReader, FixtureSignatures]:
    import json

    start_raw, reader, signatures = signed_start()
    verify_capture_fence_start(
        start_raw, expected=valid_expectation(), reader=reader, signatures=signatures, semantics=FixtureSemantics()
    )
    reader.calls.clear()
    signatures.calls.clear()
    data = json.loads(start_raw)
    items = [*data["services"], data["postgres_writer_check"], data["root_mount_check"]]
    for item in items:
        item["observed_at" if "service_kind" in item else "checked_at"] = "2026-09-25T12:08:30Z"
        item["blob"]["object_version"] = "v2"
        ref = item["blob"]
        body = _observation_body(item)
        ref["byte_size"] = len(body)
        ref["sha256"] = "sha256:" + hashlib.sha256(body).hexdigest()
        reader.blobs[(ref["store_id"], ref["object_ref"], ref["object_version"])] = body
    data["capture_checks_completed_at"] = "2026-09-25T12:08:00Z"
    data["fenced_capture_ended_at"] = "2026-09-25T12:09:00Z"
    return altered_start(canonical_json_bytes(data, allow_nan=False)), start_raw, reader, signatures


def test_valid_closure_checks_all_final_immutable_versions() -> None:
    raw, start_raw, reader, signatures = signed_closure()
    semantics = FixtureSemantics()
    closure = verify_capture_fence_closure(
        raw,
        start_raw=start_raw,
        expected=closure_expectation(),
        reader=reader,
        signatures=signatures,
        semantics=semantics,
    )
    assert closure.fenced_capture_ended_at.minute == 9
    assert len(reader.calls) == 12
    assert [call[2] for call in reader.calls] == ["v1"] * 6 + ["v2"] * 6
    assert len(signatures.calls) == 2
    assert semantics.calls == (["service"] * 4 + ["postgres", "roots"]) * 2


def test_closure_hash_valid_contradictory_final_blob_rejects() -> None:
    import json

    raw, start_raw, reader, signatures = signed_closure()
    data = json.loads(raw)
    ref = data["root_mount_check"]["blob"]
    contradictory = b"ROOT MOUNT REPLACED; ALIAS PRESENT"
    ref["byte_size"] = len(contradictory)
    ref["sha256"] = "sha256:" + hashlib.sha256(contradictory).hexdigest()
    reader.blobs[(ref["store_id"], ref["object_ref"], ref["object_version"])] = contradictory
    with pytest.raises(FenceEvidenceError) as exc:
        verify_capture_fence_closure(
            altered_start(canonical_json_bytes(data, allow_nan=False)),
            start_raw=start_raw,
            expected=closure_expectation(),
            reader=reader,
            signatures=signatures,
            semantics=FixtureSemantics(),
        )
    assert exc.value.category == "blob_semantics"


def test_closure_does_not_accept_a_start_with_bad_signature() -> None:
    import json

    raw, start_raw, reader, signatures = signed_closure()
    forged_start = json.loads(start_raw)
    forged_start["signature"] = "not-a-valid-start-signature"
    with pytest.raises(FenceEvidenceError) as exc:
        verify_capture_fence_closure(
            raw,
            start_raw=canonical_json_bytes(forged_start, allow_nan=False),
            expected=closure_expectation(),
            reader=reader,
            signatures=signatures,
            semantics=FixtureSemantics(),
        )
    assert exc.value.code is FenceFailureCode.BACKUP_FENCE_EVIDENCE_INVALID


def test_closure_rejects_when_start_blob_is_missing() -> None:
    import json

    raw, start_raw, reader, signatures = signed_closure()
    ref = json.loads(start_raw)["services"][0]["blob"]
    del reader.blobs[(ref["store_id"], ref["object_ref"], ref["object_version"])]
    with pytest.raises(FenceEvidenceError) as exc:
        verify_capture_fence_closure(
            raw,
            start_raw=start_raw,
            expected=closure_expectation(),
            reader=reader,
            signatures=signatures,
            semantics=FixtureSemantics(),
        )
    assert exc.value.code is FenceFailureCode.BACKUP_FENCE_EVIDENCE_INVALID


def test_closure_missing_is_not_a_window_end() -> None:
    with pytest.raises(FenceEvidenceError) as exc:
        verify_capture_fence_closure(
            None,
            start_raw=signed_start()[0],
            expected=closure_expectation(),
            reader=unused_reader(),
            signatures=unused_signatures(),
            semantics=FixtureSemantics(),
        )
    assert exc.value.code is FenceFailureCode.BACKUP_FENCE_EVIDENCE_INVALID


def test_closure_rejects_missing_start_before_any_port_call() -> None:
    raw, _, reader, signatures = signed_closure()
    with pytest.raises(FenceEvidenceError) as exc:
        verify_capture_fence_closure(
            raw,
            start_raw=None,
            expected=closure_expectation(),
            reader=reader,
            signatures=signatures,
            semantics=FixtureSemantics(),
        )
    assert exc.value.code is FenceFailureCode.BACKUP_FENCE_EVIDENCE_INVALID
    assert reader.calls == []
    assert signatures.calls == []


def test_deeply_nested_closure_rejects_before_start_or_port_access() -> None:
    raw = b'{"x":' + b"[" * 2_000 + b"0" + b"]" * 2_000 + b"}"
    with pytest.raises(FenceEvidenceError) as exc:
        verify_capture_fence_closure(
            raw,
            start_raw=signed_start()[0],
            expected=closure_expectation(),
            reader=unused_reader(),
            signatures=unused_signatures(),
            semantics=FixtureSemantics(),
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
    raw, start_raw, reader, signatures = signed_closure()
    with pytest.raises(FenceEvidenceError) as exc:
        verify_capture_fence_closure(
            altered_start(raw, **change),
            start_raw=start_raw,
            expected=closure_expectation(),
            reader=reader,
            signatures=signatures,
            semantics=FixtureSemantics(),
        )
    assert exc.value.code is FenceFailureCode.BACKUP_FENCE_EVIDENCE_INVALID


@pytest.mark.parametrize(
    "mutation", ["missing_blob", "tampered_blob", "incomplete_writers", "db_writer", "bad_signature"]
)
def test_closure_final_evidence_rejects_failures(mutation: str) -> None:
    import json

    raw, start_raw, reader, signatures = signed_closure()
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
            raw,
            start_raw=start_raw,
            expected=closure_expectation(),
            reader=reader,
            signatures=signatures,
            semantics=FixtureSemantics(),
        )
    assert exc.value.code is FenceFailureCode.BACKUP_FENCE_EVIDENCE_INVALID


def test_expectation_cannot_alias_database_and_file_root() -> None:
    raw, reader, signatures = signed_start()
    expected = replace(valid_expectation(), file_root_ids=("db-1", "media-1"))
    with pytest.raises(FenceEvidenceError) as exc:
        verify_capture_fence_start(
            raw, expected=expected, reader=reader, signatures=signatures, semantics=FixtureSemantics()
        )
    assert exc.value.code is FenceFailureCode.BACKUP_FENCE_EVIDENCE_INVALID
    assert exc.value.category == "expectation"


@pytest.mark.parametrize("mutation", ["replay_start_ref", "switch_approved_store"])
def test_closure_must_capture_new_evidence_in_the_start_store(mutation: str) -> None:
    import json

    raw, start_raw, reader, signatures = signed_closure()
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
            start_raw=start_raw,
            expected=expected,
            reader=reader,
            signatures=signatures,
            semantics=FixtureSemantics(),
        )
    assert exc.value.code is FenceFailureCode.BACKUP_FENCE_EVIDENCE_INVALID


def test_closure_cannot_change_physical_mount_identities() -> None:
    import json

    raw, start_raw, reader, signatures = signed_closure()
    data = json.loads(raw)
    data["root_mount_check"]["mount_identities"] = ["attacker-db", "attacker-projects", "attacker-media"]
    with pytest.raises(FenceEvidenceError) as exc:
        verify_capture_fence_closure(
            altered_start(canonical_json_bytes(data, allow_nan=False)),
            start_raw=start_raw,
            expected=closure_expectation(),
            reader=reader,
            signatures=signatures,
            semantics=FixtureSemantics(),
        )
    assert exc.value.code is FenceFailureCode.BACKUP_FENCE_EVIDENCE_INVALID
