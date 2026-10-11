"""Verify a stored V2 spatial pair decision and its scoped review custody."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from lib.db.models.spatial_pair import SpatialPairDecisionModel, SpatialPairV2CustodyModel
from lib.db.repositories.spatial_pair import SpatialPairIntegrityError
from r2.contracts.production_target import TargetVersionRef
from r2.contracts.spatial_pair import PairDecisionV2
from r2.spatial_pair.digests import pair_decision_digest_v2, scoped_pair_id


@dataclass(frozen=True)
class VerifiedPairDecisionV2:
    body: PairDecisionV2
    decision_digest: str


def verify_stored_pair_decision_v2(
    row: SpatialPairDecisionModel,
    custody: SpatialPairV2CustodyModel | None,
    *,
    user_id: str,
    project_name: str,
    binding_id: str,
    expected_binding_version: int,
    expected_envelope_digest: str,
    expected_core_digest: str,
    expected_target_ref: TargetVersionRef,
    expected_scene_ref: TargetVersionRef,
) -> VerifiedPairDecisionV2:
    try:
        if custody is None:
            raise ValueError("V2 decision custody is missing")
        body = PairDecisionV2.model_validate(row.decision_body_json)
        command = body.command
        decision_digest = pair_decision_digest_v2(body.model_dump(mode="json"))
        if (
            body.model_dump(mode="json") != row.decision_body_json
            or (row.user_id, row.project_name, custody.user_id, custody.project_name)
            != (user_id, project_name, user_id, project_name)
            or (command.user_id, command.project_name) != (user_id, project_name)
            or row.pair_id != scoped_pair_id(user_id=user_id, project_name=project_name, binding_id=binding_id)
            or body.pair_id != row.pair_id
            or (custody.pair_id, custody.pair_version) != (row.pair_id, row.pair_version)
            or body.pair_version != row.pair_version
            or (row.binding_id, command.binding_id) != (binding_id, binding_id)
            or (row.binding_version, command.expected_binding_version)
            != (expected_binding_version, expected_binding_version)
            or (row.binding_envelope_digest, command.expected_envelope_digest)
            != (expected_envelope_digest, expected_envelope_digest)
            or (row.binding_core_digest, command.expected_core_digest) != (expected_core_digest, expected_core_digest)
            or command.expected_target_ref != expected_target_ref
            or command.expected_scene_ref != expected_scene_ref
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
            or (row.master_receipt_id, row.reverse_receipt_id)
            != (command.views[0].receipt_id, command.views[1].receipt_id)
            or row.decision != command.decision
            or row.command_digest != body.command_digest
            or row.authorization_digest != body.authorization_digest
            or (row.decision_digest, custody.decision_digest) != (decision_digest, decision_digest)
            or custody.review_session_id != command.review_session_id
            or custody.review_evidence_digest != command.review_evidence_digest
        ):
            raise ValueError("V2 decision row differs from its scoped body or custody")
        return VerifiedPairDecisionV2(body=body, decision_digest=decision_digest)
    except (ValidationError, ValueError, TypeError) as exc:
        raise SpatialPairIntegrityError("pair V2 decision integrity verification failed") from exc


__all__ = ["VerifiedPairDecisionV2", "verify_stored_pair_decision_v2"]
