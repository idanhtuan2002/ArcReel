"""Pure, fail-closed preflight for operator-observed backup capture fences."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import NoReturn, Protocol

from lib.content_digest import canonical_json_bytes, canonical_json_digest
from r2.contracts.backup_fence import (
    CaptureFenceClosureV1,
    CaptureFenceStartV1,
    EvidenceBlobRefV1,
    FenceRecordInvalid,
    PostgresWriterCheckV1,
    RootMountCheckV1,
    ServiceKind,
    ServiceStopEvidenceV1,
    parse_canonical_fence_record,
)

MAX_EVIDENCE_BYTES = 65_536
_REQUIRED_KINDS: set[str] = {"app", "worker", "recovery_scanner", "gc_cleanup"}


class FenceFailureCode(StrEnum):
    BACKUP_FENCE_EVIDENCE_INVALID = "BACKUP_FENCE_EVIDENCE_INVALID"


class FenceEvidenceError(ValueError):
    """Sanitized failure whose category never embeds submitted evidence."""

    def __init__(self, code: FenceFailureCode, category: str) -> None:
        self.code = code
        self.category = category
        super().__init__(f"{code.value}: {category}")


@dataclass(frozen=True)
class FenceExpectationV1:
    backup_set_id: str
    source_deployment_id: str
    release_git_sha: str
    release_image_digest: str
    db_root_id: str
    file_root_ids: tuple[str, ...]
    approved_writers: tuple[tuple[ServiceKind, str], ...]
    allowed_signer_ids: frozenset[str]
    allowed_evidence_store_ids: frozenset[str]
    custodian_id: str
    custodian_role: str
    evaluated_at: datetime


class EvidenceReader(Protocol):
    def read_exact(self, ref: EvidenceBlobRefV1, *, max_bytes: int) -> bytes: ...


class SignatureVerifier(Protocol):
    def verify_ed25519(self, key_id: str, payload: bytes, signature: str) -> bool: ...


class EvidenceSemantics(Protocol):
    """Trusted, type-specific interpretation of immutable observation bytes."""

    def validate_service(self, item: ServiceStopEvidenceV1, blob: bytes) -> bool: ...

    def validate_postgres(self, item: PostgresWriterCheckV1, blob: bytes) -> bool: ...

    def validate_roots(self, item: RootMountCheckV1, blob: bytes) -> bool: ...


def _reject(category: str) -> NoReturn:
    raise FenceEvidenceError(FenceFailureCode.BACKUP_FENCE_EVIDENCE_INVALID, category)


def evidence_refs(record: CaptureFenceStartV1) -> tuple[EvidenceBlobRefV1, ...]:
    """Enumerate all independently stored observations named by a record."""

    return (
        *(item.blob for item in record.services),
        record.postgres_writer_check.blob,
        record.root_mount_check.blob,
    )


def _verify_expectation(expected: FenceExpectationV1) -> None:
    writers = expected.approved_writers
    if (
        not expected.allowed_signer_ids
        or not expected.allowed_evidence_store_ids
        or not expected.file_root_ids
        or len(set(expected.file_root_ids)) != len(expected.file_root_ids)
        or expected.db_root_id in expected.file_root_ids
        or not writers
        or len(set(writers)) != len(writers)
        or {kind for kind, _ in writers} != _REQUIRED_KINDS
        or any(not instance_id for _, instance_id in writers)
        or expected.evaluated_at.utcoffset() != timedelta(0)
    ):
        _reject("expectation")


def _verify_identity_and_window(record: CaptureFenceStartV1, expected: FenceExpectationV1) -> None:
    if (
        record.backup_set_id != expected.backup_set_id
        or record.source_deployment_id != expected.source_deployment_id
        or record.release_git_sha != expected.release_git_sha
        or record.release_image_digest != expected.release_image_digest
        or record.db_root_id != expected.db_root_id
        or record.file_root_ids != expected.file_root_ids
        or record.custodian_id != expected.custodian_id
        or record.custodian_role != expected.custodian_role
    ):
        _reject("identity")
    if not (
        record.fence_started_at <= record.quiescence_confirmed_at <= expected.evaluated_at < record.fence_expires_at
    ):
        _reject("capture_window")


def _verify_observations(
    record: CaptureFenceStartV1,
    expected: FenceExpectationV1,
    *,
    observations_started_at: datetime,
    observations_ended_at: datetime,
) -> None:
    submitted_writers = tuple((item.service_kind, item.instance_id) for item in record.services)
    approved_writers = expected.approved_writers
    if (
        len(submitted_writers) != len(set(submitted_writers))
        or set(submitted_writers) != set(approved_writers)
        or {kind for kind, _ in submitted_writers} != _REQUIRED_KINDS
    ):
        _reject("writer_inventory")
    digest = "sha256:" + canonical_json_digest(sorted(approved_writers), allow_nan=False)
    if record.writer_inventory_digest != digest:
        _reject("writer_inventory")
    observation_times = (
        *(item.observed_at for item in record.services),
        record.postgres_writer_check.checked_at,
        record.root_mount_check.checked_at,
    )
    if any(not observations_started_at <= observed <= observations_ended_at for observed in observation_times):
        _reject("observation_window")
    db_check = record.postgres_writer_check
    if (
        db_check.database_id != expected.db_root_id
        or db_check.active_writer_sessions != 0
        or db_check.active_writer_transactions != 0
    ):
        _reject("postgres_writers")
    root_check = record.root_mount_check
    expected_roots = (expected.db_root_id, *expected.file_root_ids)
    if (
        root_check.root_ids != expected_roots
        or not root_check.no_alias
        or not root_check.no_symlink
        or len(root_check.mount_identities) != len(expected_roots)
        or len(set(root_check.mount_identities)) != len(expected_roots)
    ):
        _reject("root_mounts")


def _verify_signature(
    record: CaptureFenceStartV1,
    decoded: dict[str, object],
    expected: FenceExpectationV1,
    signatures: SignatureVerifier,
) -> None:
    if record.signer_key_id not in expected.allowed_signer_ids:
        _reject("signature")
    unsigned = {key: value for key, value in decoded.items() if key != "signature"}
    try:
        valid = signatures.verify_ed25519(
            record.signer_key_id, canonical_json_bytes(unsigned, allow_nan=False), record.signature
        )
    except Exception:
        valid = False
    if not valid:
        _reject("signature")


def _blob_matches_ref(value: object, ref: EvidenceBlobRefV1) -> bool:
    return (
        isinstance(value, bytes)
        and len(value) == ref.byte_size
        and "sha256:" + hashlib.sha256(value).hexdigest() == ref.sha256
    )


def _read_verified_blob(ref: EvidenceBlobRefV1, expected: FenceExpectationV1, reader: EvidenceReader) -> bytes:
    if ref.store_id not in expected.allowed_evidence_store_ids:
        _reject("evidence_store")
    if not 1 <= ref.byte_size <= MAX_EVIDENCE_BYTES:
        _reject("blob_size")
    available = True
    try:
        blob = reader.read_exact(ref, max_bytes=ref.byte_size)
    except Exception:
        available = False
        blob = b""
    if not available:
        _reject("blob_unavailable")
    if not _blob_matches_ref(blob, ref):
        _reject("blob_integrity")
    return blob


def _require_semantics(check: Callable[[], bool]) -> None:
    try:
        valid = check()
    except Exception:
        valid = False
    if valid is not True:
        _reject("blob_semantics")


def _verify_blobs(
    record: CaptureFenceStartV1,
    expected: FenceExpectationV1,
    reader: EvidenceReader,
    semantics: EvidenceSemantics | None,
) -> None:
    if semantics is None:
        _reject("blob_semantics")
    refs = evidence_refs(record)
    identities = tuple((ref.store_id, ref.object_ref, ref.object_version) for ref in refs)
    if len(set(identities)) != len(identities):
        _reject("evidence_refs")
    for item in record.services:
        blob = _read_verified_blob(item.blob, expected, reader)
        _require_semantics(lambda item=item, blob=blob: semantics.validate_service(item, blob))
    db = record.postgres_writer_check
    db_blob = _read_verified_blob(db.blob, expected, reader)
    _require_semantics(lambda: semantics.validate_postgres(db, db_blob))
    roots = record.root_mount_check
    root_blob = _read_verified_blob(roots.blob, expected, reader)
    _require_semantics(lambda: semantics.validate_roots(roots, root_blob))


def _verify_final_refs(start: CaptureFenceStartV1, closure: CaptureFenceClosureV1) -> None:
    start_services = {(item.service_kind, item.instance_id): item.blob for item in start.services}
    pairs = [(start_services[(item.service_kind, item.instance_id)], item.blob) for item in closure.services]
    pairs.extend(
        (
            (start.postgres_writer_check.blob, closure.postgres_writer_check.blob),
            (start.root_mount_check.blob, closure.root_mount_check.blob),
        )
    )
    for before, after in pairs:
        if before.store_id != after.store_id or (
            before.store_id,
            before.object_ref,
            before.object_version,
        ) == (after.store_id, after.object_ref, after.object_version):
            _reject("final_evidence_ref")


def verify_capture_fence_start(
    raw: bytes | None,
    *,
    expected: FenceExpectationV1,
    reader: EvidenceReader,
    signatures: SignatureVerifier,
    semantics: EvidenceSemantics | None = None,
) -> CaptureFenceStartV1:
    """Verify a start proof without granting any database or filesystem authority."""

    if not isinstance(raw, bytes) or not raw:
        _reject("missing_start")
    try:
        parsed = parse_canonical_fence_record(raw, CaptureFenceStartV1)
    except FenceRecordInvalid:
        parsed = None
    if parsed is None:
        _reject("invalid_record")
    record, decoded = parsed
    _verify_expectation(expected)
    _verify_identity_and_window(record, expected)
    _verify_observations(
        record,
        expected,
        observations_started_at=record.fence_started_at,
        observations_ended_at=record.quiescence_confirmed_at,
    )
    _verify_signature(record, decoded, expected, signatures)
    _verify_blobs(record, expected, reader, semantics)
    return record


def verify_capture_fence_closure(
    raw: bytes | None,
    *,
    start_raw: bytes | None,
    expected: FenceExpectationV1,
    reader: EvidenceReader,
    signatures: SignatureVerifier,
    semantics: EvidenceSemantics | None = None,
) -> CaptureFenceClosureV1:
    """Reverify the raw start, then validate signed post-capture observations."""

    if not isinstance(raw, bytes) or not raw:
        _reject("missing_closure")
    try:
        parsed = parse_canonical_fence_record(raw, CaptureFenceClosureV1)
    except FenceRecordInvalid:
        parsed = None
    if parsed is None:
        _reject("invalid_record")
    closure, decoded = parsed
    start = verify_capture_fence_start(
        start_raw, expected=expected, reader=reader, signatures=signatures, semantics=semantics
    )
    _verify_expectation(expected)
    _verify_identity_and_window(closure, expected)
    start_binding = (
        "schema_version",
        "backup_set_id",
        "source_deployment_id",
        "release_git_sha",
        "release_image_digest",
        "db_root_id",
        "file_root_ids",
        "writer_inventory_digest",
        "custodian_id",
        "custodian_role",
        "fence_started_at",
        "quiescence_confirmed_at",
        "fence_expires_at",
        "signer_key_id",
    )
    if any(getattr(closure, field) != getattr(start, field) for field in start_binding):
        _reject("start_binding")
    if not (
        start.quiescence_confirmed_at
        <= closure.capture_checks_completed_at
        <= closure.fenced_capture_ended_at
        <= start.fence_expires_at
        and closure.fenced_capture_ended_at <= expected.evaluated_at
    ):
        _reject("capture_window")
    _verify_observations(
        closure,
        expected,
        observations_started_at=closure.capture_checks_completed_at,
        observations_ended_at=closure.fenced_capture_ended_at,
    )
    if closure.root_mount_check.mount_identities != start.root_mount_check.mount_identities:
        _reject("root_mounts")
    _verify_final_refs(start, closure)
    _verify_signature(closure, decoded, expected, signatures)
    _verify_blobs(closure, expected, reader, semantics)
    return closure


__all__ = [
    "MAX_EVIDENCE_BYTES",
    "EvidenceReader",
    "EvidenceSemantics",
    "FenceEvidenceError",
    "FenceExpectationV1",
    "FenceFailureCode",
    "SignatureVerifier",
    "evidence_refs",
    "verify_capture_fence_closure",
    "verify_capture_fence_start",
]
