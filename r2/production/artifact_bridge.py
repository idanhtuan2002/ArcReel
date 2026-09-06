from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from collections.abc import Callable
from typing import Protocol

from pydantic import ValidationError

from r2.contracts import ArtifactCurrencyStatus

from lib.artifact_manifest import ArtifactKey, ProjectArtifactManifestAdapter

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
    r2_raw: object | None


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
    ) -> bool: ...

    def promote_version_with_r2_metadata(
        self,
        artifact_key: str,
        *,
        host_version_ref: str,
        metadata: R2ArtifactMetadata,
    ) -> bool: ...


class ArtifactManifestConflictError(RuntimeError):
    pass


VersionPromotionCallback = Callable[[str, Callable[[], None]], object]


class ArcReelArtifactManifestPort:
    def __init__(
        self,
        project_dir: Path,
        *,
        native_currency: Callable[[str], ArtifactCurrencyStatus],
        version_promoter: VersionPromotionCallback | None = None,
    ) -> None:
        self._adapter = ProjectArtifactManifestAdapter(Path(project_dir))
        self._native_currency = native_currency
        self._version_promoter = version_promoter

    def _key(self, artifact_key: str) -> ArtifactKey:
        return ArtifactKey.decode(artifact_key)

    def load_artifact(self, artifact_key: str) -> ArtifactHostSnapshot | None:
        key = self._key(artifact_key)
        entry = self._adapter.get_entry(key)
        if entry is None:
            return None
        currency = self._native_currency(artifact_key)
        return ArtifactHostSnapshot(
            artifact_key=artifact_key,
            usable=currency in {
                ArtifactCurrencyStatus.CURRENT,
                ArtifactCurrencyStatus.STALE,
            },
            native_currency=currency,
            r2_raw=entry.r2,
        )

    def write_r2_metadata(
        self,
        artifact_key: str,
        metadata: R2ArtifactMetadata,
    ) -> bool:
        key = self._key(artifact_key)
        current = self._adapter.get_entry(key)
        if current is None:
            raise KeyError(artifact_key)
        replacement = replace(current, r2=metadata.model_dump(mode="json"))
        if replacement == current:
            return False
        changed = self._adapter.replace_entries_if_matches_atomically(
            expected={key: current},
            replacements={key: replacement},
        )
        if not changed:
            raise ArtifactManifestConflictError(
                f"artifact manifest changed while writing R2 metadata: {artifact_key}"
            )
        return True

    def promote_version_with_r2_metadata(
        self,
        artifact_key: str,
        *,
        host_version_ref: str,
        metadata: R2ArtifactMetadata,
    ) -> bool:
        if self._version_promoter is None:
            raise RuntimeError("version promotion is not configured")
        key = self._key(artifact_key)
        expected = self._adapter.get_entry(key)
        if expected is None:
            raise KeyError(artifact_key)
        replacement = replace(expected, r2=metadata.model_dump(mode="json"))
        if replacement == expected:
            return False

        def commit_manifest_selection() -> None:
            changed = self._adapter.replace_entries_if_matches_atomically(
                expected={key: expected},
                replacements={key: replacement},
            )
            if not changed:
                raise ArtifactManifestConflictError(
                    f"artifact manifest changed during version promotion: {artifact_key}"
                )

        self._version_promoter(host_version_ref, commit_manifest_selection)
        return True


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
