from lib.artifact_manifest import ArtifactKey, ArtifactManifestEntry, ProjectArtifactManifestAdapter
from r2.contracts import ArtifactCurrencyStatus, ContentBasis, ContentBasisType
from r2.production import (
    ArcReelArtifactManifestPort,
    DependencyResolverRegistry,
    R2ArtifactBridge,
    R2ArtifactMetadata,
    R2ContractRef,
)


def metadata() -> R2ArtifactMetadata:
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
        direct_dependencies=[],
        content_fingerprint="c" * 64,
    )


def setup_entry(tmp_path, *, r2=None):
    key = ArtifactKey.episode_video(1, "SH1")
    adapter = ProjectArtifactManifestAdapter(tmp_path)
    assert adapter.put_entry(
        key,
        ArtifactManifestEntry(
            artifact_path="current.mp4",
            basis_digest="sha256-v1:" + ("a" * 64),
            r2=r2,
        ),
    )
    return key


def port(tmp_path):
    return ArcReelArtifactManifestPort(
        tmp_path,
        native_currency=lambda _artifact_key: ArtifactCurrencyStatus.CURRENT,
    )


def test_real_manifest_port_persists_and_reloads_r2_metadata(tmp_path):
    key = setup_entry(tmp_path)
    host = port(tmp_path)

    changed = host.write_r2_metadata(key.encode(), metadata())

    assert changed is True
    reloaded = ProjectArtifactManifestAdapter(tmp_path).get_entry(key)
    assert reloaded is not None
    assert reloaded.r2 == metadata().model_dump(mode="json")


def test_identical_r2_write_is_a_noop(tmp_path):
    key = setup_entry(tmp_path)
    host = port(tmp_path)

    assert host.write_r2_metadata(key.encode(), metadata()) is True
    assert host.write_r2_metadata(key.encode(), metadata()) is False


def test_legacy_manifest_entry_keeps_native_behavior(tmp_path):
    key = setup_entry(tmp_path)
    bridge = R2ArtifactBridge(port(tmp_path), DependencyResolverRegistry([]))

    result = bridge.evaluate_currency(key.encode())

    assert result.status is None
    assert result.reason == "legacy"


def test_malformed_r2_envelope_becomes_blocked_not_native_manifest_failure(tmp_path):
    key = setup_entry(tmp_path, r2="malformed")
    bridge = R2ArtifactBridge(port(tmp_path), DependencyResolverRegistry([]))

    result = bridge.evaluate_currency(key.encode())

    assert result.status is ArtifactCurrencyStatus.BLOCKED
    assert result.reason == "malformed_r2_metadata"
