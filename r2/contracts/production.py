from enum import StrEnum
from typing import Annotated, Any

from pydantic import Discriminator, Field, Tag, field_validator

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


# ``ShotSpec`` above is the accepted v1 arm, unchanged (plan Task 3: "The existing
# class becomes the v1 arm without changing its accepted serialization or content
# hash") — it stays the concrete class every existing caller already constructs.
# ``ShotSpecV1`` is that same class under an explicit name for new v2-aware code.
ShotSpecV1 = ShotSpec


# Pinned Take vocabulary (XucroYuri/take@47c17216b5ad74ee7dd376e8508266e29aefae2c,
# packages/core/src/models/enums.ts) — Task 4 parity-tests these values against that
# exact pinned source via a Node runner; lifecycle/provider/rendered-asset enums from
# that source are excluded (out of scope here).
class ShotSize(StrEnum):
    EXTREME_WIDE = "extreme-wide"
    WIDE = "wide"
    FULL = "full"
    MEDIUM = "medium"
    MEDIUM_CLOSE = "medium-close"
    CLOSE = "close"
    EXTREME_CLOSE = "extreme-close"


class CameraAngle(StrEnum):
    EYE_LEVEL = "eye-level"
    LOW = "low"
    HIGH = "high"
    DUTCH = "dutch"
    OVER_SHOULDER = "over-shoulder"
    AERIAL = "aerial"
    BIRD = "bird"
    WORM = "worm"


class CameraMovement(StrEnum):
    STATIC = "static"
    PAN_LEFT = "pan-left"
    PAN_RIGHT = "pan-right"
    TILT_UP = "tilt-up"
    TILT_DOWN = "tilt-down"
    DOLLY_IN = "dolly-in"
    DOLLY_OUT = "dolly-out"
    TRACKING = "tracking"
    HANDHELD = "handheld"
    CRANE_UP = "crane-up"
    CRANE_DOWN = "crane-down"
    ZOOM_IN = "zoom-in"
    ZOOM_OUT = "zoom-out"
    ORBIT = "orbit"


class ShotSpecV2(ContractIdentity):
    """Preserves every v1 semantic field verbatim and adds the pinned Take
    ``shot_size``/``camera_angle``/``camera_movement`` vocabulary as strict,
    additional structured metadata alongside (not instead of) v1's free-text
    ``framing``/``camera`` fields."""

    scene_id: NonEmptyStr
    content_basis: ContentBasis

    purpose: NonEmptyStr
    target_duration: float = Field(gt=0)

    framing: NonEmptyStr
    camera: NonEmptyStr

    shot_size: ShotSize
    camera_angle: CameraAngle
    camera_movement: CameraMovement

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


def _shot_spec_discriminator(value: Any) -> str:
    """Structural, not field-based: v1 has no discriminator field to add without
    changing its accepted shape, so this inspects for a v2-only key/attribute
    instead. A v1-shaped payload can never satisfy v2 (missing required fields)
    and a v2-shaped payload can never satisfy v1 (``extra="forbid"``), so this is
    unambiguous either way — the callable only needs to pick a fast, correct tag."""
    if isinstance(value, ShotSpecV2):
        return "v2"
    if isinstance(value, ShotSpec):
        return "v1"
    if isinstance(value, dict):
        return "v2" if "shot_size" in value else "v1"
    return "v1"


AnyShotSpec = Annotated[
    Annotated[ShotSpecV1, Tag("v1")] | Annotated[ShotSpecV2, Tag("v2")],
    Discriminator(_shot_spec_discriminator),
]
