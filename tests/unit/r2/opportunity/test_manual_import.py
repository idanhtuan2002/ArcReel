from __future__ import annotations

import hashlib
import importlib
import importlib.util
from pathlib import Path

import pytest

from r2.contracts.advanced_creative import CanonicalJsonObject
from r2.contracts.opportunity import SourcePageRequest
from r2.opportunity.errors import OpportunityError
from tests.unit.r2.opportunity.test_capabilities import _authority, _resign

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures/r2/opportunity/manual_import.json"
UPLOAD = "manual-upload:856a31070677496083597b304568587c"
ORIGIN = "manual-origin:73a191b26ea94207bbd1e4b4c65de852"


def source_inputs():
    raw = FIXTURE.read_bytes()
    g, e, r = _authority()
    condition = {
        "kind": "manual-upload-policy.v1",
        "upload_ref": UPLOAD,
        "origin_ref": ORIGIN,
        "uploader_id": "human-a",
        "data_classes": ("manual-excerpt", "manual-public-metadata"),
    }
    frozen = CanonicalJsonObject.model_validate(condition)
    g = g.model_copy(update={"permission": "CONDITIONAL", "conditions": (frozen,)})
    e = e.model_copy(
        update={
            "condition_evidence": (CanonicalJsonObject.model_validate({"condition": condition, "satisfied": True}),)
        }
    )
    g, e, r = _resign(g, e, r)
    return (raw, g, e)


def source(**overrides):
    assert importlib.util.find_spec("r2.opportunity.manual_import") is not None, "B4 manual source is missing"
    raw, g, e = source_inputs()
    args = {
        "payload": raw,
        "grant": g,
        "evaluation": e,
        "actor_id": "human-a",
        "upload_ref": UPLOAD,
        "origin_ref": ORIGIN,
        "declared_origin": "synthetic-fixture",
        "uploader_id": "fixture-human",
        "payload_digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
    }
    args.update(overrides)
    return importlib.import_module("r2.opportunity.manual_import").ManualImportSource(**args)


def request(**overrides):
    _, g, e = source_inputs()
    args = {
        "user_id": "u1",
        "project_name": "show-a",
        "attempt_id": "019a0000-0000-7000-8000-000000000001",
        "query_id": "019a0000-0000-7000-8000-000000000002",
        "query_revision": 1,
        "query_digest": "sha256:" + "a" * 64,
        "source_kind": "manual-import",
        "source_contract_version": "manual-import.v1",
        "operation": "import",
        "parameters": {"import_ref": UPLOAD},
        "page_ordinal": 1,
        "cursor": None,
        "remaining_record_limit": 2,
        "remaining_quota_units": 0,
        "credential_ref": None,
        "capability_grant_digest": g.grant_digest,
        "capability_evaluation_digest": e.evaluation_digest,
    }
    args.update(overrides)
    return SourcePageRequest.model_validate(args)


async def test_host_bound_manual_source_returns_exact_immutable_bytes():
    port = source()
    result = await port.fetch_page(request())
    assert result.raw_payload == FIXTURE.read_bytes()
    assert result.source_native_ids == ("synthetic-metric-001", "synthetic-text-001")
    assert result.returned_record_count == 2
    assert result.quota_units_observed == 0
    assert result.next_cursor is None
    assert result.terminal_page is True
    assert result.provider_request_id == UPLOAD


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("user_id", "other"),
        ("project_name", "other"),
        ("source_kind", "other"),
        ("source_contract_version", "unknown"),
        ("operation", "search"),
        ("parameters", {"import_ref": "foreign"}),
        ("parameters", {"import_ref": UPLOAD, "origin": "caller-claim"}),
        ("credential_ref", "Bearer canary-secret"),
        ("capability_grant_digest", "sha256:" + "b" * 64),
        ("capability_evaluation_digest", "sha256:" + "b" * 64),
        ("cursor", "foreign-cursor"),
        ("page_ordinal", 2),
    ],
)
async def test_page_requests_cannot_substitute_scope_upload_policy_or_credentials(field, value):
    port = source()
    with pytest.raises(OpportunityError) as caught:
        await port.fetch_page(request(**{field: value}))
    assert "canary-secret" not in str(caught.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("payload_digest", "sha256:" + "b" * 64),
        ("declared_origin", "caller-origin"),
        ("uploader_id", "caller-uploader"),
        ("actor_id", "foreign"),
        ("upload_ref", "foreign"),
        ("origin_ref", "foreign"),
    ],
)
def test_caller_labels_or_mismatched_upload_bytes_never_replace_host_bindings(field, value):
    with pytest.raises(OpportunityError):
        source(**{field: value})


async def test_manual_payload_over_declared_record_budget_refuses_without_truncating():
    port = source()
    with pytest.raises(OpportunityError, match="M9_OPERATIONAL_ENVELOPE_EXCEEDED"):
        await port.fetch_page(request(remaining_record_limit=1))


def test_an_enabled_grant_without_host_upload_policy_cannot_authorize_raw_files():
    g, e, _ = _authority()
    with pytest.raises(OpportunityError, match="M9_SOURCE_POLICY_FORBIDDEN"):
        source(grant=g, evaluation=e)
