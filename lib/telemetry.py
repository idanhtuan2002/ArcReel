"""Secret-safe span emission for H7 correlation (spec section 9).

Real spans join the durable ID chain within one process lifetime. A restart
begins a new trace; ``execution_span``'s ``linked_trace_id`` parameter links
the new trace back to the prior one when the caller has a stored trace_id for
this execution, so an operator can still follow an attempt across a crash
without the durable-ID join ever depending on span continuity.

Every attribute this module puts on a span is validated against
``r2.host_hardening.telemetry``'s allowlist before it is set -- this module
never re-decides what is safe to attach, only how to attach it. Exporter and
provider installation live in ``server.telemetry``; without an installed
provider these spans go to the OpenTelemetry API's no-op tracer.
"""

from __future__ import annotations

import functools
import logging
import os
import secrets
from collections.abc import Callable, Coroutine, Generator, Mapping
from contextlib import contextmanager
from typing import Any

from opentelemetry import baggage, propagate, trace
from opentelemetry import context as otel_context
from opentelemetry.trace import Link, Span, SpanContext, Status, StatusCode, TraceFlags
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from r2.host_hardening.telemetry import assert_span_attributes_allowed, public_provider_job_ref

logger = logging.getLogger(__name__)

SERVICE_NAME = "arcreel-host"
DEFAULT_TELEMETRY_HMAC_KEY_VERSION = "v1"
DEPLOYMENT_ENVIRONMENT_ENV = "DEPLOYMENT_ENVIRONMENT"
DEFAULT_DEPLOYMENT_ENVIRONMENT = "development"

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


def deployment_environment(environ: Mapping[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    return env.get(DEPLOYMENT_ENVIRONMENT_ENV) or DEFAULT_DEPLOYMENT_ENVIRONMENT


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

    # Exception events and the default error-status description would copy the
    # raw exception message (URLs, prompts, provider IDs) onto the span; only
    # the exception class name is recorded, as ``failure.reason_code``.
    with get_tracer().start_as_current_span(
        operation_name,
        links=_external_span_links(linked_trace_id),
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        for key, value in attributes.items():
            span.set_attribute(key, value)
        try:
            yield span
        except Exception as exc:
            span.set_attribute("failure.reason_code", type(exc).__name__)
            span.set_status(Status(StatusCode.ERROR))
            raise


def record_correlation_span(
    operation_name: str,
    *,
    provider_id: str | None = None,
    attempt_state: str | None = None,
    **durable_ids: str | None,
) -> None:
    """Emit one completed span joining the durable IDs that are known here."""
    with correlation_span(operation_name, provider_id=provider_id, attempt_state=attempt_state, **durable_ids):
        pass


@contextmanager
def correlation_span(
    operation_name: str,
    *,
    provider_id: str | None = None,
    attempt_state: str | None = None,
    **durable_ids: str | None,
) -> Generator[Span]:
    """``execution_span`` for this deployment, dropping IDs that are not known yet."""
    known_ids = {key: value for key, value in durable_ids.items() if value is not None}
    with execution_span(
        operation_name,
        deployment_environment=deployment_environment(),
        provider_id=provider_id,
        attempt_state=attempt_state,
        **known_ids,
    ) as span:
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
    func: Callable[P, Coroutine[Any, Any, R]],
) -> Callable[P, Coroutine[Any, Any, R]]:
    """Run an async provider-boundary entrypoint inside a baggage-cleared context.

    Every provider call made while the wrapped coroutine runs sees an empty W3C
    baggage set; the caller's ambient context is restored when it returns or
    raises.
    """

    @functools.wraps(func)
    async def _cleared(*args: P.args, **kwargs: P.kwargs) -> R:
        token = otel_context.attach(clear_baggage_for_provider_call())
        try:
            return await func(*args, **kwargs)
        finally:
            otel_context.detach(token)

    return _cleared


def install_baggage_free_propagator() -> None:
    """Propagate W3C trace context only, never W3C baggage, on every outbound carrier.

    The OpenTelemetry default propagator injects both ``traceparent`` and
    ``baggage``; with this installed, no instrumented client in the process can
    forward ambient baggage to a provider, whatever calls it.
    """
    propagate.set_global_textmap(TraceContextTextMapPropagator())


__all__ = [
    "DEFAULT_DEPLOYMENT_ENVIRONMENT",
    "DEFAULT_TELEMETRY_HMAC_KEY_VERSION",
    "DEPLOYMENT_ENVIRONMENT_ENV",
    "SERVICE_NAME",
    "clear_baggage_for_provider_call",
    "clears_baggage_at_provider_boundary",
    "correlation_span",
    "deployment_environment",
    "execution_span",
    "get_tracer",
    "install_baggage_free_propagator",
    "public_job_ref",
    "record_correlation_span",
]
