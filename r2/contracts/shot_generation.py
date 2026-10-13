"""R2 shot generation contracts: the versioned execution profile a spatial shot is admitted to."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field

from r2.contracts.common import R2ContractModel
from r2.contracts.production_binding_authority import ExactName
from r2.contracts.production_target import Sha256Digest
from r2.contracts.spatial_source import FrameCandidateId


class R2ExecutionProfileV1(R2ContractModel):
    """One exact provider route, model and output setting set for an R2 shot.

    The M4 capability identity is kept separate from the backend model. Every output setting
    is explicit, so nothing is inherited from mutable backend defaults.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    profile_ref: ExactName
    capability_id: ExactName
    descriptor_version: ExactName
    provider_id: ExactName
    provider_model_id: ExactName
    backend_model_id: ExactName
    endpoint_id: ExactName
    adapter_version: ExactName
    capability_profile_ref: ExactName
    duration_seconds: int = Field(ge=1)
    resolution: ExactName
    aspect_ratio: ExactName
    watermark: bool
    seed: int | None
    prompt_extend: bool
    reference_images: Literal[2]
    max_prompt_chars: int = Field(ge=1)


class R2ShotSourceFrameV1(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    image_index: Literal[1, 2]
    view: Literal["MASTER", "REVERSE"]
    receipt_id: FrameCandidateId
    receipt_digest: Sha256Digest
    frame_content_digest: Sha256Digest


class R2ShotGenerationTaskV1(R2ContractModel):
    """Immutable task evidence for one admitted spatial shot; the worker re-derives and compares it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["r2_shot_generation_v1"]
    user_id: ExactName
    project_name: ExactName
    task_id: ExactName
    command_id: ExactName
    target_type: Literal["SHOT"]
    target_id: ExactName
    target_registry_version: int = Field(ge=1)
    target_digest: Sha256Digest
    binding_snapshot_digest: Sha256Digest
    spatial_set_digests: tuple[Sha256Digest, ...] = Field(min_length=1)
    ordered_source_frames: tuple[R2ShotSourceFrameV1, R2ShotSourceFrameV1]
    execution_profile_ref: ExactName
    prompt_plan_digest: Sha256Digest
    compiled_request_digest: Sha256Digest
    provider_prompt_digest: Sha256Digest
    provider_payload_digest: Sha256Digest
    host_request_digest: Sha256Digest
    submit_fingerprint: Sha256Digest


__all__ = ["R2ExecutionProfileV1", "R2ShotGenerationTaskV1", "R2ShotSourceFrameV1"]
