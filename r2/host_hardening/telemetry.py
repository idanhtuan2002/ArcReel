"""Secret-safe telemetry correlation policy (M7-D, spec section 9, H7).

Every generation is joinable by durable IDs: ``request_id -> method_decision_id
-> task_id -> execution_id -> provider_job_ref -> candidate_id -> master_version
-> usage_entry_id``. This module is the one place that decides which attribute
keys may ever reach a span, a log record, or a metric label -- everything else
(``server/telemetry.py``'s span helper, every call site that sets an attribute)
must go through the functions here rather than re-deciding the policy locally.

Two different bars apply on purpose:

- Durable identity attributes (``DURABLE_ID_ATTRIBUTES``) may appear on spans,
  in logs, and in trace exemplars -- they correlate one execution across its
  whole lifetime and are exactly what an operator needs to debug a specific
  failure.
- Metric labels must stay low-cardinality (``REQUIRED_LOW_CARDINALITY_ATTRIBUTES``
  only) -- a per-execution ID as a metric label is a well-known cardinality
  explosion, not merely a style preference.

Raw provider job IDs never leave the execution repository: every other
consumer uses ``public_provider_job_ref``'s keyed-HMAC reference instead.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping

REQUIRED_LOW_CARDINALITY_ATTRIBUTES = frozenset(
    {
        "service.name",
        "deployment.environment",
        "operation.name",
        "attempt.state",
        "provider.id",
        "failure.reason_code",
    }
)

# Durable identity chain (spec section 9) -- fine on spans/logs/exemplars,
# never on a metric label.
DURABLE_ID_ATTRIBUTES = frozenset(
    {
        "request_id",
        "method_decision_id",
        "task_id",
        "execution_id",
        "provider_job_ref",
        "candidate_id",
        "master_version",
        "usage_entry_id",
    }
)

ALLOWED_SPAN_ATTRIBUTES = REQUIRED_LOW_CARDINALITY_ATTRIBUTES | DURABLE_ID_ATTRIBUTES

_PROVIDER_JOB_REF_PREFIX = "pjr"


class TelemetryPolicyError(Exception):
    """An attribute or metric label violates the H7 allowlist."""


def public_provider_job_ref(raw_id: str, *, key: bytes, key_version: str) -> str:
    """A deterministic, non-reversible reference standing in for ``raw_id``.

    Keyed (not a bare hash) so the reference cannot be brute-forced from a
    guessed/enumerable raw ID space by anyone without ``key``; versioned so a
    key rotation doesn't silently break correlation across the rotation --
    old references keep resolving via the old key version, looked up in the
    execution repository, which is the only place the raw ID is ever stored.
    """
    if not raw_id:
        raise ValueError("raw_id must be non-empty")
    digest = hmac.new(key, raw_id.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{_PROVIDER_JOB_REF_PREFIX}:{key_version}:{digest[:32]}"


def assert_metric_labels_allowed(labels: Mapping[str, object]) -> None:
    """Fail closed if a metric label carries a durable identity attribute."""
    disallowed = set(labels) - REQUIRED_LOW_CARDINALITY_ATTRIBUTES
    if disallowed:
        raise TelemetryPolicyError(f"metric labels {sorted(disallowed)} are not in the low-cardinality allowlist")


def assert_span_attributes_allowed(attributes: Mapping[str, object]) -> None:
    """Fail closed if a span attribute key is not on the H7 allowlist.

    This is the last line of defense against a raw content, credential, or
    other unvetted field being attached to a span by a future caller.
    """
    disallowed = set(attributes) - ALLOWED_SPAN_ATTRIBUTES
    if disallowed:
        raise TelemetryPolicyError(f"span attributes {sorted(disallowed)} are not in the H7 allowlist")


__all__ = [
    "ALLOWED_SPAN_ATTRIBUTES",
    "DURABLE_ID_ATTRIBUTES",
    "REQUIRED_LOW_CARDINALITY_ATTRIBUTES",
    "TelemetryPolicyError",
    "assert_metric_labels_allowed",
    "assert_span_attributes_allowed",
    "public_provider_job_ref",
]
