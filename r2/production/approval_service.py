from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from r2.contracts import (
    CandidateSelectionStatus,
    GenerationCandidate,
    GenerationLifecycleStatus,
)

from .artifact_bridge import ArtifactManifestPort
from .artifact_metadata import ApprovedMasterMetadata, R2ArtifactMetadata


@dataclass(frozen=True)
class PromotionResult:
    changed: bool
    approved_master: ApprovedMasterMetadata


class ProductionApprovalService:
    def __init__(self, host: ArtifactManifestPort) -> None:
        self._host = host

    def promote(
        self,
        *,
        artifact_key: str,
        candidate: GenerationCandidate,
        host_version_ref: str,
        approval_record: str,
        selected_by: str,
        selected_at: datetime,
    ) -> PromotionResult:
        snapshot = self._host.load_artifact(artifact_key)
        if snapshot is None:
            raise KeyError(artifact_key)
        if snapshot.r2_raw is None:
            raise ValueError("artifact is not R2-aware")

        metadata = R2ArtifactMetadata.model_validate(snapshot.r2_raw)

        if candidate.lifecycle_state is not GenerationLifecycleStatus.GENERATED:
            raise ValueError("candidate must be GENERATED before promotion")
        if candidate.selection_state is CandidateSelectionStatus.REJECTED:
            raise ValueError("REJECTED candidate cannot be promoted")
        if candidate.target_ref != metadata.contract_ref.id:
            raise ValueError("candidate target_ref does not match artifact contract")
        if candidate.content_fingerprint != metadata.content_fingerprint:
            raise ValueError("candidate content_fingerprint does not match current semantic state")
        if not host_version_ref:
            raise ValueError("host_version_ref must be non-empty")

        existing = metadata.approved_master
        if (
            existing is not None
            and existing.selected_candidate_id == candidate.id
            and existing.host_version_ref == host_version_ref
        ):
            return PromotionResult(changed=False, approved_master=existing)

        approved = ApprovedMasterMetadata(
            selected_candidate_id=candidate.id,
            host_version_ref=host_version_ref,
            approval_record=approval_record,
            selected_at=selected_at,
            selected_by=selected_by,
        )
        updated = metadata.model_copy(update={"approved_master": approved})

        changed = self._host.promote_version_with_r2_metadata(
            artifact_key,
            host_version_ref=host_version_ref,
            metadata=updated,
        )
        return PromotionResult(changed=changed, approved_master=approved)
