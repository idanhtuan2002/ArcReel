"""Local integrity verification for stored LOCATION binding versions."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from lib.db.models.production_binding import ProductionBindingVersionModel
from r2.contracts.preparation import ProductionBinding
from r2.contracts.production_binding_authority import BindingEnvelopeV1
from r2.contracts.production_target import TargetVersionRef
from r2.production_binding.digests import (
    binding_body_digest,
    binding_envelope_digest,
    scoped_location_binding_id,
    source_group_ref,
)


class ProductionBindingIntegrityError(ValueError):
    """A stored binding version disagrees with its canonical or scoped authority."""


@dataclass(frozen=True)
class VerifiedBindingVersion:
    body: ProductionBinding
    envelope: BindingEnvelopeV1
    envelope_digest: str


def verify_stored_binding_version(
    row: ProductionBindingVersionModel,
    *,
    user_id: str,
    project_name: str,
    expected_target_ref: TargetVersionRef,
    expected_scene_ref: TargetVersionRef,
) -> VerifiedBindingVersion:
    try:
        body = ProductionBinding.model_validate(row.binding_body_json)
        envelope = BindingEnvelopeV1.model_validate(row.envelope_json)
        if (
            body.model_dump(mode="json") != row.binding_body_json
            or envelope.model_dump(mode="json") != row.envelope_json
        ):
            raise ValueError("stored JSON is not the exact typed body")
        claims = envelope.ordered_claims
        frame_ids = [claim.frame_candidate_id for claim in claims]
        if (
            (row.user_id, row.project_name) != (user_id, project_name)
            or envelope.user_id != user_id
            or envelope.project_name != project_name
            or row.binding_id
            != scoped_location_binding_id(
                user_id=user_id, project_name=project_name, target_id=expected_target_ref.target_id
            )
            or body.id != row.binding_id
            or envelope.binding_id != row.binding_id
            or body.version != row.binding_version
            or envelope.binding_version != row.binding_version
            or body.target_id != expected_target_ref.target_id
            or envelope.target_ref != expected_target_ref
            or envelope.scene_ref != expected_scene_ref
            or body.asset_refs != frame_ids
            or body.production_ref
            != source_group_ref(user_id=user_id, project_name=project_name, frame_candidate_ids=frame_ids)
            or len({claim.parent_artifact_key for claim in claims}) != 2
            or (row.receipt_a_id, row.receipt_b_id) != tuple(frame_ids)
            or (row.target_type, row.target_id, row.target_registry_version, row.target_version_digest)
            != (
                expected_target_ref.target_type.value,
                expected_target_ref.target_id,
                expected_target_ref.registry_version,
                expected_target_ref.version_digest,
            )
            or (row.scene_type, row.scene_id, row.scene_registry_version, row.scene_version_digest)
            != (
                expected_scene_ref.target_type.value,
                expected_scene_ref.target_id,
                expected_scene_ref.registry_version,
                expected_scene_ref.version_digest,
            )
            or binding_body_digest(body) != row.binding_body_digest
            or envelope.binding_body_digest != row.binding_body_digest
            or binding_envelope_digest(envelope.model_dump(mode="json")) != row.envelope_digest
        ):
            raise ValueError("binding row disagrees with its exact scope or canonical contents")
        return VerifiedBindingVersion(body=body, envelope=envelope, envelope_digest=row.envelope_digest)
    except (ValidationError, ValueError, TypeError) as exc:
        raise ProductionBindingIntegrityError("binding version integrity verification failed") from exc


__all__ = ["ProductionBindingIntegrityError", "VerifiedBindingVersion", "verify_stored_binding_version"]
