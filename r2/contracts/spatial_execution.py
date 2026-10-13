"""Immutable evidence that one bounded M7 execution produced one spatial revision."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from r2.advanced_creative.digests import digest_canonical
from r2.contracts.advanced_creative import M8ContractModel, Sha256Digest
from r2.contracts.spatial_source import FrameCandidateId

SPATIAL_EXECUTION_EVIDENCE_DOMAIN = "r2.m8.spatial.execution.evidence.v1"

NonBlank = Annotated[str, StringConstraints(min_length=1, pattern=r".*\S.*")]


class SpatialResponseObjectV1(M8ContractModel):
    object_id: NonBlank
    byte_digest: Sha256Digest
    schema_version: NonBlank


class SpatialSourceFrameV1(M8ContractModel):
    role: Literal["MASTER", "REVERSE"]
    frame_receipt_id: FrameCandidateId
    frame_receipt_digest: Sha256Digest
    frame_digest: Sha256Digest


class SpatialExecutionEvidenceV1(M8ContractModel):
    user_id: NonBlank
    project_name: NonBlank
    execution_id: NonBlank
    task_id: NonBlank
    request_digest: Sha256Digest
    route_digest: Sha256Digest
    provider_job_id: str | None
    terminal_state: Literal["SUCCEEDED"]
    terminal_state_version: int = Field(ge=1)
    prompt_version: NonBlank
    prompt_digest: Sha256Digest
    normalizer_version: NonBlank
    raw_response: SpatialResponseObjectV1
    overlap_response: SpatialResponseObjectV1 | None
    ordered_source_frames: tuple[SpatialSourceFrameV1, SpatialSourceFrameV1]

    @model_validator(mode="after")
    def require_master_then_reverse(self) -> Self:
        master, reverse = self.ordered_source_frames
        if (master.role, reverse.role) != ("MASTER", "REVERSE"):
            raise ValueError("source frames must be ordered MASTER then REVERSE")
        if master.frame_receipt_id == reverse.frame_receipt_id:
            raise ValueError("MASTER and REVERSE must be distinct frames")
        return self

    @property
    def digest(self) -> str:
        return digest_canonical(
            {
                "domain": SPATIAL_EXECUTION_EVIDENCE_DOMAIN,
                "canonical_version": "1",
                "body": self.model_dump(mode="json"),
            }
        )


__all__ = [
    "SPATIAL_EXECUTION_EVIDENCE_DOMAIN",
    "SpatialExecutionEvidenceV1",
    "SpatialResponseObjectV1",
    "SpatialSourceFrameV1",
]
