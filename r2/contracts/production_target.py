"""Take-derived target registry identities and canonical receipt bodies."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from r2.contracts.adaptation import AdmittedScreenplayRef
from r2.contracts.common import NonEmptyStr, R2ContractModel
from r2.contracts.enums import ProductionBindingTarget

Sha256Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class TargetVersionRef(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    target_type: ProductionBindingTarget
    target_id: NonEmptyStr
    registry_version: int = Field(ge=1)
    version_digest: Sha256Digest


class SceneVersionDependency(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    target_type: Literal["SCENE"]
    target_id: NonEmptyStr
    registry_version: int = Field(ge=1)
    target_version_digest: Sha256Digest


class TargetVersionBody(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: NonEmptyStr
    project_name: NonEmptyStr
    registry_version: int = Field(ge=1)
    admitted_screenplay_ref: AdmittedScreenplayRef
    take_derivation_version: NonEmptyStr
    target_type: ProductionBindingTarget
    target_id: NonEmptyStr
    target_body_digest: Sha256Digest
    scene_dependency: SceneVersionDependency | None

    @model_validator(mode="after")
    def check_scene_dependency(self) -> TargetVersionBody:
        if (self.target_type == ProductionBindingTarget.SHOT) != (self.scene_dependency is not None):
            raise ValueError("only a SHOT target version has a Scene registry dependency")
        return self


class TargetRegistrationCommandBody(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: NonEmptyStr
    project_name: NonEmptyStr
    principal: NonEmptyStr
    admitted_screenplay_ref: AdmittedScreenplayRef
    take_derivation_version: NonEmptyStr


class TargetRegistrationResultBody(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    command_digest: Sha256Digest
    scene_targets: tuple[TargetVersionRef, ...] = Field(min_length=1)
    shot_targets: tuple[TargetVersionRef, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def check_target_order(self) -> TargetRegistrationResultBody:
        for refs, expected in (
            (self.scene_targets, ProductionBindingTarget.SCENE),
            (self.shot_targets, ProductionBindingTarget.SHOT),
        ):
            ids = [ref.target_id for ref in refs]
            if ids != sorted(set(ids)) or any(ref.target_type != expected for ref in refs):
                raise ValueError("registration result targets must be typed, unique and sorted by ID")
        return self


class TargetRegistrationResult(TargetRegistrationResultBody):
    result_digest: Sha256Digest


__all__ = [
    "SceneVersionDependency",
    "TargetRegistrationCommandBody",
    "TargetRegistrationResult",
    "TargetRegistrationResultBody",
    "TargetVersionBody",
    "TargetVersionRef",
]
