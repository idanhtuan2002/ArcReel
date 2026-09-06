from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import ValidationError

from r2.contracts import ArtifactCurrencyStatus

from .artifact_metadata import R2ArtifactMetadata
from .dependency_resolver import (
    AmbiguousDependencyResolverError,
    DependencyResolverRegistry,
    UnresolvedDependencyError,
)


@dataclass(frozen=True)
class ArtifactHostSnapshot:
    artifact_key: str
    usable: bool
    native_currency: ArtifactCurrencyStatus
    r2_raw: dict[str, object] | None


@dataclass(frozen=True)
class R2CurrencyEvaluation:
    status: ArtifactCurrencyStatus | None
    reason: str
    metadata: R2ArtifactMetadata | None


class ArtifactManifestPort(Protocol):
    def load_artifact(
        self,
        artifact_key: str,
    ) -> ArtifactHostSnapshot | None: ...

    def write_r2_metadata(
        self,
        artifact_key: str,
        metadata: R2ArtifactMetadata,
    ) -> None: ...


class R2ArtifactBridge:
    def __init__(
        self,
        host: ArtifactManifestPort,
        resolvers: DependencyResolverRegistry,
    ) -> None:
        self._host = host
        self._resolvers = resolvers

    def evaluate_currency(
        self,
        artifact_key: str,
    ) -> R2CurrencyEvaluation:
        snapshot = self._host.load_artifact(artifact_key)
        if snapshot is None:
            return R2CurrencyEvaluation(
                status=ArtifactCurrencyStatus.MISSING,
                reason="host_missing",
                metadata=None,
            )

        if snapshot.r2_raw is None:
            return R2CurrencyEvaluation(
                status=None,
                reason="legacy",
                metadata=None,
            )

        try:
            metadata = R2ArtifactMetadata.model_validate(snapshot.r2_raw)
        except ValidationError:
            return R2CurrencyEvaluation(
                status=ArtifactCurrencyStatus.BLOCKED,
                reason="malformed_r2_metadata",
                metadata=None,
            )

        if snapshot.native_currency is ArtifactCurrencyStatus.MISSING:
            return R2CurrencyEvaluation(
                status=ArtifactCurrencyStatus.MISSING,
                reason="native_missing",
                metadata=metadata,
            )

        if snapshot.native_currency is ArtifactCurrencyStatus.BLOCKED:
            return R2CurrencyEvaluation(
                status=ArtifactCurrencyStatus.BLOCKED,
                reason="native_blocked",
                metadata=metadata,
            )

        try:
            current_dependencies = [
                self._resolvers.resolve(stored.ref)
                for stored in metadata.direct_dependencies
            ]
        except (
            UnresolvedDependencyError,
            AmbiguousDependencyResolverError,
            ValueError,
        ):
            return R2CurrencyEvaluation(
                status=ArtifactCurrencyStatus.BLOCKED,
                reason="dependency_unresolved",
                metadata=metadata,
            )

        if current_dependencies != metadata.direct_dependencies:
            return R2CurrencyEvaluation(
                status=ArtifactCurrencyStatus.STALE,
                reason="dependency_changed",
                metadata=metadata,
            )

        return R2CurrencyEvaluation(
            status=ArtifactCurrencyStatus.CURRENT,
            reason="dependencies_current",
            metadata=metadata,
        )
