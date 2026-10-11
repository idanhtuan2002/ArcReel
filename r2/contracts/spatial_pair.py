"""Typed, authority-neutral bodies for a reviewed spatial frame pair."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, ConfigDict, Field, StringConstraints, model_validator

from r2.contracts.common import R2ContractModel
from r2.contracts.enums import ProductionBindingTarget
from r2.contracts.production_binding_authority import BindingId, ExactName
from r2.contracts.production_target import Sha256Digest, TargetVersionRef
from r2.contracts.review_evidence import ReviewEvidenceV1, ReviewSessionId
from r2.contracts.spatial_source import FrameCandidateId

PairId = Annotated[str, StringConstraints(pattern=r"^m8p:[0-9a-f]{64}$")]
ReviewText = Annotated[str, StringConstraints(min_length=1, max_length=2000)]


class _PairBody(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PairViewV1(_PairBody):
    role: Literal["MASTER", "REVERSE"]
    receipt_id: FrameCandidateId
    receipt_digest: Sha256Digest


class PairReviewObservationsV1(_PairBody):
    view_coverage: ReviewText | None
    camera_center: ReviewText | None
    yaw_relation: ReviewText | None
    rejection_reason: ReviewText | None

    @model_validator(mode="after")
    def require_content(self) -> Self:
        for value in (self.view_coverage, self.camera_center, self.yaw_relation, self.rejection_reason):
            if value is not None and (not value.strip() or value != value.strip()):
                raise ValueError("pair review observations must be nonblank and unpadded")
        return self


class PairDecisionCommandV1(_PairBody):
    user_id: ExactName
    project_name: ExactName
    principal: ExactName
    command_id: ExactName
    expected_scene_ref: TargetVersionRef
    expected_target_ref: TargetVersionRef
    binding_id: BindingId
    expected_binding_version: int = Field(ge=1)
    expected_envelope_digest: Sha256Digest
    expected_core_digest: Sha256Digest
    views: tuple[PairViewV1, PairViewV1]
    decision: Literal["APPROVE", "REJECT"]
    observations: PairReviewObservationsV1

    @model_validator(mode="after")
    def require_exact_pair(self) -> Self:
        if self.expected_scene_ref.target_type != ProductionBindingTarget.SCENE:
            raise ValueError("pair decision requires a Scene dependency")
        if self.expected_target_ref.target_type != ProductionBindingTarget.SHOT:
            raise ValueError("pair decision requires a Shot target")
        if [view.role for view in self.views] != ["MASTER", "REVERSE"]:
            raise ValueError("pair views must be ordered MASTER then REVERSE")
        if self.views[0].receipt_id == self.views[1].receipt_id:
            raise ValueError("pair views must use distinct frame receipts")
        if self.decision == "APPROVE":
            if (
                self.observations.view_coverage is None
                or self.observations.camera_center is None
                or self.observations.yaw_relation is None
                or self.observations.rejection_reason is not None
            ):
                raise ValueError("pair approval requires three observations and no rejection reason")
        elif self.observations.rejection_reason is None:
            raise ValueError("pair rejection requires a reason")
        return self


class PairDecisionCommandV2(PairDecisionCommandV1):
    review_session_id: ReviewSessionId
    review_evidence_digest: Sha256Digest


class PairAuthorizationV1(_PairBody):
    user_id: ExactName
    project_name: ExactName
    authenticated_principal: ExactName
    authority_role: Literal["HUMAN_SHOWRUNNER"]
    command_digest: Sha256Digest
    authorization_ref: ExactName
    authenticated_at: AwareDatetime


class PairDecisionV1(_PairBody):
    command: PairDecisionCommandV1
    command_digest: Sha256Digest
    pair_id: PairId
    pair_version: int = Field(ge=1)
    reviewer_id: ExactName
    authorization: PairAuthorizationV1
    authorization_digest: Sha256Digest
    decided_at: AwareDatetime

    @model_validator(mode="after")
    def require_authorization_match(self) -> Self:
        if (
            self.authorization.user_id != self.command.user_id
            or self.authorization.project_name != self.command.project_name
            or self.authorization.authenticated_principal != self.command.principal
            or self.authorization.command_digest != self.command_digest
            or self.reviewer_id != self.command.principal
            or self.decided_at < self.authorization.authenticated_at
        ):
            raise ValueError("pair decision authorization does not bind the exact command and reviewer")
        return self


class PairDecisionV2(_PairBody):
    decision_schema: Literal["r2.m8.spatial.pair.decision.v2"]
    command: PairDecisionCommandV2
    command_digest: Sha256Digest
    pair_id: PairId
    pair_version: int = Field(ge=1)
    reviewer_id: ExactName
    authorization: PairAuthorizationV1
    authorization_digest: Sha256Digest
    review_evidence: ReviewEvidenceV1
    decided_at: AwareDatetime

    @model_validator(mode="after")
    def require_exact_review_authority(self) -> Self:
        from r2.spatial_pair.digests import (
            pair_authorization_digest,
            pair_command_digest_v2,
            scoped_pair_id,
        )
        from r2.spatial_pair.review_digests import review_evidence_digest

        command = self.command
        snapshot = self.review_evidence.snapshot
        if (
            self.command_digest != pair_command_digest_v2(command.model_dump(mode="json"))
            or self.authorization_digest != pair_authorization_digest(self.authorization.model_dump(mode="json"))
            or command.review_evidence_digest != review_evidence_digest(self.review_evidence.model_dump(mode="json"))
            or self.pair_id
            != scoped_pair_id(user_id=command.user_id, project_name=command.project_name, binding_id=command.binding_id)
            or self.reviewer_id != command.principal
            or (self.authorization.user_id, self.authorization.project_name, self.authorization.authenticated_principal)
            != (command.user_id, command.project_name, command.principal)
            or self.authorization.authority_role != "HUMAN_SHOWRUNNER"
            or self.authorization.command_digest != self.command_digest
            or self.decided_at < self.authorization.authenticated_at
            or self.decided_at < max(ack.acknowledged_at for ack in self.review_evidence.acknowledgments)
            or (snapshot.user_id, snapshot.project_name, snapshot.principal, snapshot.session_id)
            != (command.user_id, command.project_name, command.principal, command.review_session_id)
            or (snapshot.scene_ref, snapshot.target_ref, snapshot.binding_id, snapshot.binding_version)
            != (
                command.expected_scene_ref,
                command.expected_target_ref,
                command.binding_id,
                command.expected_binding_version,
            )
            or (snapshot.envelope_digest, snapshot.core_digest)
            != (command.expected_envelope_digest, command.expected_core_digest)
            or [(frame.role, frame.receipt_id, frame.receipt_digest) for frame in snapshot.frames]
            != [(view.role, view.receipt_id, view.receipt_digest) for view in command.views]
        ):
            raise ValueError("pair V2 decision differs from its exact authority or frame review")
        return self


class PairDecisionResultV1(_PairBody):
    command_digest: Sha256Digest
    pair_id: PairId
    pair_version: int = Field(ge=1)
    decision_digest: Sha256Digest
    decision: Literal["APPROVE", "REJECT"]
    binding_id: BindingId
    binding_version: int = Field(ge=1)
    binding_envelope_digest: Sha256Digest
    binding_core_digest: Sha256Digest
    scene_ref: TargetVersionRef
    target_ref: TargetVersionRef

    @model_validator(mode="after")
    def require_target_types(self) -> Self:
        if self.scene_ref.target_type != ProductionBindingTarget.SCENE:
            raise ValueError("pair result requires a Scene dependency")
        if self.target_ref.target_type != ProductionBindingTarget.SHOT:
            raise ValueError("pair result requires a Shot target")
        return self


class PairDecisionResultV2(PairDecisionResultV1):
    result_schema: Literal["r2.m8.spatial.pair.result.v2"]
    review_session_id: ReviewSessionId
    review_evidence_digest: Sha256Digest


__all__ = [
    "PairAuthorizationV1",
    "PairDecisionCommandV1",
    "PairDecisionCommandV2",
    "PairDecisionResultV1",
    "PairDecisionResultV2",
    "PairDecisionV1",
    "PairDecisionV2",
    "PairId",
    "PairReviewObservationsV1",
    "PairViewV1",
]
