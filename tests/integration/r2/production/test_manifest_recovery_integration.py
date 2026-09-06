from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier

from lib.artifact_manifest import (
    ArtifactKey,
    ArtifactManifestEntry,
    ProjectArtifactManifestAdapter,
)
from lib.version_manager import VersionManager
from r2.contracts import (
    ArtifactCurrencyStatus,
    CandidateSelectionStatus,
    ContentBasis,
    ContentBasisType,
    GenerationCandidate,
    GenerationLifecycleStatus,
)
from r2.production import (
    ApprovedMasterMetadata,
    ArcReelArtifactManifestPort,
    ArcReelVersionRestorePromoter,
    ArtifactManifestConflictError,
    DependencyResolverRegistry,
    DependencySnapshot,
    ProductionApprovalService,
    R2ArtifactBridge,
    R2ArtifactMetadata,
    R2ContractRef,
)


BASIS_DIGEST = "sha256-v1:" + ("a" * 64)


def contract_ref() -> R2ContractRef:
    return R2ContractRef(
        contract_type="ShotSpec",
        id="SH1",
        version=1,
        schema_version="2.1",
    )


def content_basis() -> ContentBasis:
    return ContentBasis(
        basis_type=ContentBasisType.NARRATIVE,
        basis_version="canon-v7",
        refs=["event:1"],
    )


def dependency(
    *,
    version: str = "1",
    fingerprint: str = "d" * 64,
) -> DependencySnapshot:
    return DependencySnapshot(
        ref="r2:ProductionBinding:B1",
        version=version,
        fingerprint=fingerprint,
    )


def approved_master(
    candidate_id: str,
    host_version_ref: str,
) -> ApprovedMasterMetadata:
    return ApprovedMasterMetadata(
        selected_candidate_id=candidate_id,
        host_version_ref=host_version_ref,
        approval_record=f"approval:{candidate_id}",
        selected_at=datetime(2026, 9, 6, 18, 0, tzinfo=timezone.utc),
        selected_by="showrunner:1",
    )


def metadata(
    *,
    fingerprint: str = "c" * 64,
    dependencies: list[DependencySnapshot] | None = None,
    master: ApprovedMasterMetadata | None = None,
) -> R2ArtifactMetadata:
    return R2ArtifactMetadata(
        metadata_schema_version="1",
        contract_ref=contract_ref(),
        content_basis=content_basis(),
        direct_dependencies=dependencies or [],
        content_fingerprint=fingerprint,
        approved_master=master,
    )


def candidate(candidate_id: str) -> GenerationCandidate:
    return GenerationCandidate(
        id=candidate_id,
        target_ref="SH1",
        content_fingerprint="c" * 64,
        execution_fingerprint=("e" if candidate_id == "C" else "f") * 64,
        provider_execution_ref=f"job:{candidate_id}",
        output_asset_ref=f"asset:{candidate_id}",
        lifecycle_state=GenerationLifecycleStatus.GENERATED,
        selection_state=CandidateSelectionStatus.UNREVIEWED,
    )


def key() -> ArtifactKey:
    return ArtifactKey.episode_video(1, "SH1")


def native_current(_artifact_key: str) -> ArtifactCurrencyStatus:
    return ArtifactCurrencyStatus.CURRENT


def install_manifest_entry(
    tmp_path,
    value: R2ArtifactMetadata,
) -> ArtifactKey:
    artifact_key = key()
    adapter = ProjectArtifactManifestAdapter(tmp_path)
    assert adapter.put_entry(
        artifact_key,
        ArtifactManifestEntry(
            artifact_path="current.mp4",
            basis_digest=BASIS_DIGEST,
            r2=value.model_dump(mode="json"),
        ),
    )
    return artifact_key


def setup_master_b(tmp_path):
    current = tmp_path / "current.mp4"
    staged_b = tmp_path / "B.staged.mp4"
    staged_b.write_bytes(b"MASTER-B")

    versions = VersionManager(tmp_path)
    b = versions.commit_staged_paid_version(
        "videos",
        "SH1",
        "B",
        staged_file=staged_b,
        current_file=current,
        select_current=True,
    )
    assert b.selected is True

    artifact_key = install_manifest_entry(
        tmp_path,
        metadata(master=approved_master("B", str(b.version))),
    )
    return current, versions, artifact_key, b.version


def add_unapproved_version(
    tmp_path,
    versions: VersionManager,
    current,
    candidate_id: str,
    payload: bytes,
) -> int:
    staged = tmp_path / f"{candidate_id}.staged.mp4"
    staged.write_bytes(payload)
    result = versions.commit_staged_paid_version(
        "videos",
        "SH1",
        candidate_id,
        staged_file=staged,
        current_file=current,
        select_current=False,
    )
    assert result.selected is False
    return result.version


def port(
    tmp_path,
    *,
    versions: VersionManager | None = None,
    current=None,
):
    promoter = None
    if versions is not None:
        promoter = ArcReelVersionRestorePromoter(
            versions,
            resource_type="videos",
            resource_id="SH1",
            current_file=current,
        )
    return ArcReelArtifactManifestPort(
        tmp_path,
        native_currency=native_current,
        version_promoter=promoter,
    )


def loaded_metadata(tmp_path, artifact_key: ArtifactKey) -> R2ArtifactMetadata:
    entry = ProjectArtifactManifestAdapter(tmp_path).get_entry(artifact_key)
    assert entry is not None
    return R2ArtifactMetadata.model_validate(entry.r2)


class MappingResolver:
    def __init__(self, values: dict[str, DependencySnapshot]) -> None:
        self.values = values

    def supports(self, ref: str) -> bool:
        return ref in self.values

    def resolve(self, ref: str) -> DependencySnapshot:
        return self.values[ref]


def test_restart_reload_preserves_r2_metadata(tmp_path):
    original = metadata(
        dependencies=[dependency()],
        master=approved_master("B", "1"),
    )
    artifact_key = install_manifest_entry(tmp_path, original)

    first = port(tmp_path).load_artifact(artifact_key.encode())
    assert first is not None
    assert R2ArtifactMetadata.model_validate(first.r2_raw) == original

    reloaded = ArcReelArtifactManifestPort(
        tmp_path,
        native_currency=native_current,
    ).load_artifact(artifact_key.encode())

    assert reloaded is not None
    assert R2ArtifactMetadata.model_validate(reloaded.r2_raw) == original


def test_restart_reload_preserves_approved_master_and_active_version(tmp_path):
    current, versions, artifact_key, _b_version = setup_master_b(tmp_path)
    c_version = add_unapproved_version(
        tmp_path,
        versions,
        current,
        "C",
        b"CANDIDATE-C",
    )

    service = ProductionApprovalService(
        port(tmp_path, versions=versions, current=current)
    )
    service.promote(
        artifact_key=artifact_key.encode(),
        candidate=candidate("C"),
        host_version_ref=str(c_version),
        approval_record="approval:C",
        selected_by="showrunner:1",
        selected_at=datetime(2026, 9, 6, 19, 0, tzinfo=timezone.utc),
    )

    restarted_versions = VersionManager(tmp_path)
    restarted_master = loaded_metadata(tmp_path, artifact_key).approved_master

    assert restarted_versions.get_current_version("videos", "SH1") == c_version
    assert restarted_master is not None
    assert restarted_master.selected_candidate_id == "C"
    assert restarted_master.host_version_ref == str(c_version)
    assert current.read_bytes() == b"CANDIDATE-C"


def test_stale_currency_evaluation_does_not_refresh_stored_dependency_snapshot(tmp_path):
    stored = dependency(version="1", fingerprint="d" * 64)
    current_dep = dependency(version="2", fingerprint="e" * 64)
    original = metadata(dependencies=[stored])
    artifact_key = install_manifest_entry(tmp_path, original)

    bridge = R2ArtifactBridge(
        port(tmp_path),
        DependencyResolverRegistry(
            [MappingResolver({stored.ref: current_dep})]
        ),
    )
    result = bridge.evaluate_currency(artifact_key.encode())

    persisted = loaded_metadata(tmp_path, artifact_key)
    assert result.status is ArtifactCurrencyStatus.STALE
    assert persisted.direct_dependencies == [stored]
    assert persisted == original


def test_concurrent_r2_metadata_updates_leave_one_valid_manifest(tmp_path):
    artifact_key = install_manifest_entry(tmp_path, metadata())
    m1 = metadata(fingerprint="1" * 64)
    m2 = metadata(fingerprint="2" * 64)
    barrier = Barrier(2)

    def writer(value: R2ArtifactMetadata):
        host = port(tmp_path)
        barrier.wait()
        try:
            return ("ok", host.write_r2_metadata(artifact_key.encode(), value))
        except ArtifactManifestConflictError:
            return ("conflict", None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(writer, (m1, m2)))

    persisted = loaded_metadata(tmp_path, artifact_key)

    assert any(kind == "ok" and changed is True for kind, changed in results)
    assert all(kind in {"ok", "conflict"} for kind, _ in results)
    assert persisted in (m1, m2)

    # A fresh adapter must still parse the complete durable manifest.
    fresh = ProjectArtifactManifestAdapter(tmp_path).get_entry(artifact_key)
    assert fresh is not None
    assert R2ArtifactMetadata.model_validate(fresh.r2) in (m1, m2)


def test_concurrent_promotions_cannot_create_active_version_master_mismatch(tmp_path):
    current, versions, artifact_key, _b_version = setup_master_b(tmp_path)
    c_version = add_unapproved_version(
        tmp_path, versions, current, "C", b"CANDIDATE-C"
    )
    d_version = add_unapproved_version(
        tmp_path, versions, current, "D", b"CANDIDATE-D"
    )
    version_by_candidate = {"C": c_version, "D": d_version}
    payload_by_candidate = {"C": b"CANDIDATE-C", "D": b"CANDIDATE-D"}
    barrier = Barrier(2)

    class BarrierPort(ArcReelArtifactManifestPort):
        def load_artifact(self, artifact_key: str):
            snapshot = super().load_artifact(artifact_key)
            barrier.wait()
            return snapshot

    def promote_one(candidate_id: str):
        host = BarrierPort(
            tmp_path,
            native_currency=native_current,
            version_promoter=ArcReelVersionRestorePromoter(
                versions,
                resource_type="videos",
                resource_id="SH1",
                current_file=current,
            ),
        )
        service = ProductionApprovalService(host)
        try:
            result = service.promote(
                artifact_key=artifact_key.encode(),
                candidate=candidate(candidate_id),
                host_version_ref=str(version_by_candidate[candidate_id]),
                approval_record=f"approval:{candidate_id}",
                selected_by=f"showrunner:{candidate_id}",
                selected_at=datetime(2026, 9, 6, 19, 0, tzinfo=timezone.utc),
            )
            return ("ok", result.changed)
        except ArtifactManifestConflictError:
            return ("conflict", None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(promote_one, ("C", "D")))

    final_version = VersionManager(tmp_path).get_current_version("videos", "SH1")
    final_master = loaded_metadata(tmp_path, artifact_key).approved_master

    assert final_master is not None
    assert final_master.selected_candidate_id in {"C", "D"}
    assert final_version == version_by_candidate[final_master.selected_candidate_id]
    assert final_master.host_version_ref == str(final_version)
    assert current.read_bytes() == payload_by_candidate[final_master.selected_candidate_id]
    assert all(kind in {"ok", "conflict"} for kind, _ in outcomes)


def test_stale_approved_master_remains_selected_until_explicit_replacement(tmp_path):
    current, versions, artifact_key, b_version = setup_master_b(tmp_path)

    stored_dep = dependency(version="1", fingerprint="d" * 64)
    with_dependency = metadata(
        dependencies=[stored_dep],
        master=approved_master("B", str(b_version)),
    )
    assert port(tmp_path).write_r2_metadata(
        artifact_key.encode(),
        with_dependency,
    )

    current_dep = dependency(version="2", fingerprint="e" * 64)
    bridge = R2ArtifactBridge(
        port(tmp_path),
        DependencyResolverRegistry(
            [MappingResolver({stored_dep.ref: current_dep})]
        ),
    )

    result = bridge.evaluate_currency(artifact_key.encode())
    persisted = loaded_metadata(tmp_path, artifact_key)

    assert result.status is ArtifactCurrencyStatus.STALE
    assert persisted.approved_master is not None
    assert persisted.approved_master.selected_candidate_id == "B"
    assert persisted.approved_master.host_version_ref == str(b_version)
    assert VersionManager(tmp_path).get_current_version("videos", "SH1") == b_version
    assert current.read_bytes() == b"MASTER-B"
