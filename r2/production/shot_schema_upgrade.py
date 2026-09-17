"""Exact-only v1 -> v2 ``ShotSpec`` legacy mapping (plan Task 3).

``ShotSpecV1``'s free-text ``framing``/``camera`` fields predate the pinned Take
vocabulary and were never a controlled vocabulary — different callers spelled the
same shot differently. This module maps only the exact strings this codebase's own
v1 corpus is known to use; anything else fails closed with
``ShotSpecManualMappingRequired`` rather than guessing at a compound or unfamiliar
description. There is no v1 source for ``camera_angle`` at all (v1's single
``camera`` field only ever encoded movement/stability, never framing angle), so
callers must always supply it explicitly.
"""

from __future__ import annotations

from r2.contracts.production import CameraAngle, CameraMovement, ShotSize, ShotSpecV1, ShotSpecV2

_FRAMING_TO_SHOT_SIZE: dict[str, ShotSize] = {
    "extreme-wide": ShotSize.EXTREME_WIDE,
    "wide": ShotSize.WIDE,
    "full": ShotSize.FULL,
    "medium": ShotSize.MEDIUM,
    "standard": ShotSize.MEDIUM,
    "medium-close": ShotSize.MEDIUM_CLOSE,
    "close-up": ShotSize.CLOSE,
    "close": ShotSize.CLOSE,
    "extreme-close": ShotSize.EXTREME_CLOSE,
}

_CAMERA_TO_MOVEMENT: dict[str, CameraMovement] = {
    "static": CameraMovement.STATIC,
    "locked": CameraMovement.STATIC,
    "pan-left": CameraMovement.PAN_LEFT,
    "pan-right": CameraMovement.PAN_RIGHT,
    "tilt-up": CameraMovement.TILT_UP,
    "tilt-down": CameraMovement.TILT_DOWN,
    "dolly-in": CameraMovement.DOLLY_IN,
    "dolly-out": CameraMovement.DOLLY_OUT,
    "tracking": CameraMovement.TRACKING,
    "handheld": CameraMovement.HANDHELD,
    "crane-up": CameraMovement.CRANE_UP,
    "crane-down": CameraMovement.CRANE_DOWN,
    "zoom-in": CameraMovement.ZOOM_IN,
    "zoom-out": CameraMovement.ZOOM_OUT,
    "orbit": CameraMovement.ORBIT,
}


class ShotSpecManualMappingRequired(ValueError):
    """SHOT_SPEC_MANUAL_MAPPING_REQUIRED: a v1 ``framing``/``camera`` string has no
    exact, known v2 mapping and must be resolved by a human, not guessed."""


def upgrade_shot_spec_v1(v1: ShotSpecV1, *, camera_angle: CameraAngle) -> ShotSpecV2:
    """Upgrade a v1 shot to v2, preserving every v1 field verbatim and adding the
    strict Take vocabulary. ``camera_angle`` has no v1 source and is always the
    caller's responsibility; ``shot_size``/``camera_movement`` are derived from
    ``framing``/``camera`` only when they match an exact known legacy spelling."""
    shot_size = _FRAMING_TO_SHOT_SIZE.get(v1.framing)
    if shot_size is None:
        raise ShotSpecManualMappingRequired(f"no exact shot_size mapping for framing={v1.framing!r}")
    camera_movement = _CAMERA_TO_MOVEMENT.get(v1.camera)
    if camera_movement is None:
        raise ShotSpecManualMappingRequired(f"no exact camera_movement mapping for camera={v1.camera!r}")

    return ShotSpecV2(
        id=v1.id,
        schema_version=v1.schema_version,
        version=v1.version,
        scene_id=v1.scene_id,
        content_basis=v1.content_basis,
        purpose=v1.purpose,
        target_duration=v1.target_duration,
        framing=v1.framing,
        camera=v1.camera,
        shot_size=shot_size,
        camera_angle=camera_angle,
        camera_movement=camera_movement,
        entity_refs=v1.entity_refs,
        audio_intent=v1.audio_intent,
        required_continuity=v1.required_continuity,
        required_reference_roles=v1.required_reference_roles,
        allowed_methods=v1.allowed_methods,
        quality_tier=v1.quality_tier,
        approval_status=v1.approval_status,
    )


__all__ = ["ShotSpecManualMappingRequired", "upgrade_shot_spec_v1"]
