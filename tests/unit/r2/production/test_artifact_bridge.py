from copy import deepcopy

from r2.contracts import (
    ArtifactCurrencyStatus,
    ContentBasis,
    ContentBasisType,
)
from r2.production import (
    ArtifactHostSnapshot,
    DependencyResolverRegistry,
    DependencySnapshot,
    R2ArtifactBridge,
    R2ArtifactMetadata,
    R2ContractRef,
)


class Port:
    def __init__(self, snapshot: ArtifactHostSnapshot | None) -> None:
        self.snapshot = snapshot
        self.writes: list[tuple[str, R2ArtifactMetadata]] = []

    def load_artifact(self, artifact_key: str) -> ArtifactHostSnapshot | None:
        return self.snapshot

    def write_r2_metadata(
        self,
        artifact_key: str,
        metadata: R2ArtifactMetadata,
    ) -> None:
        self.writes.append((artifact_key, metadata))


class MappingResolver:
    def __init__(self, values: dict[str, DependencySnapshot]) -> None:
        self.values = values

    def supports(self, ref: str) -> bool:
        return ref in self.values

    def resolve(self, ref: str) -> DependencySnapshot:
        return self.values[ref]


def metadata(
    dependencies: list[DependencySnapshot],
) -> R2ArtifactMetadata:
    return R2ArtifactMetadata(
        metadata_schema_version="1",
        contract_ref=R2ContractRef(
            contract_type="ShotSpec",
            id="SH1",
            version=1,
            schema_version="2.1",
        ),
        content_basis=ContentBasis(
            basis_type=ContentBasisType.NARRATIVE,
            basis_version="canon-v7",
            refs=["event:1"],
        ),
        direct_dependencies=dependencies,
        content_fingerprint="c" * 64,
    )


def host(
    *,
    native_currency: ArtifactCurrencyStatus = ArtifactCurrencyStatus.CURRENT,
    r2_raw: dict | None,
) -> ArtifactHostSnapshot:
    return ArtifactHostSnapshot(
        artifact_key="shot:SH1",
        usable=True,
        native_currency=native_currency,
        r2_raw=r2_raw,
    )


def dep(version: str = "1", fingerprint: str = "a" * 64) -> DependencySnapshot:
    return DependencySnapshot(
        ref="r2:ShotSpec:SOURCE",
        version=version,
        fingerprint=fingerprint,
    )


def test_legacy_non_r2_artifact_has_no_r2_currency_override():
    bridge = R2ArtifactBridge(
        Port(host(r2_raw=None)),
        DependencyResolverRegistry([]),
    )

    result = bridge.evaluate_currency("shot:SH1")

    assert result.status is None
    assert result.reason == "legacy"


def test_missing_host_artifact_projects_missing():
    bridge = R2ArtifactBridge(
        Port(None),
        DependencyResolverRegistry([]),
    )

    result = bridge.evaluate_currency("shot:SH1")

    assert result.status is ArtifactCurrencyStatus.MISSING


def test_malformed_r2_metadata_is_blocked():
    bridge = R2ArtifactBridge(
        Port(host(r2_raw={"metadata_schema_version": "1"})),
        DependencyResolverRegistry([]),
    )

    result = bridge.evaluate_currency("shot:SH1")

    assert result.status is ArtifactCurrencyStatus.BLOCKED
    assert result.metadata is None


def test_native_missing_precedes_r2_dependency_evaluation():
    stored = metadata([dep()])
    bridge = R2ArtifactBridge(
        Port(
            host(
                native_currency=ArtifactCurrencyStatus.MISSING,
                r2_raw=stored.model_dump(mode="json"),
            )
        ),
        DependencyResolverRegistry([]),
    )

    result = bridge.evaluate_currency("shot:SH1")

    assert result.status is ArtifactCurrencyStatus.MISSING


def test_native_blocked_precedes_r2_dependency_evaluation():
    stored = metadata([dep()])
    bridge = R2ArtifactBridge(
        Port(
            host(
                native_currency=ArtifactCurrencyStatus.BLOCKED,
                r2_raw=stored.model_dump(mode="json"),
            )
        ),
        DependencyResolverRegistry([]),
    )

    result = bridge.evaluate_currency("shot:SH1")

    assert result.status is ArtifactCurrencyStatus.BLOCKED


def test_unchanged_direct_dependencies_are_current():
    stored_dep = dep()
    stored = metadata([stored_dep])
    resolver = MappingResolver({stored_dep.ref: stored_dep})
    bridge = R2ArtifactBridge(
        Port(host(r2_raw=stored.model_dump(mode="json"))),
        DependencyResolverRegistry([resolver]),
    )

    result = bridge.evaluate_currency("shot:SH1")

    assert result.status is ArtifactCurrencyStatus.CURRENT


def test_changed_direct_dependency_is_stale():
    stored_dep = dep()
    current_dep = dep(version="2", fingerprint="b" * 64)
    bridge = R2ArtifactBridge(
        Port(host(r2_raw=metadata([stored_dep]).model_dump(mode="json"))),
        DependencyResolverRegistry([MappingResolver({stored_dep.ref: current_dep})]),
    )

    result = bridge.evaluate_currency("shot:SH1")

    assert result.status is ArtifactCurrencyStatus.STALE


def test_unrelated_dependency_change_does_not_stale_artifact():
    stored_dep = dep()
    resolver = MappingResolver(
        {
            stored_dep.ref: stored_dep,
            "r2:Other:X": DependencySnapshot(
                ref="r2:Other:X",
                version="99",
                fingerprint="f" * 64,
            ),
        }
    )
    bridge = R2ArtifactBridge(
        Port(host(r2_raw=metadata([stored_dep]).model_dump(mode="json"))),
        DependencyResolverRegistry([resolver]),
    )

    result = bridge.evaluate_currency("shot:SH1")

    assert result.status is ArtifactCurrencyStatus.CURRENT


def test_unresolved_required_dependency_is_blocked():
    stored_dep = dep()
    bridge = R2ArtifactBridge(
        Port(host(r2_raw=metadata([stored_dep]).model_dump(mode="json"))),
        DependencyResolverRegistry([]),
    )

    result = bridge.evaluate_currency("shot:SH1")

    assert result.status is ArtifactCurrencyStatus.BLOCKED


def test_currency_evaluation_does_not_mutate_stored_dependency_snapshots():
    stored_dep = dep()
    stored = metadata([stored_dep])
    raw = stored.model_dump(mode="json")
    raw_before = deepcopy(raw)
    current_dep = dep(version="2", fingerprint="b" * 64)
    bridge = R2ArtifactBridge(
        Port(host(r2_raw=raw)),
        DependencyResolverRegistry([MappingResolver({stored_dep.ref: current_dep})]),
    )

    result = bridge.evaluate_currency("shot:SH1")

    assert result.status is ArtifactCurrencyStatus.STALE
    assert raw == raw_before
    assert result.metadata is not None
    assert result.metadata.direct_dependencies == [stored_dep]


def test_execution_only_fields_are_not_part_of_r2_artifact_metadata():
    fields = set(R2ArtifactMetadata.model_fields)

    assert "provider" not in fields
    assert "model" not in fields
    assert "endpoint" not in fields
    assert "seed" not in fields
    assert "resolution" not in fields
    assert "execution_fingerprint" not in fields
