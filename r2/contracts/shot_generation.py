"""R2 shot generation contracts: the versioned execution profile a spatial shot is admitted to."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field

from r2.contracts.common import R2ContractModel
from r2.contracts.production_binding_authority import ExactName


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


__all__ = ["R2ExecutionProfileV1"]
