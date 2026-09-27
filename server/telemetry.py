"""OpenTelemetry installation for H7 (spec section 9).

Span emission, the HMAC provider-job reference and provider-boundary baggage
clearing live in ``lib.telemetry`` so ``lib`` seams can use them; they are
re-exported here for existing callers. This module owns tracer-provider and
propagator installation (OTLP from the environment, or an in-memory exporter
for tests).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from lib.telemetry import (
    DEFAULT_TELEMETRY_HMAC_KEY_VERSION,
    SERVICE_NAME,
    clear_baggage_for_provider_call,
    clears_baggage_at_provider_boundary,
    deployment_environment,
    execution_span,
    get_tracer,
    install_baggage_free_propagator,
    public_job_ref,
)

logger = logging.getLogger(__name__)

# Standard OpenTelemetry variables; either one enables OTLP/HTTP trace export.
OTLP_ENDPOINT_ENV_VARS = ("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "OTEL_EXPORTER_OTLP_ENDPOINT")


def _install_tracer_provider(provider: TracerProvider) -> None:
    # The OTel API refuses to override an already-set global TracerProvider:
    # a one-shot `Once` guard (independent of the stored value) makes every
    # call after the first a no-op with a warning. Installing a provider more
    # than once per process needs a genuine reset of both.
    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE._done = False
    trace.set_tracer_provider(provider)


def configure_tracer_from_env(
    environ: Mapping[str, str] | None = None,
    *,
    exporter_factory: Callable[[], SpanExporter] = OTLPSpanExporter,
) -> TracerProvider | None:
    """Install the production tracer when an OTLP endpoint is configured.

    With neither ``OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`` nor
    ``OTEL_EXPORTER_OTLP_ENDPOINT`` set, nothing is installed: spans stay on the
    API's no-op tracer and correlation relies on the durable IDs in the
    database. The default exporter reads endpoint, headers and timeout from the
    standard OTEL environment variables itself; the endpoint is never logged
    because it may embed credentials.
    """
    env = os.environ if environ is None else environ
    install_baggage_free_propagator()
    if not any(env.get(name) for name in OTLP_ENDPOINT_ENV_VARS):
        logger.info("OTLP 追踪导出未配置，跳过")
        return None
    provider = TracerProvider(
        resource=Resource.create({"service.name": SERVICE_NAME, "deployment.environment": deployment_environment(env)})
    )
    provider.add_span_processor(BatchSpanProcessor(exporter_factory()))
    _install_tracer_provider(provider)
    logger.info("OTLP 追踪导出已启用")
    return provider


def configure_test_tracer() -> InMemorySpanExporter:
    """Install a fresh in-memory exporter as the active tracer provider.

    Tests read exported spans directly from the returned exporter instead of
    scraping a real OTLP collector -- this is the "in-memory OTLP export"
    surface the H7 secret-canary tests scan for leaked content.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    _install_tracer_provider(provider)
    return exporter


__all__ = [
    "DEFAULT_TELEMETRY_HMAC_KEY_VERSION",
    "SERVICE_NAME",
    "clear_baggage_for_provider_call",
    "clears_baggage_at_provider_boundary",
    "configure_test_tracer",
    "configure_tracer_from_env",
    "deployment_environment",
    "execution_span",
    "get_tracer",
    "public_job_ref",
]
