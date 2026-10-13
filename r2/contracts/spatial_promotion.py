"""Typed spatial promotion wire: a V2 preview and receipt that couple the base M8 rows to their sidecars.

The artifact-slot preview and receipt keep their bytes and digests. A ``PRODUCTION_BINDING``
target always carries exactly one sidecar, and the V2 digests cover the base row and the sidecar.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import ConfigDict, Field, model_validator

from r2.contracts.advanced_creative import PromotionPreview, PromotionReceipt, PromotionTargetKind
from r2.contracts.common import R2ContractModel
from r2.contracts.enums import ProductionBindingTarget
from r2.contracts.production_binding_authority import BindingId, ExactName, SpatialConstraintSetId
from r2.contracts.production_target import Sha256Digest, TargetVersionRef
from r2.contracts.spatial_constraint import SpatialConstraintSetV1
from r2.contracts.spatial_pair import PairId


class _Body(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SpatialPreviewBindingV2(_Body):
    """Sidecar of one binding-target preview: the server-derived proposal and its bound identities."""

    schema_version: Literal["2"]
    binding_id: BindingId
    expected_binding_version: int = Field(ge=1)
    binding_envelope_digest: Sha256Digest
    target_ref: TargetVersionRef
    selected_assertion_ids: tuple[ExactName, ...] = Field(min_length=1)
    proposal: SpatialConstraintSetV1
    proposal_digest: Sha256Digest
    pair_id: PairId
    pair_version: int = Field(ge=1)
    pair_decision_digest: Sha256Digest

    @model_validator(mode="after")
    def check_proposal_identity(self) -> Self:
        if self.target_ref.target_type != ProductionBindingTarget.SHOT:
            raise ValueError("a spatial preview binds a Shot target")
        if self.proposal.binding_id != self.binding_id:
            raise ValueError("the proposal names another binding")
        if [c.assertion_id for c in self.proposal.constraints] != list(self.selected_assertion_ids):
            raise ValueError("the proposal constraints differ from the selected assertions")
        if (self.proposal.pair_id, self.proposal.pair_version, self.proposal.pair_decision_digest) != (
            self.pair_id,
            self.pair_version,
            self.pair_decision_digest,
        ):
            raise ValueError("the proposal names another pair approval")
        return self


class SpatialPromotionPreviewV2(_Body):
    schema_version: Literal["2"]
    base_preview: PromotionPreview
    binding: SpatialPreviewBindingV2

    @model_validator(mode="after")
    def check_coupling(self) -> Self:
        base = self.base_preview
        if (
            base.target.kind is not PromotionTargetKind.PRODUCTION_BINDING
            or base.target.target_ref != self.binding.binding_id
            or base.target.expected_target_version != self.binding.expected_binding_version
            or base.expected_master_id is not None
            or (base.candidate_id, base.candidate_revision, base.candidate_payload_digest)
            != (
                self.binding.proposal.candidate_id,
                self.binding.proposal.candidate_revision,
                self.binding.proposal.candidate_payload_digest,
            )
            or base.project_name != self.binding.proposal.project_name
        ):
            raise ValueError("the base preview and its spatial sidecar differ")
        return self


class SpatialPromotionResultV2(_Body):
    """Sidecar of one binding-target receipt: the binding version and constraint set it produced."""

    schema_version: Literal["2"]
    binding_id: BindingId
    binding_version: int = Field(ge=2)
    binding_envelope_digest: Sha256Digest
    constraint_set_id: SpatialConstraintSetId
    constraint_set_digest: Sha256Digest

    @model_validator(mode="after")
    def check_set_identity(self) -> Self:
        if self.constraint_set_id.removeprefix("m8s:") != self.constraint_set_digest.removeprefix("sha256:"):
            raise ValueError("the result constraint set ID must name its digest")
        return self


class SpatialPromotionReceiptV2(_Body):
    schema_version: Literal["2"]
    base_receipt: PromotionReceipt
    result: SpatialPromotionResultV2

    @model_validator(mode="after")
    def check_coupling(self) -> Self:
        base = self.base_receipt
        if (
            base.target.kind is not PromotionTargetKind.PRODUCTION_BINDING
            or base.target.target_ref != self.result.binding_id
            or base.result_master_id is not None
            or base.result_artifact_ref != binding_version_ref(self.result.binding_id, self.result.binding_version)
            or base.result_digest != self.result.binding_envelope_digest
        ):
            raise ValueError("the base receipt and its spatial result differ")
        return self


def binding_version_ref(binding_id: str, version: int) -> str:
    return f"{binding_id}@{version}"


__all__ = [
    "SpatialPreviewBindingV2",
    "SpatialPromotionPreviewV2",
    "SpatialPromotionReceiptV2",
    "SpatialPromotionResultV2",
    "binding_version_ref",
]
