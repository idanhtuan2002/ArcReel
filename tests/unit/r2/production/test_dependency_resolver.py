import pytest

from r2.production import (
    AmbiguousDependencyResolverError,
    DependencyResolverRegistry,
    DependencySnapshot,
    UnresolvedDependencyError,
)


class Resolver:
    def __init__(self, prefix: str, snapshot: DependencySnapshot) -> None:
        self.prefix = prefix
        self.snapshot = snapshot

    def supports(self, ref: str) -> bool:
        return ref.startswith(self.prefix)

    def resolve(self, ref: str) -> DependencySnapshot:
        return self.snapshot


def snapshot() -> DependencySnapshot:
    return DependencySnapshot(
        ref="r2:ShotSpec:SH1",
        version="1",
        fingerprint="a" * 64,
    )


def test_registry_resolves_exactly_one_claimant():
    expected = snapshot()
    registry = DependencyResolverRegistry([Resolver("r2:", expected)])

    actual = registry.resolve(expected.ref)

    assert actual == expected


def test_registry_rejects_zero_claimants():
    registry = DependencyResolverRegistry([])

    with pytest.raises(UnresolvedDependencyError):
        registry.resolve("canon:Event:E1")


def test_registry_rejects_multiple_claimants():
    expected = snapshot()
    registry = DependencyResolverRegistry(
        [
            Resolver("r2:", expected),
            Resolver("r2:Shot", expected),
        ]
    )

    with pytest.raises(AmbiguousDependencyResolverError):
        registry.resolve(expected.ref)


def test_registry_rejects_resolver_returning_different_ref():
    wrong = DependencySnapshot(
        ref="r2:ShotSpec:OTHER",
        version="1",
        fingerprint="a" * 64,
    )
    registry = DependencyResolverRegistry([Resolver("r2:", wrong)])

    with pytest.raises(ValueError, match="resolver returned"):
        registry.resolve("r2:ShotSpec:SH1")
