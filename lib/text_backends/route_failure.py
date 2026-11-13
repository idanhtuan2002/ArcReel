"""Whether a text call failed because of its route (the model or its provider), not because of what it was asked.

A route failure is worth retrying on another model (ADR-0139): quota or rate exhausted, the key refused, the model
missing, the provider down or unreachable. An answer that does not fit its schema, a refused prompt or a bad request
is not: another model would be asked the same thing.
"""

from __future__ import annotations

#: HTTP statuses that name the route: payment/quota, auth, missing model, timeout, rate, and server errors.
ROUTE_STATUSES = frozenset({401, 402, 403, 404, 408, 429})
_TRANSPORT_NAMES = frozenset(
    {
        "APIConnectionError",
        "APITimeoutError",
        "ConnectError",
        "ConnectTimeout",
        "ReadTimeout",
        "RemoteProtocolError",
        "TransportError",
        "TimeoutException",
        "ServiceUnavailable",
        "ResourceExhausted",
        "OllamaUnavailableError",
    }
)


def _status(error: BaseException) -> int | None:
    for value in (
        getattr(error, "status_code", None),
        getattr(getattr(error, "response", None), "status_code", None),
        getattr(error, "code", None),
        getattr(error, "status", None),
    ):
        if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599:
            return value
    return None


def is_route_failure(error: BaseException) -> bool:
    """``error`` or any error it was raised from names its route (see the module docstring)."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (TimeoutError, ConnectionError)):
            return True
        if any(cls.__name__ in _TRANSPORT_NAMES for cls in type(current).__mro__):
            return True
        status = _status(current)
        if status is not None and (status in ROUTE_STATUSES or status >= 500):
            return True
        current = current.__cause__ or current.__context__
    return False


__all__ = ["ROUTE_STATUSES", "is_route_failure"]
