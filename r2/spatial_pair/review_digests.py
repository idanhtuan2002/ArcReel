"""Domain-separated digests for exact spatial frame review custody."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from r2.contracts.common import ensure_json_value
from r2.contracts.fingerprints import canonical_json_bytes
from r2.contracts.review_evidence import ReviewEvidenceV1, ReviewSnapshotV1


def _digest(domain: str, body: Mapping[str, Any]) -> str:
    envelope = ensure_json_value({"domain": domain, "canonical_version": "1", "body": dict(body)})
    return "sha256:" + hashlib.sha256(canonical_json_bytes(envelope)).hexdigest()


def review_snapshot_digest(body: Mapping[str, Any]) -> str:
    snapshot = ReviewSnapshotV1.model_validate(body)
    return _digest("r2.m8.spatial.review.snapshot.v1", snapshot.model_dump(mode="json"))


def review_evidence_digest(body: Mapping[str, Any]) -> str:
    evidence = ReviewEvidenceV1.model_validate(body)
    return _digest("r2.m8.spatial.review.evidence.v1", evidence.model_dump(mode="json"))


class ReviewEvidenceIntegrityError(ValueError):
    """Stored review evidence differs from its expected scope or digest."""


def verify_stored_review_evidence(
    body: Mapping[str, Any],
    *,
    expected_digest: str,
    user_id: str,
    project_name: str,
    principal: str,
    session_id: str,
) -> ReviewEvidenceV1:
    try:
        evidence = ReviewEvidenceV1.model_validate(body)
        snapshot = evidence.snapshot
        canonical_body = evidence.model_dump(mode="json")
        if (
            canonical_body != dict(body)
            or snapshot.user_id != user_id
            or snapshot.project_name != project_name
            or snapshot.principal != principal
            or snapshot.session_id != session_id
            or _digest("r2.m8.spatial.review.evidence.v1", canonical_body) != expected_digest
        ):
            raise ValueError("review evidence mismatch")
    except (ValidationError, ValueError, TypeError) as exc:
        raise ReviewEvidenceIntegrityError("stored review evidence integrity verification failed") from exc
    return evidence


__all__ = [
    "ReviewEvidenceIntegrityError",
    "review_evidence_digest",
    "review_snapshot_digest",
    "verify_stored_review_evidence",
]
