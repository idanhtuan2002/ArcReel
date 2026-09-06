from pydantic import Field, field_validator

from .common import ContractIdentity, NonEmptyStr
from .content_basis import ContentBasis
from .enums import (
    CreativeApprovalStatus,
    ProductionBindingRole,
    ProductionMethod,
)


class SceneSpec(ContractIdentity):
    source_artifact_ref: NonEmptyStr
    source_unit_refs: list[NonEmptyStr] = Field(default_factory=list)
    content_basis: ContentBasis

    purpose: NonEmptyStr
    duration_target: float = Field(gt=0)

    temporal_context: NonEmptyStr | None = None
    location_ref: NonEmptyStr | None = None
    entity_refs: list[NonEmptyStr] = Field(default_factory=list)

    required_beats: list[NonEmptyStr] = Field(default_factory=list)
    continuity_requirements: list[NonEmptyStr] = Field(default_factory=list)

    allowed_methods: list[ProductionMethod] = Field(min_length=1)
    approval_status: CreativeApprovalStatus

    @field_validator("source_unit_refs", "entity_refs")
    @classmethod
    def normalize_set_like_refs(cls, value: list[str]) -> list[str]:
        return sorted(set(value))


class ShotSpec(ContractIdentity):
    scene_id: NonEmptyStr
    content_basis: ContentBasis

    purpose: NonEmptyStr
    target_duration: float = Field(gt=0)

    framing: NonEmptyStr
    camera: NonEmptyStr

    entity_refs: list[NonEmptyStr] = Field(default_factory=list)
    audio_intent: NonEmptyStr | None = None

    required_continuity: list[NonEmptyStr] = Field(default_factory=list)
    required_reference_roles: list[ProductionBindingRole] = Field(default_factory=list)

    allowed_methods: list[ProductionMethod] = Field(min_length=1)
    quality_tier: int = Field(ge=0)

    approval_status: CreativeApprovalStatus

    @field_validator("entity_refs")
    @classmethod
    def normalize_entity_refs(cls, value: list[str]) -> list[str]:
        return sorted(set(value))
