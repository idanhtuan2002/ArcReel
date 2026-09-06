from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from .artifact_metadata import DependencySnapshot


class DependencyResolver(Protocol):
    def supports(self, ref: str) -> bool: ...

    def resolve(self, ref: str) -> DependencySnapshot: ...


class UnresolvedDependencyError(LookupError):
    pass


class AmbiguousDependencyResolverError(LookupError):
    pass


class DependencyResolverRegistry:
    def __init__(
        self,
        resolvers: Iterable[DependencyResolver] = (),
    ) -> None:
        self._resolvers = list(resolvers)

    def register(self, resolver: DependencyResolver) -> None:
        self._resolvers.append(resolver)

    def resolve(self, ref: str) -> DependencySnapshot:
        matches = [resolver for resolver in self._resolvers if resolver.supports(ref)]
        if not matches:
            raise UnresolvedDependencyError(ref)
        if len(matches) != 1:
            raise AmbiguousDependencyResolverError(ref)

        snapshot = matches[0].resolve(ref)
        if snapshot.ref != ref:
            raise ValueError(
                f"resolver returned {snapshot.ref!r} for {ref!r}"
            )
        return snapshot
