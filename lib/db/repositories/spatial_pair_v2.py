"""Verify a stored V2 spatial pair decision and its scoped review custody."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.spatial_pair import SpatialPairDecisionModel, SpatialPairHeadModel, SpatialPairV2CustodyModel
from lib.db.models.spatial_review import SpatialReviewSessionModel
from lib.db.repositories.spatial_pair import (
    SpatialPairIntegrityError,
    VerifiedPairDecision,
    verify_stored_pair_decision,
)
from lib.db.repositories.spatial_review import SpatialReviewIntegrityError, SpatialReviewRepository
from r2.contracts.production_target import TargetVersionRef
from r2.contracts.spatial_pair import PairDecisionV2
from r2.spatial_pair.digests import pair_decision_digest_v2, scoped_pair_id


@dataclass(frozen=True)
class VerifiedPairDecisionV2:
    body: PairDecisionV2
    decision_digest: str


class SpatialPairVersionedRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_current_verified(
        self,
        *,
        user_id: str,
        project_name: str,
        binding_id: str,
        expected_binding_version: int,
        expected_envelope_digest: str,
        expected_core_digest: str,
        expected_target_ref: TargetVersionRef,
        expected_scene_ref: TargetVersionRef,
    ) -> VerifiedPairDecision | VerifiedPairDecisionV2 | None:
        """Read local history after the caller locks current target and binding authority."""
        pair_id = scoped_pair_id(user_id=user_id, project_name=project_name, binding_id=binding_id)
        head = await self.session.get(
            SpatialPairHeadModel,
            (user_id, project_name, pair_id),
            with_for_update=True,
            populate_existing=True,
        )
        if head is None:
            return None
        if head.current_version is None or head.current_decision_digest is None:
            raise SpatialPairIntegrityError("pair head integrity: committed genesis or incomplete current pair")
        row = await self.session.get(
            SpatialPairDecisionModel,
            (user_id, project_name, pair_id, head.current_version),
            with_for_update=True,
            populate_existing=True,
        )
        latest = await self.session.scalar(
            select(func.max(SpatialPairDecisionModel.pair_version)).where(
                SpatialPairDecisionModel.user_id == user_id,
                SpatialPairDecisionModel.project_name == project_name,
                SpatialPairDecisionModel.pair_id == pair_id,
            )
        )
        if row is None or latest != head.current_version or row.decision_digest != head.current_decision_digest:
            raise SpatialPairIntegrityError("pair head integrity: current decision is missing or not latest")
        custody = await self.session.get(
            SpatialPairV2CustodyModel,
            (user_id, project_name, pair_id, head.current_version),
            with_for_update=True,
            populate_existing=True,
        )
        verified = verify_stored_pair_decision_versioned(
            row,
            custody,
            user_id=user_id,
            project_name=project_name,
            binding_id=binding_id,
            expected_binding_version=expected_binding_version,
            expected_envelope_digest=expected_envelope_digest,
            expected_core_digest=expected_core_digest,
            expected_target_ref=expected_target_ref,
            expected_scene_ref=expected_scene_ref,
        )
        if isinstance(verified, VerifiedPairDecisionV2):
            command = verified.body.command
            try:
                evidence, evidence_digest = await SpatialReviewRepository(self.session).read_complete(
                    user_id=user_id,
                    project_name=project_name,
                    principal=command.principal,
                    session_id=command.review_session_id,
                )
            except SpatialReviewIntegrityError as exc:
                raise SpatialPairIntegrityError("pair V2 stored review evidence is invalid") from exc
            session_row = await self.session.get(
                SpatialReviewSessionModel,
                (user_id, project_name, command.review_session_id),
                with_for_update=True,
                populate_existing=True,
            )
            if (
                session_row is None
                or session_row.consumed_command_digest != verified.body.command_digest
                or evidence != verified.body.review_evidence
                or evidence_digest != command.review_evidence_digest
            ):
                raise SpatialPairIntegrityError("pair V2 decision differs from stored review consumption")
        return verified


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


def verify_stored_pair_decision_versioned(
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
) -> VerifiedPairDecision | VerifiedPairDecisionV2:
    body = cast(object, row.decision_body_json)
    if not isinstance(body, dict):
        raise SpatialPairIntegrityError("pair decision body is not an object")
    expected = {
        "user_id": user_id,
        "project_name": project_name,
        "binding_id": binding_id,
        "expected_binding_version": expected_binding_version,
        "expected_envelope_digest": expected_envelope_digest,
        "expected_core_digest": expected_core_digest,
        "expected_target_ref": expected_target_ref,
        "expected_scene_ref": expected_scene_ref,
    }
    if "decision_schema" not in body:
        if custody is not None:
            raise SpatialPairIntegrityError("V1 pair decision has V2 custody")
        return verify_stored_pair_decision(row, **expected)
    if body["decision_schema"] == "r2.m8.spatial.pair.decision.v2":
        return verify_stored_pair_decision_v2(row, custody, **expected)
    raise SpatialPairIntegrityError("pair decision schema is unknown")


__all__ = [
    "SpatialPairVersionedRepository",
    "VerifiedPairDecisionV2",
    "verify_stored_pair_decision_v2",
    "verify_stored_pair_decision_versioned",
]
