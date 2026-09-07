"""M4 — ApprovedMaster survives a failed later candidate; promotion is explicit."""

from __future__ import annotations

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

_CONTENT_FP = "c" * 64
_AT = datetime(2026, 9, 7, 19, 0, tzinfo=UTC)


def _metadata() -> R2ArtifactMetadata:
    return R2ArtifactMetadata(
        metadata_schema_version="1",
        contract_ref=R2ContractRef(contract_type="ShotSpec", id="SH1", version=1, schema_version="1"),
        content_basis=ContentBasis(basis_type=ContentBasisType.NARRATIVE, basis_version="canon-v1", refs=["event:1"]),
        direct_dependencies=[],
        content_fingerprint=_CONTENT_FP,
    )


def _candidate(cid: str, **over) -> GenerationCandidate:
    data = {
        "id": cid,
        "target_ref": "SH1",
        "content_fingerprint": _CONTENT_FP,
        "execution_fingerprint": f"e-{cid}" + "0" * 60,
        "provider_execution_ref": f"job:{cid}",
        "output_asset_ref": f"asset:{cid}",
        "lifecycle_state": GenerationLifecycleStatus.GENERATED,
        "selection_state": CandidateSelectionStatus.UNREVIEWED,
    }
    data.update(over)
    return GenerationCandidate(**data)


class _Host:
    def __init__(self, value: R2ArtifactMetadata) -> None:
        self.value = value

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

    def promote_version_with_r2_metadata(self, artifact_key, *, host_version_ref, metadata):
        self.value = metadata
        return True


def _promote(host: _Host, candidate: GenerationCandidate, version: str):
    return ProductionApprovalService(host).promote(
        artifact_key="video:SH1",
        candidate=candidate,
        host_version_ref=version,
        approval_record=f"approval:{version}",
        selected_by="showrunner:1",
        selected_at=_AT,
    )


def test_failed_or_unapproved_later_candidate_never_replaces_the_master() -> None:
    host = _Host(_metadata())

    # B becomes the ApprovedMaster.
    result_b = _promote(host, _candidate("B"), "2")
    assert result_b.approved_master.selected_candidate_id == "B"

    # C fails -> promotion refused -> B stays master.
    with pytest.raises(ValueError, match="GENERATED"):
        _promote(host, _candidate("C", lifecycle_state=GenerationLifecycleStatus.FAILED), "3")
    assert host.value.approved_master.selected_candidate_id == "B"

    # D succeeds but is left unapproved -> B stays master.
    _candidate("D")
    assert host.value.approved_master.selected_candidate_id == "B"

    # Explicit promotion of D -> D becomes master.
    result_d = _promote(host, _candidate("D"), "4")
    assert result_d.approved_master.selected_candidate_id == "D"

    # "Restart": a fresh service over the persisted metadata still sees D.
    reopened = ProductionApprovalService(_Host(host.value))
    snapshot = reopened._host.load_artifact("video:SH1")
    reloaded = R2ArtifactMetadata.model_validate(snapshot.r2_raw)
    assert reloaded.approved_master is not None
    assert reloaded.approved_master.selected_candidate_id == "D"
