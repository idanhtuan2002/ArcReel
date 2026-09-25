"""Pure, fail-closed preflight for operator-observed backup capture fences."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import NoReturn, Protocol

from lib.content_digest import canonical_json_bytes, canonical_json_digest
from r2.contracts.backup_fence import (
    CaptureFenceStartV1,
    EvidenceBlobRefV1,
    FenceRecordInvalid,
    ServiceKind,
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


def _verify_observations(record: CaptureFenceStartV1, expected: FenceExpectationV1) -> None:
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
    if any(not record.fence_started_at <= observed <= record.quiescence_confirmed_at for observed in observation_times):
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


def _verify_blobs(record: CaptureFenceStartV1, expected: FenceExpectationV1, reader: EvidenceReader) -> None:
    for ref in evidence_refs(record):
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


def verify_capture_fence_start(
    raw: bytes | None,
    *,
    expected: FenceExpectationV1,
    reader: EvidenceReader,
    signatures: SignatureVerifier,
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
    _verify_observations(record, expected)
    _verify_signature(record, decoded, expected, signatures)
    _verify_blobs(record, expected, reader)
    return record


__all__ = [
    "MAX_EVIDENCE_BYTES",
    "EvidenceReader",
    "FenceEvidenceError",
    "FenceExpectationV1",
    "FenceFailureCode",
    "SignatureVerifier",
    "evidence_refs",
    "verify_capture_fence_start",
]
