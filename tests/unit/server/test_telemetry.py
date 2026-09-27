"""server.telemetry: span creation stays inside the H7 allowlist, baggage
clearing actually clears, and public_job_ref is stable within a process."""

from __future__ import annotations

import pytest
from opentelemetry import baggage
from opentelemetry import context as otel_context
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from r2.host_hardening.telemetry import TelemetryPolicyError
from server.telemetry import (
    clear_baggage_for_provider_call,
    clears_baggage_at_provider_boundary,
    configure_test_tracer,
    configure_tracer_from_env,
    execution_span,
    public_job_ref,
)


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


async def test_provider_boundary_decorator_clears_baggage_and_restores_ambient_context() -> None:
    seen: list[dict[str, object]] = []

    @clears_baggage_at_provider_boundary
    async def _provider_entrypoint() -> str:
        seen.append(dict(baggage.get_all()))
        return "done"

    token = otel_context.attach(baggage.set_baggage("user_id", "u1"))
    try:
        assert await _provider_entrypoint() == "done"
        assert baggage.get_all() == {"user_id": "u1"}
    finally:
        otel_context.detach(token)

    assert seen == [{}]


async def test_provider_boundary_decorator_restores_ambient_context_on_error() -> None:
    @clears_baggage_at_provider_boundary
    async def _failing_entrypoint() -> None:
        raise RuntimeError("provider failed")

    token = otel_context.attach(baggage.set_baggage("project_name", "demo"))
    try:
        with pytest.raises(RuntimeError, match="provider failed"):
            await _failing_entrypoint()
        assert baggage.get_all() == {"project_name": "demo"}
    finally:
        otel_context.detach(token)


def test_public_job_ref_is_stable_within_a_process() -> None:
    a = public_job_ref("job-canary-1")
    b = public_job_ref("job-canary-1")
    assert a == b
    assert "job-canary-1" not in a


def test_tracer_is_not_installed_without_an_otlp_endpoint() -> None:
    assert configure_tracer_from_env({}, exporter_factory=InMemorySpanExporter) is None


@pytest.mark.parametrize("endpoint_var", ["OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"])
def test_tracer_exports_allowlisted_spans_when_an_otlp_endpoint_is_configured(endpoint_var: str) -> None:
    exporter = InMemorySpanExporter()
    provider = configure_tracer_from_env(
        {endpoint_var: "http://collector.invalid:4318", "DEPLOYMENT_ENVIRONMENT": "staging"},
        exporter_factory=lambda: exporter,
    )
    assert provider is not None

    with execution_span("unit.op", deployment_environment="staging", task_id="T-1"):
        pass
    provider.force_flush()

    (span,) = exporter.get_finished_spans()
    assert span.resource.attributes["service.name"] == "arcreel-host"
    assert span.resource.attributes["deployment.environment"] == "staging"
    assert dict(span.attributes or {})["task_id"] == "T-1"
    provider.shutdown()


def test_configured_propagator_never_injects_baggage_into_outbound_headers() -> None:
    from opentelemetry import propagate

    configure_tracer_from_env({}, exporter_factory=InMemorySpanExporter)
    configure_test_tracer()
    carrier: dict[str, str] = {}
    token = otel_context.attach(baggage.set_baggage("project_name", "demo"))
    try:
        with execution_span("unit.op", deployment_environment="test"):
            propagate.inject(carrier)
    finally:
        otel_context.detach(token)

    assert "traceparent" in carrier
    assert "baggage" not in carrier


@pytest.mark.parametrize(
    "boundary",
    [
        "lib.text_generator:TextGenerator.generate",
        "lib.media_generator:MediaGenerator.generate_image_async",
        "lib.media_generator:MediaGenerator.generate_audio_async",
        "lib.media_generator:MediaGenerator.generate_video_async",
        "lib.media_generator:MediaGenerator.resume_video_async",
        "lib.custom_provider.endpoint_test.trial_run:TrialRunManager._execute",
        "lib.custom_provider.discovery:discover_models",
        "server.services.generation_tasks:execute_generation_task",
        "server.services.resume_executor:execute_resume_video_task",
    ],
)
def test_every_provider_boundary_clears_baggage(boundary: str) -> None:
    import importlib

    module_name, qualname = boundary.split(":")
    target: object = importlib.import_module(module_name)
    for part in qualname.split("."):
        target = getattr(target, part)

    code = getattr(target, "__code__", None)
    assert code is not None, boundary
    assert code.co_name == "_cleared", boundary
