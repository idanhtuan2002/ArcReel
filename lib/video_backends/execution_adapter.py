"""Generic ``ProviderExecutionAdapter`` wrapping backend execution callables.

Adapters return observations and never mutate attempt state. This class
enforces that structurally: it is a thin pass-through to
caller-supplied functions shaped exactly like the M7 contracts, with no
backend-specific HTTP logic of its own. Each real video backend supplies a
small translation layer from that
backend's existing create/poll/cancel functions (``lib.video_backends.base``)
into these callables; wiring bounded retry, ``AmbiguousSubmitError``
classification and the rest of the existing submit/poll machinery is that
translation layer's job, reused as-is rather than duplicated here.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from r2.contracts.execution import ProviderRequest
from r2.contracts.host_hardening import AttemptSnapshot, ProviderCapabilityProfile, ProviderObservation

SubmitFn = Callable[[AttemptSnapshot, ProviderRequest], Awaitable[ProviderObservation]]
PollFn = Callable[[AttemptSnapshot], Awaitable[ProviderObservation]]
CancelFn = Callable[[AttemptSnapshot], Awaitable[ProviderObservation]]
ReconcileFn = Callable[[AttemptSnapshot], Awaitable[ProviderObservation | None]]


@dataclass(frozen=True)
class BackendExecutionFunctions:
    submit: SubmitFn
    poll: PollFn
    cancel: CancelFn | None = None
    reconcile: ReconcileFn | None = None


class BackendCapabilityUnsupportedError(NotImplementedError):
    """The wrapped backend declared no callable for this capability (e.g. no
    ``cancel`` function was supplied)."""


class BackendExecutionAdapter:
    """``ProviderExecutionAdapter`` over one backend's
    :class:`BackendExecutionFunctions`."""

    def __init__(self, capability_profile: ProviderCapabilityProfile, functions: BackendExecutionFunctions) -> None:
        self.capability_profile = capability_profile
        self._functions = functions

    async def submit(self, *, attempt: AttemptSnapshot, request: ProviderRequest) -> ProviderObservation:
        return await self._functions.submit(attempt, request)

    async def poll(self, attempt: AttemptSnapshot) -> ProviderObservation:
        return await self._functions.poll(attempt)

    async def cancel(self, attempt: AttemptSnapshot) -> ProviderObservation:
        if self._functions.cancel is None:
            raise BackendCapabilityUnsupportedError(f"{self.capability_profile.ref} does not support cancel")
        return await self._functions.cancel(attempt)

    async def reconcile(self, attempt: AttemptSnapshot) -> ProviderObservation | None:
        if self._functions.reconcile is None:
            return None
        return await self._functions.reconcile(attempt)


__all__ = [
    "BackendCapabilityUnsupportedError",
    "BackendExecutionAdapter",
    "BackendExecutionFunctions",
    "CancelFn",
    "PollFn",
    "ReconcileFn",
    "SubmitFn",
]
