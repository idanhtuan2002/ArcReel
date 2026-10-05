"""Exact v1 bodies for the first Take-derived LOCATION binding packet."""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import ConfigDict, Field, StringConstraints, model_validator

from r2.contracts.common import R2ContractModel
from r2.contracts.enums import ProductionBindingTarget
from r2.contracts.production_target import Sha256Digest, TargetVersionRef
from r2.contracts.spatial_source import FrameCandidateId

ExactName = Annotated[str, StringConstraints(min_length=1, pattern=r"^\S(?:.*\S)?$")]
BindingId = Annotated[str, StringConstraints(pattern=r"^m8b:[0-9a-f]{64}$")]
SourceGroupRef = Annotated[str, StringConstraints(pattern=r"^m8g:[0-9a-f]{64}$")]


class _AuthorityBody(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FrameSourceClaimV1(_AuthorityBody):
    receipt_id: FrameCandidateId
    receipt_digest: Sha256Digest
    frame_candidate_id: FrameCandidateId
    frame_content_digest: Sha256Digest
    frame_probe_digest: Sha256Digest
    frame_byte_size: int = Field(gt=0)
    parent_artifact_key: ExactName
    parent_master_version: int = Field(ge=1)
    parent_candidate_id: ExactName
    parent_content_digest: Sha256Digest
    decoded_frame_index: int = Field(ge=0)
    recipe_version: ExactName
    decoder_identity: ExactName

    @model_validator(mode="after")
    def check_frame_identity(self) -> Self:
        if self.receipt_id != self.frame_candidate_id:
            raise ValueError("frame claim receipt ID must equal its frame candidate ID")
        return self


class FrameSourceClaimWithDigestV1(FrameSourceClaimV1):
    claim_digest: Sha256Digest


class BindingEnvelopeV1(_AuthorityBody):
    user_id: ExactName
    project_name: ExactName
    binding_id: BindingId
    binding_version: int = Field(ge=1)
    binding_body_digest: Sha256Digest
    scene_ref: TargetVersionRef
    target_ref: TargetVersionRef
    ordered_claims: tuple[FrameSourceClaimWithDigestV1, FrameSourceClaimWithDigestV1]
    spatial_set_id: None
    spatial_set_digest: None

    @model_validator(mode="after")
    def check_claim_and_target_order(self) -> Self:
        ids = [claim.frame_candidate_id for claim in self.ordered_claims]
        if ids != sorted(set(ids)):
            raise ValueError("binding frame claims must be distinct and sorted")
        if self.scene_ref.target_type != ProductionBindingTarget.SCENE:
            raise ValueError("binding Scene ref has the wrong target type")
        if self.target_ref.target_type != ProductionBindingTarget.SHOT:
            raise ValueError("binding Shot ref has the wrong target type")
        return self


class FrameReceiptRefV1(_AuthorityBody):
    receipt_id: FrameCandidateId
    receipt_digest: Sha256Digest


class BindingCreateCommandV1(_AuthorityBody):
    user_id: ExactName
    project_name: ExactName
    principal: ExactName
    command_id: ExactName
    expected_target_ref: TargetVersionRef
    ordered_frame_receipts: tuple[FrameReceiptRefV1, FrameReceiptRefV1]

    @model_validator(mode="after")
    def check_order(self) -> Self:
        ids = [item.receipt_id for item in self.ordered_frame_receipts]
        if ids != sorted(set(ids)):
            raise ValueError("command frame receipts must be distinct and sorted")
        if self.expected_target_ref.target_type != ProductionBindingTarget.SHOT:
            raise ValueError("create command requires a Shot target ref")
        return self


class BindingCreateResultV1(_AuthorityBody):
    command_digest: Sha256Digest
    binding_id: BindingId
    binding_version: int = Field(ge=1)
    envelope_digest: Sha256Digest
    target_ref: TargetVersionRef

    @model_validator(mode="after")
    def check_target(self) -> Self:
        if self.target_ref.target_type != ProductionBindingTarget.SHOT:
            raise ValueError("create result requires a Shot target ref")
        return self


class SnapshotBindingRefV1(_AuthorityBody):
    binding_id: BindingId
    version: int = Field(ge=1)
    envelope_digest: Sha256Digest


class BindingSnapshotV1(_AuthorityBody):
    user_id: ExactName
    project_name: ExactName
    ordered_bindings: tuple[SnapshotBindingRefV1, ...] = Field(min_length=1)
    target_versions: tuple[TargetVersionRef, TargetVersionRef]

    @model_validator(mode="after")
    def check_order(self) -> Self:
        ids = [binding.binding_id for binding in self.ordered_bindings]
        if ids != sorted(set(ids)):
            raise ValueError("snapshot bindings must be distinct and sorted")
        if [ref.target_type for ref in self.target_versions] != [
            ProductionBindingTarget.SCENE,
            ProductionBindingTarget.SHOT,
        ]:
            raise ValueError("snapshot target refs must be Scene then Shot")
        return self


__all__ = [
    "BindingCreateCommandV1",
    "BindingCreateResultV1",
    "BindingEnvelopeV1",
    "BindingId",
    "BindingSnapshotV1",
    "FrameReceiptRefV1",
    "FrameSourceClaimV1",
    "FrameSourceClaimWithDigestV1",
    "SnapshotBindingRefV1",
    "SourceGroupRef",
]
