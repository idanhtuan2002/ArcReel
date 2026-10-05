"""Preparation-canonical digest domains for Take-derived target authority."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from r2.contracts.common import ensure_json_value
from r2.contracts.enums import ProductionBindingTarget
from r2.contracts.fingerprints import canonical_json_bytes
from r2.contracts.production import SceneSpec, ShotSpecV2
from r2.contracts.production_target import (
    TargetRegistrationCommandBody,
    TargetRegistrationResultBody,
    TargetVersionBody,
)


def _digest(domain: str, body: Mapping[str, Any]) -> str:
    envelope = ensure_json_value({"domain": domain, "canonical_version": "1", "body": dict(body)})
    return "sha256:" + hashlib.sha256(canonical_json_bytes(envelope)).hexdigest()


def target_body_digest(target_type: ProductionBindingTarget | str, target: SceneSpec | ShotSpecV2) -> str:
    kind = ProductionBindingTarget(target_type)
    if (kind == ProductionBindingTarget.SCENE and not isinstance(target, SceneSpec)) or (
        kind == ProductionBindingTarget.SHOT and not isinstance(target, ShotSpecV2)
    ):
        raise ValueError("target type does not match the Scene/Shot body")
    return _digest(
        "r2.production.target.body.v1", {"target_type": kind.value, "target": target.model_dump(mode="json")}
    )


def target_version_digest(body: TargetVersionBody | Mapping[str, Any]) -> str:
    validated = TargetVersionBody.model_validate(body)
    return _digest("r2.production.target.version.v1", validated.model_dump(mode="json"))


def registration_command_digest(body: TargetRegistrationCommandBody | Mapping[str, Any]) -> str:
    validated = TargetRegistrationCommandBody.model_validate(body)
    return _digest("r2.production.target.registration.command.v1", validated.model_dump(mode="json"))


def registration_result_digest(body: TargetRegistrationResultBody | Mapping[str, Any]) -> str:
    validated = TargetRegistrationResultBody.model_validate(body)
    return _digest("r2.production.target.registration.result.v1", validated.model_dump(mode="json"))


__all__ = [
    "registration_command_digest",
    "registration_result_digest",
    "target_body_digest",
    "target_version_digest",
]
