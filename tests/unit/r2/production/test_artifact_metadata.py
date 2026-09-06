from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from r2.contracts import ContentBasis, ContentBasisType
from r2.production import (
    ApprovedMasterMetadata,
    DependencySnapshot,
    R2ArtifactMetadata,
    R2ContractRef,
)


def basis() -> ContentBasis:
    return ContentBasis(
        basis_type=ContentBasisType.NARRATIVE,
        basis_version="canon-v7",
        refs=["event:1"],
    )


def test_r2_artifact_metadata_round_trips():
    metadata = R2ArtifactMetadata(
        metadata_schema_version="1",
        contract_ref=R2ContractRef(
            contract_type="ShotSpec",
            id="SH042",
            version=4,
            schema_version="2.1",
        ),
        content_basis=basis(),
        direct_dependencies=[
            DependencySnapshot(
                ref="r2:ProductionBinding:B02",
                version="5",
                fingerprint="b" * 64,
            ),
            DependencySnapshot(
                ref="r2:ProductionBinding:B01",
                version="2",
                fingerprint="a" * 64,
            ),
        ],
        content_fingerprint="c" * 64,
    )

    restored = R2ArtifactMetadata.model_validate(metadata.model_dump(mode="json"))

    assert restored == metadata


def test_r2_artifact_metadata_sorts_direct_dependencies():
    metadata = R2ArtifactMetadata(
        metadata_schema_version="1",
        contract_ref=R2ContractRef(
            contract_type="ShotSpec",
            id="SH042",
            version=4,
            schema_version="2.1",
        ),
        content_basis=basis(),
        direct_dependencies=[
            DependencySnapshot(
                ref="r2:ProductionBinding:B02",
                version="5",
                fingerprint="b" * 64,
            ),
            DependencySnapshot(
                ref="r2:ProductionBinding:B01",
                version="2",
                fingerprint="a" * 64,
            ),
        ],
        content_fingerprint="c" * 64,
    )

    assert [d.ref for d in metadata.direct_dependencies] == [
        "r2:ProductionBinding:B01",
        "r2:ProductionBinding:B02",
    ]


def test_r2_artifact_metadata_rejects_conflicting_duplicate_dependency_refs():
    with pytest.raises(ValidationError):
        R2ArtifactMetadata(
            metadata_schema_version="1",
            contract_ref=R2ContractRef(
                contract_type="ShotSpec",
                id="SH042",
                version=4,
                schema_version="2.1",
            ),
            content_basis=basis(),
            direct_dependencies=[
                DependencySnapshot(
                    ref="r2:ProductionBinding:B01",
                    version="2",
                    fingerprint="a" * 64,
                ),
                DependencySnapshot(
                    ref="r2:ProductionBinding:B01",
                    version="3",
                    fingerprint="b" * 64,
                ),
            ],
            content_fingerprint="c" * 64,
        )


def test_r2_artifact_metadata_requires_content_basis():
    with pytest.raises(ValidationError):
        R2ArtifactMetadata(
            metadata_schema_version="1",
            contract_ref=R2ContractRef(
                contract_type="ShotSpec",
                id="SH042",
                version=4,
                schema_version="2.1",
            ),
            direct_dependencies=[],
            content_fingerprint="c" * 64,
        )


def test_approved_master_rejects_naive_selected_at():
    with pytest.raises(ValidationError):
        ApprovedMasterMetadata(
            selected_candidate_id="C1",
            host_version_ref="V17",
            approval_record="APR1",
            selected_at=datetime(2026, 9, 6, 18, 0),
            selected_by="showrunner:1",
        )


def test_approved_master_accepts_timezone_aware_selected_at():
    master = ApprovedMasterMetadata(
        selected_candidate_id="C1",
        host_version_ref="V17",
        approval_record="APR1",
        selected_at=datetime(2026, 9, 6, 18, 0, tzinfo=timezone.utc),
        selected_by="showrunner:1",
    )

    assert master.host_version_ref == "V17"
