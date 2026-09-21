"""Host wiring for the execution-attempt service:
constructs :class:`ExecutionAttemptRepository` and
:class:`ExecutionAttemptServiceImpl` against a real database session and the
real qualified-capability registry.

Routes and workers import this module as the single composition point and
populate its :class:`AdapterRegistry` with one adapter per backend.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.repositories.host_hardening import ExecutionAttemptRepository
from lib.video_backends.execution_adapter import BackendCapabilityUnsupportedError
from r2.contracts.execution import ProviderRequest
from r2.contracts.host_hardening import (
    AttemptSnapshot,
    ProviderCapabilityProfile,
    ProviderObservation,
    ProviderRouteSnapshot,
)
from r2.host_hardening.execution import ExecutionAttemptServiceImpl
from r2.host_hardening.host_submit import AttemptSubmitter, UsageExecutionBinder
from r2.host_hardening.ports import ProviderExecutionAdapter
from r2.host_hardening.provider_capabilities import DEFAULT_REGISTRY_PATH, load_capability_profile

AdapterRegistry = dict[str, ProviderExecutionAdapter]


class NoAdapterRegisteredError(LookupError):
    """No :class:`ProviderExecutionAdapter` is registered for this route's
    ``capability_profile_ref`` yet."""


class _CapabilityUnsupportedAdapter:
    """Fallback for a route with no real registered adapter: every
    provider-facing call fails exactly like ``BackendExecutionAdapter`` already
    does for a backend that declares no function for a capability, so a caller
    (a recovery scan) needs only one exception type to handle regardless of
    whether "no adapter yet" or "adapter has no cancel" is the real reason."""

    def __init__(self, capability_profile: ProviderCapabilityProfile) -> None:
        self.capability_profile = capability_profile

    async def submit(self, *, attempt: AttemptSnapshot, request: ProviderRequest) -> ProviderObservation:
        raise BackendCapabilityUnsupportedError(f"no adapter registered for {self.capability_profile.ref}")

    async def poll(self, attempt: AttemptSnapshot) -> ProviderObservation:
        raise BackendCapabilityUnsupportedError(f"no adapter registered for {self.capability_profile.ref}")

    async def cancel(self, attempt: AttemptSnapshot) -> ProviderObservation:
        raise BackendCapabilityUnsupportedError(f"no adapter registered for {self.capability_profile.ref}")

    async def reconcile(self, attempt: AttemptSnapshot) -> ProviderObservation | None:
        return None


def capability_resolver(registry_path: Path = DEFAULT_REGISTRY_PATH) -> Callable[[str], ProviderCapabilityProfile]:
    def _resolve(ref: str) -> ProviderCapabilityProfile:
        return load_capability_profile(ref, registry_path=registry_path)

    return _resolve


def build_adapter_resolver(
    registry: AdapterRegistry,
    *,
    default_to_unsupported: bool = False,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
) -> Callable[[ProviderRouteSnapshot], ProviderExecutionAdapter]:
    """Resolve routes through an explicit, caller-owned backend registry.

    ``default_to_unsupported=True`` (recovery scans only -- never submit,
    which must fail loud on a real misconfiguration) returns
    :class:`_CapabilityUnsupportedAdapter` instead of raising for a route
    nothing has registered a real adapter for yet: today that is every route
    except Kling's poll, and cancel for every route including Kling's (no
    backend declares ``supports_cancel: true``). The scans' own exception
    handling already treats that as "leave it, cannot realize this safely",
    which is the correct outcome, not a configuration error to fail loud on.
    """

    def _resolve(route: ProviderRouteSnapshot) -> ProviderExecutionAdapter:
        adapter = registry.get(route.capability_profile_ref)
        if adapter is not None:
            return adapter
        if default_to_unsupported:
            profile = load_capability_profile(route.capability_profile_ref, registry_path=registry_path)
            return _CapabilityUnsupportedAdapter(profile)
        raise NoAdapterRegisteredError(f"no ProviderExecutionAdapter registered for {route.capability_profile_ref!r}")

    return _resolve


def build_execution_attempt_service(
    session: AsyncSession,
    *,
    adapter_registry: AdapterRegistry,
    default_to_unsupported: bool = False,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
) -> ExecutionAttemptServiceImpl:
    resolver = capability_resolver(registry_path)
    repository = ExecutionAttemptRepository(session, capability_resolver=resolver)
    return ExecutionAttemptServiceImpl(
        repository,
        capability_resolver=resolver,
        adapter_resolver=build_adapter_resolver(
            adapter_registry, default_to_unsupported=default_to_unsupported, registry_path=registry_path
        ),
        commit=session.commit,
    )


def build_attempt_submitter(
    session: AsyncSession,
    *,
    user_id: str,
    project_name: str,
    usage_binder: UsageExecutionBinder | None,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
) -> AttemptSubmitter:
    resolver = capability_resolver(registry_path)
    repository = ExecutionAttemptRepository(session, capability_resolver=resolver)
    service = ExecutionAttemptServiceImpl(
        repository,
        capability_resolver=resolver,
        adapter_resolver=build_adapter_resolver({}),
        commit=session.commit,
    )
    return AttemptSubmitter(
        repository=repository,
        service=service,
        capability_resolver=resolver,
        user_id=user_id,
        project_name=project_name,
        usage_binder=usage_binder,
    )


__all__ = [
    "AdapterRegistry",
    "NoAdapterRegisteredError",
    "build_adapter_resolver",
    "build_attempt_submitter",
    "build_execution_attempt_service",
    "capability_resolver",
]
