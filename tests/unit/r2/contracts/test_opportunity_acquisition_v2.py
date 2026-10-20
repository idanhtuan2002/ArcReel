"""Successor contracts close local policy expiry without claiming provider resolution."""

from __future__ import annotations

import importlib
import importlib.util
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

ID = "019a0000-0000-7000-8000-000000000001"
ATTEMPT = "019a0000-0000-7000-8000-000000000002"
SNAPSHOT = "019a0000-0000-7000-8000-000000000003"
H = "sha256:" + "a" * 64
NOW = datetime(2026, 10, 20, tzinfo=UTC)


def types() -> Any:
    assert importlib.util.find_spec("r2.contracts.opportunity_acquisition_v2") is not None, "V2 contracts missing"
    return importlib.import_module("r2.contracts.opportunity_acquisition_v2")


def closure() -> dict[str, Any]:
    return {
        "disposition": "ADMISSION_RETENTION_EXPIRED",
        "original_deadline": NOW,
        "closed_at": NOW,
        "resolver_id": "host-policy-expiry",
        "resolver_version": "1",
        "expected_prior_version": 3,
    }


def attempt() -> dict[str, Any]:
    return {
        "protocol_version": "m9.acquisition.v2",
        "attempt_id": ATTEMPT,
        "attempt_version": 4,
        "user_id": "u1",
        "project_name": "show-a",
        "actor_id": "human-a",
        "command_id": ID,
        "request_digest": H,
        "query_id": ID,
        "query_revision": 1,
        "query_digest": H,
        "page_cursor_digest": None,
        "state": "EXPIRED_UNRECOVERABLE",
        "adapter_version": "manual-import.v1",
        "started_at": NOW - timedelta(seconds=90),
        "completed_at": NOW,
        "provider_request_id": "opaque-original-upload",
        "outcome_reason": "RESPONSE_OUTCOME_UNKNOWN",
        "closure": closure(),
        "quota_disposition": "POSSIBLY_CONSUMED",
        "quota_units_observed": None,
    }


def receipt() -> dict[str, Any]:
    return {
        "protocol_version": "m9.acquisition.v2",
        "command_id": ID,
        "request_digest": H,
        "attempt_id": ATTEMPT,
        "attempt_version": 4,
        "state": "EXPIRED_UNRECOVERABLE",
        "outcome_reason": "RESPONSE_OUTCOME_UNKNOWN",
        "snapshot_ids": (),
        "snapshot_digests": (),
        "snapshot_provenance_digests": (),
        "closure": closure(),
        "quota_disposition": "POSSIBLY_CONSUMED",
        "quota_units_observed": None,
        "result_digest": H,
        "committed_at": NOW,
    }


def test_v2_expiry_is_terminal_without_snapshot():
    c = types()
    a = c.AcquisitionAttemptV2.model_validate(attempt())
    r = c.AcquisitionReceiptV2.model_validate(receipt())
    assert a.state in c.TERMINAL_ATTEMPT_STATES_V2
    assert a.state.value == r.state.value == "EXPIRED_UNRECOVERABLE"
    assert r.snapshot_ids == r.snapshot_provenance_digests == ()
    assert a.completed_at == r.closure.closed_at == NOW


def test_expiry_preserves_unknown_reason_and_quota():
    c = types()
    for value in (c.AcquisitionAttemptV2.model_validate(attempt()), c.AcquisitionReceiptV2.model_validate(receipt())):
        assert value.outcome_reason.value == "RESPONSE_OUTCOME_UNKNOWN"
        assert value.quota_disposition.value == "POSSIBLY_CONSUMED"
        assert value.quota_units_observed is None
    r = c.AcquisitionReceiptV2.model_validate({**receipt(), "quota_disposition": "OBSERVED", "quota_units_observed": 0})
    assert r.quota_units_observed == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"outcome_reason": "COMPLETED"},
        {"outcome_reason": "OPERATOR_RESOLVED"},
        {"closure": None},
        {"completed_at": None},
        {"attempt_version": 3},
        {"completed_at": NOW + timedelta(seconds=1)},
        {"started_at": NOW + timedelta(seconds=1)},
        {"state": "NEEDS_OPERATOR"},
        {"protocol_version": "m9.acquisition.v1"},
        {"quota_disposition": "OBSERVED", "quota_units_observed": None},
        {"quota_disposition": "UNKNOWN", "quota_units_observed": 0},
        {"quota_units_observed": -1},
    ],
)
def test_expiry_attempt_rejects_false_lifecycle_or_quota(changes):
    with pytest.raises(ValidationError):
        types().AcquisitionAttemptV2.model_validate({**attempt(), **changes})


@pytest.mark.parametrize(
    "changes",
    [
        {"closed_at": NOW - timedelta(microseconds=1)},
        {"expected_prior_version": 0},
        {"disposition": "PROVIDER_REJECTED"},
        {"resolver_id": " "},
        {"material_digest": H},
    ],
)
def test_closure_rejects_non_expiry_or_content_authority(changes):
    with pytest.raises(ValidationError):
        types().ExpiryClosureV2.model_validate({**closure(), **changes})


@pytest.mark.parametrize(
    "changes",
    [
        {"state": "SUCCEEDED", "closure": None, "outcome_reason": "COMPLETED"},
        {"state": "FAILED", "closure": None, "outcome_reason": "PROVIDER_ERROR"},
        {"snapshot_ids": (SNAPSHOT,)},
        {"snapshot_digests": (H,)},
        {"snapshot_provenance_digests": (H,)},
        {"outcome_reason": "OPERATOR_RESOLVED"},
        {"committed_at": NOW + timedelta(seconds=1)},
        {"attempt_version": 3},
    ],
)
def test_terminal_receipt_cannot_fabricate_snapshot_or_resolution(changes):
    with pytest.raises(ValidationError):
        types().AcquisitionReceiptV2.model_validate({**receipt(), **changes})


def test_nonterminal_receipt_replays_without_snapshot_or_closure():
    r = types().AcquisitionReceiptV2.model_validate({**receipt(), "state": "OUTCOME_UNKNOWN", "closure": None})
    assert r.snapshot_ids == ()
    assert r.closure is None


def test_expired_receipt_can_preserve_original_snapshot_metadata():
    r = types().AcquisitionReceiptV2.model_validate(
        {**receipt(), "snapshot_ids": (SNAPSHOT,), "snapshot_digests": (H,), "snapshot_provenance_digests": (H,)}
    )
    assert r.snapshot_ids == (SNAPSHOT,)


def test_command_requires_explicit_version_and_forbids_host_binding_injection():
    body = {
        "context": {"command_id": ID, "user_id": "u1", "project_name": "show-a", "actor_id": "human-a"},
        "query_id": ID,
        "query_revision": 1,
        "query_digest": H,
        "expected_query_head_version": 1,
    }
    c = types()
    with pytest.raises(ValidationError):
        c.AcquireSourceQueryV2.model_validate(body)
    command = c.AcquireSourceQueryV2.model_validate({**body, "protocol_version": "m9.acquisition.v2"})
    assert command.context.command_id == ID
    with pytest.raises(ValidationError):
        c.AcquireSourceQueryV2.model_validate({**command.model_dump(), "binding_id": "caller-binding"})


@pytest.mark.parametrize("response_time", [NOW, NOW + timedelta(seconds=1)])
def test_provenance_reconstruction_cannot_claim_response(response_time):
    with pytest.raises(ValidationError):
        types().SnapshotProvenanceV2.model_validate(
            {
                "snapshot_id": SNAPSHOT,
                "snapshot_digest": H,
                "attempt_id": ATTEMPT,
                "attempt_version": 4,
                "admission_metadata_digest": H,
                "origin": "LOCAL_ADMISSION_RECONSTRUCTION",
                "admitted_at": NOW,
                "response_recorded_at": response_time,
            }
        )


def test_response_provenance_cannot_predate_admission_or_omit_response():
    body = {
        "snapshot_id": SNAPSHOT,
        "snapshot_digest": H,
        "attempt_id": ATTEMPT,
        "attempt_version": 4,
        "admission_metadata_digest": H,
        "origin": "SOURCE_RESPONSE_VERIFIED",
        "admitted_at": NOW,
    }
    for value in (None, NOW - timedelta(microseconds=1)):
        with pytest.raises(ValidationError):
            types().SnapshotProvenanceV2.model_validate({**body, "response_recorded_at": value})


def snapshot_view() -> dict[str, Any]:
    return {
        "protocol_version": "m9.acquisition.v2",
        "snapshot_view": {
            "snapshot": {
                "snapshot_id": SNAPSHOT,
                "revision": 1,
                "parent_revision": None,
                "user_id": "u1",
                "project_name": "show-a",
                "query_id": ID,
                "query_revision": 1,
                "query_digest": H,
                "attempt_id": ATTEMPT,
                "source_kind": "manual-import",
                "source_contract_version": "manual-import.v1",
                "source_identity_refs": (),
                "pages": (),
                "coverage_state": "PARTIAL",
                "requested_record_limit": 1,
                "returned_record_count": 0,
                "coverage_note": "Original local admission reconstructed.",
                "provider_observed_at": None,
                "capture_started_at": NOW - timedelta(seconds=90),
                "capture_completed_at": NOW,
                "adapter_version": "manual-import.v1",
                "capability_grant_digest": H,
                "capability_evaluation_digest": H,
                "snapshot_digest": H,
                "created_at": NOW + timedelta(seconds=1),
            },
            "validity": {
                "state": "STALE",
                "invalidation_job_id": None,
                "reason_code": None,
                "invalidated_at": None,
                "erasable_content_available": False,
                "projection_digest": H,
            },
        },
        "provenance": {
            "snapshot_id": SNAPSHOT,
            "snapshot_digest": H,
            "attempt_id": ATTEMPT,
            "attempt_version": 4,
            "admission_metadata_digest": H,
            "origin": "LOCAL_ADMISSION_RECONSTRUCTION",
            "admitted_at": NOW,
            "response_recorded_at": None,
        },
    }


def test_snapshot_projection_preserves_local_admission_without_provider_claim():
    view = types().SourceSnapshotViewV2.model_validate(snapshot_view())
    assert view.snapshot_view.snapshot.capture_completed_at == NOW
    assert view.provenance.origin.value == "LOCAL_ADMISSION_RECONSTRUCTION"
    assert view.snapshot_view.snapshot.provider_observed_at is None


@pytest.mark.parametrize(
    "changes",
    [
        {"provider_observed_at": NOW},
        {"snapshot_id": ID},
        {"snapshot_digest": "sha256:" + "b" * 64},
        {"attempt_id": ID},
        {"created_at": NOW - timedelta(seconds=1)},
        {"capture_completed_at": NOW + timedelta(seconds=1)},
    ],
)
def test_snapshot_projection_rejects_substitution_or_fabricated_provider_observation(changes):
    body = snapshot_view()
    body["snapshot_view"]["snapshot"].update(changes)
    with pytest.raises(ValidationError):
        types().SourceSnapshotViewV2.model_validate(body)


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        ("RUNNING", None),
        ("SUCCEEDED", "COMPLETED"),
        ("FAILED", "PROVIDER_ERROR"),
        ("OUTCOME_UNKNOWN", "RESPONSE_OUTCOME_UNKNOWN"),
        ("NEEDS_OPERATOR", "RESPONSE_OUTCOME_UNKNOWN"),
    ],
)
def test_nonexpiry_attempts_preserve_known_or_uncertain_lifecycle(state, reason):
    body = {**attempt(), "state": state, "outcome_reason": reason, "closure": None}
    if state not in ("SUCCEEDED", "FAILED"):
        body["completed_at"] = None
    value = types().AcquisitionAttemptV2.model_validate(body)
    assert value.state.value == state
    assert value.closure is None
