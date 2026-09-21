"""server.telemetry: span creation stays inside the H7 allowlist, baggage
clearing actually clears, and public_job_ref is stable within a process."""

from __future__ import annotations

import pytest
from opentelemetry import baggage
from opentelemetry import context as otel_context

from r2.host_hardening.telemetry import TelemetryPolicyError
from server.telemetry import clear_baggage_for_provider_call, configure_test_tracer, execution_span, public_job_ref


def test_execution_span_exports_only_the_attributes_it_was_given() -> None:
    exporter = configure_test_tracer()
    with execution_span(
        "unit.op",
        deployment_environment="test",
        attempt_state="ACCEPTED",
        provider_id="kling",
        execution_id="exec-1",
    ):
        pass

    (span,) = exporter.get_finished_spans()
    attributes = dict(span.attributes or {})
    assert attributes["service.name"] == "arcreel-host"
    assert attributes["deployment.environment"] == "test"
    assert attributes["operation.name"] == "unit.op"
    assert attributes["attempt.state"] == "ACCEPTED"
    assert attributes["provider.id"] == "kling"
    assert attributes["execution_id"] == "exec-1"


def test_execution_span_omits_unset_optional_attributes() -> None:
    exporter = configure_test_tracer()
    with execution_span("unit.op", deployment_environment="test", execution_id="exec-1"):
        pass

    (span,) = exporter.get_finished_spans()
    attributes = dict(span.attributes or {})
    assert "attempt.state" not in attributes
    assert "provider.id" not in attributes
    assert "failure.reason_code" not in attributes


def test_execution_span_rejects_a_disallowed_attribute_before_creating_any_span() -> None:
    exporter = configure_test_tracer()
    with (
        pytest.raises(TelemetryPolicyError),
        execution_span("unit.op", deployment_environment="test", raw_prompt="leak me"),
    ):
        pass

    assert exporter.get_finished_spans() == ()


def test_clear_baggage_for_provider_call_removes_every_entry() -> None:
    ctx = otel_context.get_current()
    ctx = baggage.set_baggage("user_id", "u1", context=ctx)
    ctx = baggage.set_baggage("project_name", "demo", context=ctx)
    token = otel_context.attach(ctx)
    try:
        cleared = clear_baggage_for_provider_call()
        assert baggage.get_all(cleared) == {}
    finally:
        otel_context.detach(token)


def test_public_job_ref_is_stable_within_a_process() -> None:
    a = public_job_ref("job-canary-1")
    b = public_job_ref("job-canary-1")
    assert a == b
    assert "job-canary-1" not in a
