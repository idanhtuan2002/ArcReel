from datetime import UTC, datetime

import pytest

from lib.artifact_manifest import ArtifactKey, ArtifactManifestEntry, ProjectArtifactManifestAdapter
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
    ProductionApprovalService,
    R2ArtifactMetadata,
    R2ContractRef,
)


def base_metadata(candidate_id: str, version_ref: str) -> R2ArtifactMetadata:
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
        approved_master=ApprovedMasterMetadata(
            selected_candidate_id=candidate_id,
            host_version_ref=version_ref,
            approval_record=f"approval:{candidate_id}",
            selected_at=datetime(2026, 9, 6, 18, 0, tzinfo=UTC),
            selected_by="showrunner:1",
        ),
    )


def candidate(candidate_id: str, *, lifecycle=GenerationLifecycleStatus.GENERATED):
    return GenerationCandidate(
        id=candidate_id,
        target_ref="SH1",
        content_fingerprint="c" * 64,
        execution_fingerprint="e" * 64,
        provider_execution_ref=f"job:{candidate_id}",
        output_asset_ref=f"asset:{candidate_id}",
        lifecycle_state=lifecycle,
        selection_state=CandidateSelectionStatus.UNREVIEWED,
    )


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

    key = ArtifactKey.episode_video(1, "SH1")
    adapter = ProjectArtifactManifestAdapter(tmp_path)
    assert adapter.put_entry(
        key,
        ArtifactManifestEntry(
            artifact_path="current.mp4",
            basis_digest="sha256-v1:" + ("a" * 64),
            r2=base_metadata("B", str(b.version)).model_dump(mode="json"),
        ),
    )
    return current, versions, key, b.version


def add_unapproved_c(tmp_path, versions, current):
    staged_c = tmp_path / "C.staged.mp4"
    staged_c.write_bytes(b"CANDIDATE-C")
    c = versions.commit_staged_paid_version(
        "videos",
        "SH1",
        "C",
        staged_file=staged_c,
        current_file=current,
        select_current=False,
    )
    assert c.selected is False
    return c.version


def make_port(tmp_path, versions, current):
    return ArcReelArtifactManifestPort(
        tmp_path,
        native_currency=lambda _key: ArtifactCurrencyStatus.CURRENT,
        version_promoter=ArcReelVersionRestorePromoter(
            versions,
            resource_type="videos",
            resource_id="SH1",
            current_file=current,
        ),
    )


def manifest_master(tmp_path, key):
    entry = ProjectArtifactManifestAdapter(tmp_path).get_entry(key)
    assert entry is not None
    assert isinstance(entry.r2, dict)
    return entry.r2["approved_master"]


def test_successful_unapproved_candidate_preserves_master_b(tmp_path):
    current, versions, key, b_version = setup_master_b(tmp_path)
    c_version = add_unapproved_c(tmp_path, versions, current)

    assert c_version != b_version
    assert versions.get_current_version("videos", "SH1") == b_version
    assert current.read_bytes() == b"MASTER-B"
    assert manifest_master(tmp_path, key)["selected_candidate_id"] == "B"


def test_failed_candidate_preserves_master_b(tmp_path):
    current, versions, key, b_version = setup_master_b(tmp_path)
    svc = ProductionApprovalService(make_port(tmp_path, versions, current))

    with pytest.raises(ValueError, match="GENERATED"):
        svc.promote(
            artifact_key=key.encode(),
            candidate=candidate("C", lifecycle=GenerationLifecycleStatus.FAILED),
            host_version_ref="999",
            approval_record="approval:C",
            selected_by="showrunner:1",
            selected_at=datetime(2026, 9, 6, 19, 0, tzinfo=UTC),
        )

    assert versions.get_current_version("videos", "SH1") == b_version
    assert current.read_bytes() == b"MASTER-B"
    assert manifest_master(tmp_path, key)["selected_candidate_id"] == "B"


def test_explicit_promotion_changes_version_and_approved_master_together(tmp_path):
    current, versions, key, b_version = setup_master_b(tmp_path)
    c_version = add_unapproved_c(tmp_path, versions, current)
    svc = ProductionApprovalService(make_port(tmp_path, versions, current))

    result = svc.promote(
        artifact_key=key.encode(),
        candidate=candidate("C"),
        host_version_ref=str(c_version),
        approval_record="approval:C",
        selected_by="showrunner:1",
        selected_at=datetime(2026, 9, 6, 19, 0, tzinfo=UTC),
    )

    assert b_version != c_version
    assert result.changed is True
    assert versions.get_current_version("videos", "SH1") == c_version
    assert current.read_bytes() == b"CANDIDATE-C"
    assert manifest_master(tmp_path, key)["selected_candidate_id"] == "C"
    assert manifest_master(tmp_path, key)["host_version_ref"] == str(c_version)


def test_manifest_commit_failure_rolls_back_host_version_selection(tmp_path):
    current, versions, key, b_version = setup_master_b(tmp_path)
    c_version = add_unapproved_c(tmp_path, versions, current)

    class FailingPort(ArcReelArtifactManifestPort):
        def promote_version_with_r2_metadata(
            self,
            artifact_key,
            *,
            host_version_ref,
            metadata,
        ):
            if self._version_promoter is None:
                raise RuntimeError("version promotion is not configured")

            def fail_manifest_commit():
                raise RuntimeError("injected manifest commit failure")

            self._version_promoter(host_version_ref, fail_manifest_commit)
            raise AssertionError("unreachable")

    port = FailingPort(
        tmp_path,
        native_currency=lambda _key: ArtifactCurrencyStatus.CURRENT,
        version_promoter=ArcReelVersionRestorePromoter(
            versions,
            resource_type="videos",
            resource_id="SH1",
            current_file=current,
        ),
    )
    svc = ProductionApprovalService(port)

    with pytest.raises(RuntimeError, match="injected manifest commit failure"):
        svc.promote(
            artifact_key=key.encode(),
            candidate=candidate("C"),
            host_version_ref=str(c_version),
            approval_record="approval:C",
            selected_by="showrunner:1",
            selected_at=datetime(2026, 9, 6, 19, 0, tzinfo=UTC),
        )

    assert versions.get_current_version("videos", "SH1") == b_version
    assert current.read_bytes() == b"MASTER-B"
    assert manifest_master(tmp_path, key)["selected_candidate_id"] == "B"


def test_second_promotion_of_same_candidate_is_idempotent(tmp_path):
    current, versions, key, _b_version = setup_master_b(tmp_path)
    c_version = add_unapproved_c(tmp_path, versions, current)
    svc = ProductionApprovalService(make_port(tmp_path, versions, current))

    first = svc.promote(
        artifact_key=key.encode(),
        candidate=candidate("C"),
        host_version_ref=str(c_version),
        approval_record="approval:C",
        selected_by="showrunner:1",
        selected_at=datetime(2026, 9, 6, 19, 0, tzinfo=UTC),
    )
    second = svc.promote(
        artifact_key=key.encode(),
        candidate=candidate("C"),
        host_version_ref=str(c_version),
        approval_record="approval:C2",
        selected_by="showrunner:2",
        selected_at=datetime(2026, 9, 6, 20, 0, tzinfo=UTC),
    )

    assert first.changed is True
    assert second.changed is False
    assert versions.get_current_version("videos", "SH1") == c_version
    assert manifest_master(tmp_path, key)["approval_record"] == "approval:C"
