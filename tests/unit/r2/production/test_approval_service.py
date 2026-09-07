from datetime import UTC, datetime

import pytest

from r2.contracts import (
    ArtifactCurrencyStatus,
    CandidateSelectionStatus,
    ContentBasis,
    ContentBasisType,
    GenerationCandidate,
    GenerationLifecycleStatus,
)
from r2.production import (
    ArtifactHostSnapshot,
    ProductionApprovalService,
    R2ArtifactMetadata,
    R2ContractRef,
)


def metadata(**updates) -> R2ArtifactMetadata:
    value = R2ArtifactMetadata(
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
    return value.model_copy(update=updates)


def candidate(**updates) -> GenerationCandidate:
    data = {
        "id": "C1",
        "target_ref": "SH1",
        "content_fingerprint": "c" * 64,
        "execution_fingerprint": "e" * 64,
        "provider_execution_ref": "job:1",
        "output_asset_ref": "asset:C1",
        "lifecycle_state": GenerationLifecycleStatus.GENERATED,
        "selection_state": CandidateSelectionStatus.UNREVIEWED,
    }
    data.update(updates)
    return GenerationCandidate(**data)


class Host:
    def __init__(self, value: R2ArtifactMetadata) -> None:
        self.value = value
        self.promotions = []

    def load_artifact(self, artifact_key):
        return ArtifactHostSnapshot(
            artifact_key=artifact_key,
            usable=True,
            native_currency=ArtifactCurrencyStatus.CURRENT,
            r2_raw=self.value.model_dump(mode="json"),
        )

    def write_r2_metadata(self, artifact_key, metadata):
        self.value = metadata
        return True

    def promote_version_with_r2_metadata(
        self,
        artifact_key,
        *,
        host_version_ref,
        metadata,
    ):
        self.promotions.append((artifact_key, host_version_ref, metadata))
        self.value = metadata
        return True


def service(host):
    return ProductionApprovalService(host)


def selected_at():
    return datetime(2026, 9, 6, 19, 0, tzinfo=UTC)


def test_generated_unreviewed_candidate_can_be_explicitly_promoted():
    host = Host(metadata())

    result = service(host).promote(
        artifact_key="video:SH1",
        candidate=candidate(),
        host_version_ref="2",
        approval_record="approval:1",
        selected_by="showrunner:1",
        selected_at=selected_at(),
    )

    assert result.changed is True
    assert result.approved_master.selected_candidate_id == "C1"
    assert result.approved_master.host_version_ref == "2"
    assert host.value.approved_master == result.approved_master


def test_failed_candidate_cannot_promote():
    host = Host(metadata())
    failed = candidate(lifecycle_state=GenerationLifecycleStatus.FAILED)

    with pytest.raises(ValueError, match="GENERATED"):
        service(host).promote(
            artifact_key="video:SH1",
            candidate=failed,
            host_version_ref="2",
            approval_record="approval:1",
            selected_by="showrunner:1",
            selected_at=selected_at(),
        )

    assert host.promotions == []


def test_rejected_candidate_cannot_promote():
    host = Host(metadata())
    rejected = candidate(selection_state=CandidateSelectionStatus.REJECTED)

    with pytest.raises(ValueError, match="REJECTED"):
        service(host).promote(
            artifact_key="video:SH1",
            candidate=rejected,
            host_version_ref="2",
            approval_record="approval:1",
            selected_by="showrunner:1",
            selected_at=selected_at(),
        )

    assert host.promotions == []


def test_candidate_target_must_match_artifact_contract():
    host = Host(metadata())

    with pytest.raises(ValueError, match="target_ref"):
        service(host).promote(
            artifact_key="video:SH1",
            candidate=candidate(target_ref="SH2"),
            host_version_ref="2",
            approval_record="approval:1",
            selected_by="showrunner:1",
            selected_at=selected_at(),
        )


def test_candidate_content_fingerprint_must_match_current_semantic_state():
    host = Host(metadata())

    with pytest.raises(ValueError, match="content_fingerprint"):
        service(host).promote(
            artifact_key="video:SH1",
            candidate=candidate(content_fingerprint="x" * 64),
            host_version_ref="2",
            approval_record="approval:1",
            selected_by="showrunner:1",
            selected_at=selected_at(),
        )


def test_same_candidate_and_host_version_is_idempotent():
    host = Host(metadata())
    svc = service(host)
    first = svc.promote(
        artifact_key="video:SH1",
        candidate=candidate(),
        host_version_ref="2",
        approval_record="approval:1",
        selected_by="showrunner:1",
        selected_at=selected_at(),
    )
    calls_after_first = len(host.promotions)

    second = svc.promote(
        artifact_key="video:SH1",
        candidate=candidate(),
        host_version_ref="2",
        approval_record="approval:2",
        selected_by="showrunner:2",
        selected_at=datetime(2026, 9, 6, 20, 0, tzinfo=UTC),
    )

    assert first.changed is True
    assert second.changed is False
    assert second.approved_master == first.approved_master
    assert len(host.promotions) == calls_after_first
