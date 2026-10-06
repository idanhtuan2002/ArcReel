"""Local integrity verification for immutable spatial pair decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.spatial_pair import SpatialPairCommandModel, SpatialPairDecisionModel, SpatialPairHeadModel
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

    async def _head(self, *, user_id: str, project_name: str, pair_id: str) -> SpatialPairHeadModel | None:
        return (
            await self.session.execute(
                select(SpatialPairHeadModel)
                .where(
                    SpatialPairHeadModel.user_id == user_id,
                    SpatialPairHeadModel.project_name == project_name,
                    SpatialPairHeadModel.pair_id == pair_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()

    async def lock_pair_head(self, *, user_id: str, project_name: str, pair_id: str) -> SpatialPairHeadModel:
        insert = pg_insert if self.session.get_bind().dialect.name == "postgresql" else sqlite_insert
        statement = insert(SpatialPairHeadModel).values(
            user_id=user_id,
            project_name=project_name,
            pair_id=pair_id,
            current_version=None,
            current_decision_digest=None,
        )
        inserted = (
            await self.session.execute(
                statement.on_conflict_do_nothing(index_elements=["user_id", "project_name", "pair_id"]).returning(
                    SpatialPairHeadModel.pair_id
                )
            )
        ).scalar_one_or_none()
        head = await self._head(user_id=user_id, project_name=project_name, pair_id=pair_id)
        if head is None:
            raise SpatialPairIntegrityError("pair head integrity: disappeared after scoped claim")
        if (head.current_version is None) != (head.current_decision_digest is None):
            raise SpatialPairIntegrityError("pair head integrity: incomplete current pair")
        if inserted is None and head.current_version is None:
            raise SpatialPairIntegrityError("pair head integrity: committed genesis head")
        if head.current_version is not None:
            row = (
                await self.session.execute(
                    select(SpatialPairDecisionModel)
                    .where(
                        SpatialPairDecisionModel.user_id == user_id,
                        SpatialPairDecisionModel.project_name == project_name,
                        SpatialPairDecisionModel.pair_id == pair_id,
                        SpatialPairDecisionModel.pair_version == head.current_version,
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).scalar_one_or_none()
            latest = await self.session.scalar(
                select(func.max(SpatialPairDecisionModel.pair_version)).where(
                    SpatialPairDecisionModel.user_id == user_id,
                    SpatialPairDecisionModel.project_name == project_name,
                    SpatialPairDecisionModel.pair_id == pair_id,
                )
            )
            if row is None or latest != head.current_version or row.decision_digest != head.current_decision_digest:
                raise SpatialPairIntegrityError("pair head integrity: current decision is missing or not latest")
            try:
                body = PairDecisionV1.model_validate(row.decision_body_json)
                command = body.command
                verify_stored_pair_decision(
                    row,
                    user_id=user_id,
                    project_name=project_name,
                    binding_id=command.binding_id,
                    expected_binding_version=command.expected_binding_version,
                    expected_envelope_digest=command.expected_envelope_digest,
                    expected_core_digest=command.expected_core_digest,
                    expected_target_ref=command.expected_target_ref,
                    expected_scene_ref=command.expected_scene_ref,
                )
            except (ValidationError, SpatialPairIntegrityError) as exc:
                raise SpatialPairIntegrityError("pair head integrity: current decision is invalid") from exc
        return head

    async def append_decision(
        self,
        *,
        head: SpatialPairHeadModel,
        decision: PairDecisionV1,
        expected_binding_version: int,
        expected_envelope_digest: str,
        expected_core_digest: str,
        expected_target_ref: TargetVersionRef,
        expected_scene_ref: TargetVersionRef,
    ) -> SpatialPairDecisionModel:
        current = await self._head(user_id=head.user_id, project_name=head.project_name, pair_id=head.pair_id)
        if (
            current is None
            or current.current_version != head.current_version
            or current.current_decision_digest != head.current_decision_digest
            or decision.pair_version != (current.current_version or 0) + 1
            or decision.pair_id != head.pair_id
        ):
            raise SpatialPairIntegrityError("pair append disagrees with locked predecessor")
        command = decision.command
        target = command.expected_target_ref
        scene = command.expected_scene_ref
        digest = pair_decision_digest(decision.model_dump(mode="json"))
        row = SpatialPairDecisionModel(
            user_id=head.user_id,
            project_name=head.project_name,
            pair_id=head.pair_id,
            pair_version=decision.pair_version,
            decision_body_json=decision.model_dump(mode="json"),
            decision_digest=digest,
            command_digest=decision.command_digest,
            authorization_digest=decision.authorization_digest,
            binding_id=command.binding_id,
            binding_version=command.expected_binding_version,
            binding_envelope_digest=command.expected_envelope_digest,
            binding_core_digest=command.expected_core_digest,
            target_type=target.target_type.value,
            target_id=target.target_id,
            target_registry_version=target.registry_version,
            target_version_digest=target.version_digest,
            scene_type=scene.target_type.value,
            scene_id=scene.target_id,
            scene_registry_version=scene.registry_version,
            scene_version_digest=scene.version_digest,
            master_receipt_id=command.views[0].receipt_id,
            reverse_receipt_id=command.views[1].receipt_id,
            decision=command.decision,
            created_at=datetime.now(UTC),
        )
        verify_stored_pair_decision(
            row,
            user_id=head.user_id,
            project_name=head.project_name,
            binding_id=command.binding_id,
            expected_binding_version=expected_binding_version,
            expected_envelope_digest=expected_envelope_digest,
            expected_core_digest=expected_core_digest,
            expected_target_ref=expected_target_ref,
            expected_scene_ref=expected_scene_ref,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def advance_pair_head(
        self,
        *,
        head: SpatialPairHeadModel,
        decision: SpatialPairDecisionModel,
        expected_binding_version: int,
        expected_envelope_digest: str,
        expected_core_digest: str,
        expected_target_ref: TargetVersionRef,
        expected_scene_ref: TargetVersionRef,
    ) -> None:
        current = await self._head(user_id=head.user_id, project_name=head.project_name, pair_id=head.pair_id)
        if current is None or (current.current_version or 0) != decision.pair_version - 1:
            raise SpatialPairIntegrityError("pair head CAS predecessor disagrees")
        row = (
            await self.session.execute(
                select(SpatialPairDecisionModel)
                .where(
                    SpatialPairDecisionModel.user_id == head.user_id,
                    SpatialPairDecisionModel.project_name == head.project_name,
                    SpatialPairDecisionModel.pair_id == head.pair_id,
                    SpatialPairDecisionModel.pair_version == decision.pair_version,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        latest = await self.session.scalar(
            select(func.max(SpatialPairDecisionModel.pair_version)).where(
                SpatialPairDecisionModel.user_id == head.user_id,
                SpatialPairDecisionModel.project_name == head.project_name,
                SpatialPairDecisionModel.pair_id == head.pair_id,
            )
        )
        if row is None or latest != decision.pair_version or row.decision_digest != decision.decision_digest:
            raise SpatialPairIntegrityError("pair head CAS successor is missing or not latest")
        verified = verify_stored_pair_decision(
            row,
            user_id=head.user_id,
            project_name=head.project_name,
            binding_id=row.binding_id,
            expected_binding_version=expected_binding_version,
            expected_envelope_digest=expected_envelope_digest,
            expected_core_digest=expected_core_digest,
            expected_target_ref=expected_target_ref,
            expected_scene_ref=expected_scene_ref,
        )
        current.current_version = decision.pair_version
        current.current_decision_digest = verified.decision_digest
        await self.session.flush()

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
    ) -> VerifiedPairDecision | None:
        """Verify the current local pair after the caller locked target and binding authority."""
        pair_id = scoped_pair_id(user_id=user_id, project_name=project_name, binding_id=binding_id)
        head = (
            await self.session.execute(
                select(SpatialPairHeadModel)
                .where(
                    SpatialPairHeadModel.user_id == user_id,
                    SpatialPairHeadModel.project_name == project_name,
                    SpatialPairHeadModel.pair_id == pair_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if head is None:
            return None
        if head.current_version is None or head.current_decision_digest is None:
            raise SpatialPairIntegrityError("pair head integrity: committed genesis or incomplete current pair")
        row = (
            await self.session.execute(
                select(SpatialPairDecisionModel)
                .where(
                    SpatialPairDecisionModel.user_id == user_id,
                    SpatialPairDecisionModel.project_name == project_name,
                    SpatialPairDecisionModel.pair_id == pair_id,
                    SpatialPairDecisionModel.pair_version == head.current_version,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        latest = await self.session.scalar(
            select(func.max(SpatialPairDecisionModel.pair_version)).where(
                SpatialPairDecisionModel.user_id == user_id,
                SpatialPairDecisionModel.project_name == project_name,
                SpatialPairDecisionModel.pair_id == pair_id,
            )
        )
        if row is None or latest != head.current_version or row.decision_digest != head.current_decision_digest:
            raise SpatialPairIntegrityError("pair head integrity: current decision is missing or not latest")
        return verify_stored_pair_decision(
            row,
            user_id=user_id,
            project_name=project_name,
            binding_id=binding_id,
            expected_binding_version=expected_binding_version,
            expected_envelope_digest=expected_envelope_digest,
            expected_core_digest=expected_core_digest,
            expected_target_ref=expected_target_ref,
            expected_scene_ref=expected_scene_ref,
        )


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
