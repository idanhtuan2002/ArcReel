"""Versioned receipt hashes preserve legacy vectors and bind successor metadata."""

import importlib
import importlib.util
from datetime import UTC, datetime, timedelta
from typing import Any

from r2.contracts.opportunity import AcquisitionReceipt, AttemptState, CommandContext
from r2.opportunity.digests import command_guard_key, digest_command_result

ID = "019a0000-0000-7000-8000-000000000001"
ATTEMPT = "019a0000-0000-7000-8000-000000000002"
SNAPSHOT = "019a0000-0000-7000-8000-000000000003"
H = "sha256:" + "a" * 64
NOW = datetime(2026, 10, 20, tzinfo=UTC)


def modules() -> tuple[Any, Any]:
    for name in ("r2.contracts.opportunity_acquisition_v2", "r2.opportunity.acquisition_v2_digests"):
        assert importlib.util.find_spec(name) is not None, "V2 contracts/digests missing"
    return (
        importlib.import_module("r2.contracts.opportunity_acquisition_v2"),
        importlib.import_module("r2.opportunity.acquisition_v2_digests"),
    )


def test_v1_golden_receipt_bytes_and_digest_unchanged():
    r = AcquisitionReceipt(
        command_id=ID,
        request_digest=H,
        attempt_id=ATTEMPT,
        attempt_version=3,
        state=AttemptState.SUCCEEDED,
        snapshot_ids=(SNAPSHOT,),
        snapshot_digests=("sha256:" + "b" * 64,),
        result_digest=H,
        committed_at=NOW,
    )
    assert (
        digest_command_result("acquire", H, r)
        == "sha256:5197741de02a2600eb1aa99543a921a0ec0654f50a4893404a8e28586bce8038"
    )
    assert r.model_dump_json() == (
        '{"command_id":"019a0000-0000-7000-8000-000000000001",'
        '"request_digest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
        '"attempt_id":"019a0000-0000-7000-8000-000000000002","attempt_version":3,"state":"SUCCEEDED",'
        '"snapshot_ids":["019a0000-0000-7000-8000-000000000003"],'
        '"snapshot_digests":["sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"],'
        '"result_digest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
        '"committed_at":"2026-10-20T00:00:00Z"}'
    )


def test_protocol_switch_cannot_allocate_new_command_guard():
    c, d = modules()
    context = CommandContext(command_id=ID, user_id="u1", project_name="show-a", actor_id="human-a")
    command = c.AcquireSourceQueryV2(
        protocol_version="m9.acquisition.v2",
        context=context,
        query_id=ID,
        query_revision=1,
        query_digest=H,
        expected_query_head_version=1,
    )
    other = command.model_copy(update={"context": context.model_copy(update={"project_name": "show-b"})})
    assert command_guard_key("acquire", context) == command_guard_key("acquire", other.context)
    assert d.digest_acquisition_request_v2(command) != d.digest_acquisition_request_v2(other)
    assert (
        d.digest_acquisition_request_v2(command)
        == "sha256:1d68c6043725ef6f70e7663092c28142c5b56fbb7845220f8be526a6839e08b5"
    )


def test_v2_result_digest_binds_closure_quota_and_commit_time():
    c, d = modules()
    r = c.AcquisitionReceiptV2(
        protocol_version="m9.acquisition.v2",
        command_id=ID,
        request_digest=H,
        attempt_id=ATTEMPT,
        attempt_version=4,
        state="EXPIRED_UNRECOVERABLE",
        outcome_reason="RESPONSE_OUTCOME_UNKNOWN",
        snapshot_ids=(),
        snapshot_digests=(),
        snapshot_provenance_digests=(),
        closure={
            "disposition": "ADMISSION_RETENTION_EXPIRED",
            "original_deadline": NOW,
            "closed_at": NOW,
            "resolver_id": "host-expiry",
            "resolver_version": "1",
            "expected_prior_version": 3,
        },
        quota_disposition="POSSIBLY_CONSUMED",
        quota_units_observed=None,
        result_digest=H,
        committed_at=NOW,
    )
    baseline = d.digest_acquisition_result_v2(r)
    assert baseline != digest_command_result("acquire", H, r)
    assert d.digest_acquisition_result_v2(r.model_copy(update={"result_digest": "sha256:" + "b" * 64})) == baseline
    for changes in (
        {"quota_disposition": c.QuotaDispositionV2.OBSERVED, "quota_units_observed": 0},
        {"closure": r.closure.model_copy(update={"resolver_id": "different-host"})},
        {
            "closure": r.closure.model_copy(update={"closed_at": NOW + timedelta(seconds=1)}),
            "committed_at": NOW + timedelta(seconds=1),
        },
        {"snapshot_ids": (SNAPSHOT,), "snapshot_digests": (H,), "snapshot_provenance_digests": (H,)},
    ):
        assert d.digest_acquisition_result_v2(r.model_copy(update=changes)) != baseline


def test_provenance_digest_binds_original_admission_and_origin():
    c, d = modules()
    p = c.SnapshotProvenanceV2(
        snapshot_id=SNAPSHOT,
        snapshot_digest=H,
        attempt_id=ATTEMPT,
        attempt_version=4,
        admission_metadata_digest=H,
        origin="LOCAL_ADMISSION_RECONSTRUCTION",
        admitted_at=NOW,
        response_recorded_at=None,
    )
    before = d.digest_snapshot_provenance_v2(p)
    assert (
        d.digest_snapshot_provenance_v2(p.model_copy(update={"admission_metadata_digest": "sha256:" + "b" * 64}))
        != before
    )
    assert (
        d.digest_snapshot_provenance_v2(
            p.model_copy(update={"origin": c.SnapshotOriginV2.SOURCE_RESPONSE_VERIFIED, "response_recorded_at": NOW})
        )
        != before
    )
