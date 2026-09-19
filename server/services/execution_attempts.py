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
from r2.contracts.host_hardening import ProviderCapabilityProfile, ProviderRouteSnapshot
from r2.host_hardening.execution import ExecutionAttemptServiceImpl
from r2.host_hardening.host_submit import AttemptSubmitter, UsageExecutionBinder
from r2.host_hardening.ports import ProviderExecutionAdapter
from r2.host_hardening.provider_capabilities import DEFAULT_REGISTRY_PATH, load_capability_profile

AdapterRegistry = dict[str, ProviderExecutionAdapter]


class NoAdapterRegisteredError(LookupError):
    """No :class:`ProviderExecutionAdapter` is registered for this route's
    ``capability_profile_ref`` yet."""


def capability_resolver(registry_path: Path = DEFAULT_REGISTRY_PATH) -> Callable[[str], ProviderCapabilityProfile]:
    def _resolve(ref: str) -> ProviderCapabilityProfile:
        return load_capability_profile(ref, registry_path=registry_path)

    return _resolve


def build_adapter_resolver(registry: AdapterRegistry) -> Callable[[ProviderRouteSnapshot], ProviderExecutionAdapter]:
    """Resolve routes through an explicit, caller-owned backend registry."""

    def _resolve(route: ProviderRouteSnapshot) -> ProviderExecutionAdapter:
        adapter = registry.get(route.capability_profile_ref)
        if adapter is None:
            raise NoAdapterRegisteredError(
                f"no ProviderExecutionAdapter registered for {route.capability_profile_ref!r}"
            )
        return adapter

    return _resolve


def build_execution_attempt_service(
    session: AsyncSession,
    *,
    adapter_registry: AdapterRegistry,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
) -> ExecutionAttemptServiceImpl:
    resolver = capability_resolver(registry_path)
    repository = ExecutionAttemptRepository(session, capability_resolver=resolver)
    return ExecutionAttemptServiceImpl(
        repository,
        capability_resolver=resolver,
        adapter_resolver=build_adapter_resolver(adapter_registry),
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
