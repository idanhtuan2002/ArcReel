"""OpenTelemetry wiring for M7-D's H7 correlation (spec section 9).

Real spans join the durable ID chain within one process lifetime. A restart
begins a new trace; ``execution_span``'s ``linked_trace_id`` parameter links
the new trace back to the prior one when the caller has a stored trace_id for
this execution, so an operator can still follow an attempt across a crash
without the durable-ID join ever depending on span continuity.

Every attribute this module puts on a span is validated against
``r2.host_hardening.telemetry``'s allowlist before it is set -- this module
never re-decides what is safe to attach, only how to attach it.
"""

from __future__ import annotations

import functools
import logging
import os
import secrets
from collections.abc import Awaitable, Callable, Generator
from contextlib import contextmanager

from opentelemetry import baggage, trace
from opentelemetry import context as otel_context
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Link, Span, SpanContext, TraceFlags

from r2.host_hardening.telemetry import assert_span_attributes_allowed, public_provider_job_ref

logger = logging.getLogger(__name__)

SERVICE_NAME = "arcreel-host"
DEFAULT_TELEMETRY_HMAC_KEY_VERSION = "v1"

_cached_hmac_key: bytes | None = None


def _telemetry_hmac_key() -> tuple[bytes, str]:
    """Key + version for ``public_job_ref``.

    Mirrors ``server.auth.get_token_secret``'s convention: an operator-supplied
    env var takes priority, otherwise a key is generated once and cached for
    this process's lifetime (never persisted -- a restart naturally rotates it,
    which is safe here since the raw provider job ID is never derived *from*
    the reference, only correlated *by* it within one process's telemetry).
    """
    global _cached_hmac_key

    version = os.environ.get("ARCREEL_TELEMETRY_HMAC_KEY_VERSION", DEFAULT_TELEMETRY_HMAC_KEY_VERSION)
    env_key = os.environ.get("ARCREEL_TELEMETRY_HMAC_KEY")
    if env_key:
        return env_key.encode("utf-8"), version

    if _cached_hmac_key is None:
        _cached_hmac_key = secrets.token_bytes(32)
        logger.info("已自动生成遥测 HMAC 密钥（进程内缓存，未持久化）")
    return _cached_hmac_key, version


def public_job_ref(raw_provider_job_id: str) -> str:
    """``public_provider_job_ref`` bound to this process's telemetry key."""
    key, version = _telemetry_hmac_key()
    return public_provider_job_ref(raw_provider_job_id, key=key, key_version=version)


def configure_test_tracer() -> InMemorySpanExporter:
    """Install a fresh in-memory exporter as the active tracer provider.

    Tests read exported spans directly from the returned exporter instead of
    scraping a real OTLP collector -- this is the "in-memory OTLP export"
    surface the H7 secret-canary tests scan for leaked content.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    # The OTel API refuses to override an already-set global TracerProvider:
    # a one-shot `Once` guard (independent of the stored value) makes every
    # call after the first a no-op with a warning. Tests calling this more
    # than once per process need a genuine reset of both.
    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE._done = False
    trace.set_tracer_provider(provider)
    return exporter


def get_tracer() -> trace.Tracer:
    return trace.get_tracer("arcreel.host_hardening")


def _external_span_links(linked_trace_id: str | None) -> list[Link]:
    if linked_trace_id is None:
        return []
    try:
        trace_id_int = int(linked_trace_id, 16)
    except ValueError:
        return []
    span_context = SpanContext(
        trace_id=trace_id_int,
        span_id=0x1,
        is_remote=True,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )
    return [Link(span_context)]


@contextmanager
def execution_span(
    operation_name: str,
    *,
    deployment_environment: str,
    attempt_state: str | None = None,
    provider_id: str | None = None,
    failure_reason_code: str | None = None,
    linked_trace_id: str | None = None,
    **durable_ids: str,
) -> Generator[Span]:
    """Start a span carrying only H7-allowlisted attributes.

    ``attempt_state``/``provider_id``/``failure_reason_code`` are omitted
    entirely when the caller doesn't have them at this point in the pipeline
    -- the allowlist governs what a span is *permitted* to carry, not what
    every span must carry. ``durable_ids`` accepts any subset of the durable
    ID chain (``task_id``, ``execution_id``, ``provider_job_ref``,
    ``candidate_id``, ...); unknown keys are rejected before the span is even
    created.
    """
    attributes: dict[str, str] = {
        "service.name": SERVICE_NAME,
        "deployment.environment": deployment_environment,
        "operation.name": operation_name,
        **durable_ids,
    }
    if attempt_state is not None:
        attributes["attempt.state"] = attempt_state
    if provider_id is not None:
        attributes["provider.id"] = provider_id
    if failure_reason_code is not None:
        attributes["failure.reason_code"] = failure_reason_code
    assert_span_attributes_allowed(attributes)

    with get_tracer().start_as_current_span(operation_name, links=_external_span_links(linked_trace_id)) as span:
        for key, value in attributes.items():
            span.set_attribute(key, value)
        yield span


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
    "execution_span",
    "get_tracer",
    "public_job_ref",
]
