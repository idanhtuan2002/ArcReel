"""Local integrity verification for immutable spatial pair decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.spatial_pair import SpatialPairCommandModel, SpatialPairDecisionModel
from r2.contracts.production_target import TargetVersionRef
from r2.contracts.spatial_pair import PairDecisionResultV1, PairDecisionV1
from r2.spatial_pair.digests import pair_decision_digest, pair_result_digest, scoped_pair_id


class SpatialPairIntegrityError(ValueError):
    """A stored pair decision disagrees with its exact scoped authority."""


@dataclass(frozen=True)
class VerifiedPairDecision:
    body: PairDecisionV1
    decision_digest: str


@dataclass(frozen=True)
class VerifiedPairCommandReceipt:
    result: PairDecisionResultV1
    result_digest: str


class SpatialPairRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_command_receipt(
        self,
        *,
        user_id: str,
        project_name: str,
        principal: str,
        command_id: str,
        expected_command_digest: str,
    ) -> VerifiedPairCommandReceipt | None:
        """Check a stored receipt; the caller separately rechecks current authorities."""
        row = await self.session.get(
            SpatialPairCommandModel, (user_id, project_name, principal, command_id), populate_existing=True
        )
        if row is None:
            return None
        try:
            result = PairDecisionResultV1.model_validate(row.result_json)
            if (
                result.model_dump(mode="json") != row.result_json
                or result.command_digest != row.command_digest
                or pair_result_digest(result.model_dump(mode="json")) != row.result_digest
            ):
                raise ValueError("stored command result differs from its columns")
        except (ValidationError, ValueError, TypeError) as exc:
            raise SpatialPairIntegrityError("pair command receipt integrity verification failed") from exc
        if row.command_digest != expected_command_digest:
            raise SpatialPairIntegrityError("pair command ID has different input")
        return VerifiedPairCommandReceipt(result=result, result_digest=row.result_digest)

    async def record_command(
        self,
        *,
        user_id: str,
        project_name: str,
        principal: str,
        command_id: str,
        result: PairDecisionResultV1,
    ) -> VerifiedPairCommandReceipt:
        digest = pair_result_digest(result.model_dump(mode="json"))
        self.session.add(
            SpatialPairCommandModel(
                user_id=user_id,
                project_name=project_name,
                principal=principal,
                command_id=command_id,
                command_digest=result.command_digest,
                result_json=result.model_dump(mode="json"),
                result_digest=digest,
                created_at=datetime.now(UTC),
            )
        )
        await self.session.flush()
        return VerifiedPairCommandReceipt(result=result, result_digest=digest)


def verify_stored_pair_decision(
    row: SpatialPairDecisionModel,
    *,
    user_id: str,
    project_name: str,
    binding_id: str,
    expected_binding_version: int,
    expected_envelope_digest: str,
    expected_core_digest: str,
    expected_target_ref: TargetVersionRef,
    expected_scene_ref: TargetVersionRef,
) -> VerifiedPairDecision:
    try:
        body = PairDecisionV1.model_validate(row.decision_body_json)
        command = body.command
        if body.model_dump(mode="json") != row.decision_body_json:
            raise ValueError("stored pair JSON is not the exact typed body")
        if (
            (row.user_id, row.project_name) != (user_id, project_name)
            or (command.user_id, command.project_name) != (user_id, project_name)
            or row.pair_id != scoped_pair_id(user_id=user_id, project_name=project_name, binding_id=binding_id)
            or body.pair_id != row.pair_id
            or body.pair_version != row.pair_version
            or row.binding_id != binding_id
            or command.binding_id != binding_id
            or row.binding_version != expected_binding_version
            or command.expected_binding_version != expected_binding_version
            or row.binding_envelope_digest != expected_envelope_digest
            or command.expected_envelope_digest != expected_envelope_digest
            or row.binding_core_digest != expected_core_digest
            or command.expected_core_digest != expected_core_digest
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
            or pair_decision_digest(body.model_dump(mode="json")) != row.decision_digest
        ):
            raise ValueError("pair decision row differs from its exact scope or canonical contents")
        return VerifiedPairDecision(body=body, decision_digest=row.decision_digest)
    except (ValidationError, ValueError, TypeError) as exc:
        raise SpatialPairIntegrityError("pair decision integrity verification failed") from exc


__all__ = [
    "SpatialPairIntegrityError",
    "SpatialPairRepository",
    "VerifiedPairCommandReceipt",
    "VerifiedPairDecision",
    "verify_stored_pair_decision",
]
