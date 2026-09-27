"""OpenTelemetry installation and provider-boundary baggage for H7 (spec section 9).

Span emission and the HMAC provider-job reference live in ``lib.telemetry`` so
``lib`` seams can emit spans; they are re-exported here for existing callers.
This module owns tracer-provider installation (OTLP from the environment, or an
in-memory exporter for tests) and baggage clearing at provider entrypoints.
"""

from __future__ import annotations

import functools
import logging
import os
from collections.abc import Awaitable, Callable, Mapping

from opentelemetry import baggage, trace
from opentelemetry import context as otel_context
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from lib.telemetry import (
    DEFAULT_TELEMETRY_HMAC_KEY_VERSION,
    SERVICE_NAME,
    deployment_environment,
    execution_span,
    get_tracer,
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


def clear_baggage_for_provider_call() -> otel_context.Context:
    """Return a context with W3C baggage cleared for one outbound provider call.

    Baggage propagates to whatever the provider's own tracing picks up from
    request headers; it must never carry user/project/provider identity
    across that boundary, so this clears whatever the ambient context holds
    rather than trusting it was never set in the first place.
    """
    return baggage.clear(context=otel_context.get_current())


def clears_baggage_at_provider_boundary[**P, R](
    func: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R]]:
    """Run an async provider-boundary entrypoint inside a baggage-cleared context.

    Every provider call made while the wrapped coroutine runs sees an empty W3C
    baggage set; the caller's ambient context is restored when it returns or
    raises.
    """

    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        token = otel_context.attach(clear_baggage_for_provider_call())
        try:
            return await func(*args, **kwargs)
        finally:
            otel_context.detach(token)

    return wrapper


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
