"""Immutable bodies for exact spatial frame review custody."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, ConfigDict, Field, StringConstraints, model_validator

from r2.contracts.common import R2ContractModel
from r2.contracts.enums import ProductionBindingTarget
from r2.contracts.production_binding_authority import BindingId, ExactName
from r2.contracts.production_target import Sha256Digest, TargetVersionRef
from r2.contracts.spatial_source import FrameCandidateId

ReviewSessionId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
ReviewRole = Literal["MASTER", "REVERSE"]


class _ReviewBody(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ReviewFrameV1(_ReviewBody):
    role: ReviewRole
    receipt_id: FrameCandidateId
    receipt_digest: Sha256Digest
    png_digest: Sha256Digest


class ReviewSnapshotV1(_ReviewBody):
    session_id: ReviewSessionId
    user_id: ExactName
    project_name: ExactName
    principal: ExactName
    scene_ref: TargetVersionRef
    target_ref: TargetVersionRef
    binding_id: BindingId
    binding_version: int = Field(ge=1)
    envelope_digest: Sha256Digest
    core_digest: Sha256Digest
    frames: tuple[ReviewFrameV1, ReviewFrameV1]
    created_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def check_scope_and_order(self) -> Self:
        if self.scene_ref.target_type != ProductionBindingTarget.SCENE:
            raise ValueError("review snapshot requires a Scene ref")
        if self.target_ref.target_type != ProductionBindingTarget.SHOT:
            raise ValueError("review snapshot requires a Shot ref")
        if [frame.role for frame in self.frames] != ["MASTER", "REVERSE"]:
            raise ValueError("review frames must be ordered MASTER then REVERSE")
        if self.frames[0].receipt_id == self.frames[1].receipt_id:
            raise ValueError("review frames require distinct receipts")
        if (
            self.created_at.utcoffset() != timedelta(0)
            or self.expires_at.utcoffset() != timedelta(0)
            or not self.created_at < self.expires_at <= self.created_at + timedelta(minutes=10)
        ):
            raise ValueError("review session requires a UTC interval of at most ten minutes")
        return self


class ReviewDeliveryV1(_ReviewBody):
    attempt_id: ExactName
    role: ReviewRole
    png_digest: Sha256Digest
    delivered_at: AwareDatetime


class ReviewAcknowledgmentV1(_ReviewBody):
    principal: ExactName
    role: ReviewRole
    png_digest: Sha256Digest
    decoded: Literal[True]
    delivery_attempt_id: ExactName
    acknowledged_at: AwareDatetime


class ReviewEvidenceV1(_ReviewBody):
    snapshot: ReviewSnapshotV1
    snapshot_digest: Sha256Digest
    deliveries: tuple[ReviewDeliveryV1, ...] = Field(min_length=2)
    acknowledgments: tuple[ReviewAcknowledgmentV1, ReviewAcknowledgmentV1]

    @model_validator(mode="after")
    def check_delivery_and_acknowledgment(self) -> Self:
        from r2.spatial_pair.review_digests import review_snapshot_digest

        if self.snapshot_digest != review_snapshot_digest(self.snapshot.model_dump(mode="json")):
            raise ValueError("review snapshot digest differs from stored snapshot")
        attempts: dict[str, ReviewDeliveryV1] = {}
        for delivery in self.deliveries:
            if delivery.attempt_id in attempts:
                raise ValueError("review delivery attempt IDs must be unique")
            frame = self.snapshot.frames[0 if delivery.role == "MASTER" else 1]
            if (
                delivery.png_digest != frame.png_digest
                or not self.snapshot.created_at <= delivery.delivered_at <= self.snapshot.expires_at
                or delivery.delivered_at.utcoffset() != timedelta(0)
            ):
                raise ValueError("review delivery differs from session frame or interval")
            attempts[delivery.attempt_id] = delivery
        if [ack.role for ack in self.acknowledgments] != ["MASTER", "REVERSE"]:
            raise ValueError("review acknowledgments must be ordered MASTER then REVERSE")
        for frame, ack in zip(self.snapshot.frames, self.acknowledgments, strict=True):
            delivery = attempts.get(ack.delivery_attempt_id)
            if (
                delivery is None
                or ack.principal != self.snapshot.principal
                or delivery.role != frame.role
                or delivery.png_digest != frame.png_digest
                or ack.png_digest != frame.png_digest
                or ack.acknowledged_at.utcoffset() != timedelta(0)
                or not delivery.delivered_at <= ack.acknowledged_at <= self.snapshot.expires_at
            ):
                raise ValueError("review acknowledgment has no matching delivered frame")
        return self


__all__ = [
    "ReviewAcknowledgmentV1",
    "ReviewDeliveryV1",
    "ReviewEvidenceV1",
    "ReviewFrameV1",
    "ReviewSessionId",
    "ReviewSnapshotV1",
]
