"""Pure H7 telemetry policy: HMAC job refs and the span/metric-label allowlists."""

from __future__ import annotations

import pytest

from r2.host_hardening.telemetry import (
    ALLOWED_SPAN_ATTRIBUTES,
    DURABLE_ID_ATTRIBUTES,
    REQUIRED_LOW_CARDINALITY_ATTRIBUTES,
    TelemetryPolicyError,
    assert_metric_labels_allowed,
    assert_span_attributes_allowed,
    public_provider_job_ref,
)

KEY = b"a-test-key-not-a-real-secret"


def test_public_provider_job_ref_is_deterministic_for_the_same_inputs() -> None:
    a = public_provider_job_ref("job-123", key=KEY, key_version="v1")
    b = public_provider_job_ref("job-123", key=KEY, key_version="v1")
    assert a == b


def test_public_provider_job_ref_never_contains_the_raw_id() -> None:
    ref = public_provider_job_ref("super-secret-canary-job-id", key=KEY, key_version="v1")
    assert "super-secret-canary-job-id" not in ref


def test_public_provider_job_ref_differs_for_a_different_raw_id() -> None:
    a = public_provider_job_ref("job-a", key=KEY, key_version="v1")
    b = public_provider_job_ref("job-b", key=KEY, key_version="v1")
    assert a != b


def test_public_provider_job_ref_differs_for_a_different_key() -> None:
    a = public_provider_job_ref("job-a", key=KEY, key_version="v1")
    b = public_provider_job_ref("job-a", key=b"a-different-key", key_version="v1")
    assert a != b


def test_public_provider_job_ref_carries_the_key_version() -> None:
    ref = public_provider_job_ref("job-a", key=KEY, key_version="v7")
    assert ref.startswith("pjr:v7:")


def test_public_provider_job_ref_rejects_an_empty_raw_id() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        public_provider_job_ref("", key=KEY, key_version="v1")


def test_span_allowlist_accepts_every_required_and_durable_attribute() -> None:
    attributes = dict.fromkeys(REQUIRED_LOW_CARDINALITY_ATTRIBUTES | DURABLE_ID_ATTRIBUTES, "x")
    assert_span_attributes_allowed(attributes)  # must not raise


def test_span_allowlist_rejects_an_unknown_attribute() -> None:
    with pytest.raises(TelemetryPolicyError, match="raw_prompt"):
        assert_span_attributes_allowed({"raw_prompt": "leak me"})


def test_metric_labels_accept_only_the_low_cardinality_set() -> None:
    assert_metric_labels_allowed(dict.fromkeys(REQUIRED_LOW_CARDINALITY_ATTRIBUTES, "x"))  # must not raise


def test_metric_labels_reject_a_durable_identity_attribute() -> None:
    with pytest.raises(TelemetryPolicyError, match="execution_id"):
        assert_metric_labels_allowed({"execution_id": "exec-1"})


def test_allowed_span_attributes_is_the_union_of_the_two_sets() -> None:
    assert ALLOWED_SPAN_ATTRIBUTES == REQUIRED_LOW_CARDINALITY_ATTRIBUTES | DURABLE_ID_ATTRIBUTES
