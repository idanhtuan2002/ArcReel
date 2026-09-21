"""H7 secret-canary coverage for _span_for_reconcile_result directly: this is
the one function standing between a raw ReconcileResult.provider_job_id and
an exported span, so it is the exact place a real leak could be introduced."""

from __future__ import annotations

from r2.contracts.host_hardening import ExecutionAttemptState, ReconcileResult
from server.services.execution_recovery_scheduler import _span_for_reconcile_result
from server.telemetry import configure_test_tracer, public_job_ref

CANARY_PROVIDER_JOB_ID = "canary-secret-provider-job-id-do-not-leak-9f3a"


def test_span_for_reconcile_result_substitutes_the_hmac_reference_for_the_raw_job_id() -> None:
    exporter = configure_test_tracer()
    result = ReconcileResult(
        execution_id="exec-1",
        state=ExecutionAttemptState.NEEDS_OPERATOR,
        provider_job_id=CANARY_PROVIDER_JOB_ID,
        operator_reason="no_safe_reconciliation",
    )

    _span_for_reconcile_result("host_hardening.reconcile_expired", result)

    (span,) = exporter.get_finished_spans()
    attributes = dict(span.attributes or {})
    assert attributes["execution_id"] == "exec-1"
    assert attributes["attempt.state"] == "NEEDS_OPERATOR"
    assert attributes["provider_job_ref"] == public_job_ref(CANARY_PROVIDER_JOB_ID)
    for value in attributes.values():
        assert CANARY_PROVIDER_JOB_ID not in str(value)


def test_span_for_reconcile_result_omits_provider_job_ref_when_none() -> None:
    exporter = configure_test_tracer()
    result = ReconcileResult(execution_id="exec-2", state=ExecutionAttemptState.NEEDS_OPERATOR, provider_job_id=None)

    _span_for_reconcile_result("host_hardening.reconcile_expired", result)

    (span,) = exporter.get_finished_spans()
    attributes = dict(span.attributes or {})
    assert "provider_job_ref" not in attributes
    assert attributes["execution_id"] == "exec-2"
