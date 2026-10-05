"""Local integrity verification for stored LOCATION binding versions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.production_binding import (
    ProductionBindingCommandModel,
    ProductionBindingHeadModel,
    ProductionBindingVersionModel,
)
from r2.contracts.preparation import ProductionBinding
from r2.contracts.production_binding_authority import BindingCreateResultV1, BindingEnvelopeV1
from r2.contracts.production_target import TargetVersionRef
from r2.production_binding.digests import (
    binding_body_digest,
    binding_create_result_digest,
    binding_envelope_digest,
    scoped_location_binding_id,
    source_group_ref,
)


class ProductionBindingIntegrityError(ValueError):
    """A stored binding version disagrees with its canonical or scoped authority."""


class ProductionBindingAlreadyCurrentError(ProductionBindingIntegrityError):
    """The first version of a scoped binding was already committed."""


@dataclass(frozen=True)
class VerifiedBindingVersion:
    body: ProductionBinding
    envelope: BindingEnvelopeV1
    envelope_digest: str


@dataclass(frozen=True)
class VerifiedBindingCommandReceipt:
    result: BindingCreateResultV1
    result_digest: str


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


class ProductionBindingRepository:
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
    ) -> VerifiedBindingCommandReceipt | None:
        """Check stored receipt integrity; the caller must separately recheck current authorities."""
        row = await self.session.get(
            ProductionBindingCommandModel, (user_id, project_name, principal, command_id), populate_existing=True
        )
        if row is None:
            return None
        try:
            result = BindingCreateResultV1.model_validate(row.result_json)
            if (
                result.model_dump(mode="json") != row.result_json
                or result.command_digest != row.command_digest
                or binding_create_result_digest(result.model_dump(mode="json")) != row.result_digest
            ):
                raise ValueError("stored command result disagrees with its columns")
        except (ValidationError, ValueError, TypeError) as exc:
            raise ProductionBindingIntegrityError("binding command receipt integrity verification failed") from exc
        if row.command_digest != expected_command_digest:
            raise ProductionBindingIntegrityError("binding command ID has different input")
        return VerifiedBindingCommandReceipt(result=result, result_digest=row.result_digest)

    async def record_command(
        self,
        *,
        user_id: str,
        project_name: str,
        principal: str,
        command_id: str,
        result: BindingCreateResultV1,
    ) -> VerifiedBindingCommandReceipt:
        digest = binding_create_result_digest(result.model_dump(mode="json"))
        self.session.add(
            ProductionBindingCommandModel(
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
        return VerifiedBindingCommandReceipt(result=result, result_digest=digest)

    async def _head(self, *, user_id: str, project_name: str, binding_id: str) -> ProductionBindingHeadModel | None:
        return (
            await self.session.execute(
                select(ProductionBindingHeadModel)
                .where(
                    ProductionBindingHeadModel.user_id == user_id,
                    ProductionBindingHeadModel.project_name == project_name,
                    ProductionBindingHeadModel.binding_id == binding_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()

    async def lock_binding_head(
        self, *, user_id: str, project_name: str, binding_id: str
    ) -> ProductionBindingHeadModel:
        insert = pg_insert if self.session.get_bind().dialect.name == "postgresql" else sqlite_insert
        statement = insert(ProductionBindingHeadModel).values(
            user_id=user_id,
            project_name=project_name,
            binding_id=binding_id,
            current_version=None,
            current_envelope_digest=None,
        )
        inserted = (
            await self.session.execute(
                statement.on_conflict_do_nothing(index_elements=["user_id", "project_name", "binding_id"]).returning(
                    ProductionBindingHeadModel.binding_id
                )
            )
        ).scalar_one_or_none()
        head = await self._head(user_id=user_id, project_name=project_name, binding_id=binding_id)
        if head is None:
            raise ProductionBindingIntegrityError("binding head integrity: disappeared after scoped claim")
        if (head.current_version is None) != (head.current_envelope_digest is None):
            raise ProductionBindingIntegrityError("binding head integrity: incomplete current pair")
        if inserted is None and head.current_version is None:
            raise ProductionBindingIntegrityError("binding head integrity: committed genesis head")
        if head.current_version is not None:
            raise ProductionBindingAlreadyCurrentError("binding head is already current")
        return head

    async def append_first_version(
        self, *, head: ProductionBindingHeadModel, body: ProductionBinding, envelope: BindingEnvelopeV1
    ) -> ProductionBindingVersionModel:
        current = await self._head(user_id=head.user_id, project_name=head.project_name, binding_id=head.binding_id)
        if (
            current is None
            or current.current_version is not None
            or current.current_envelope_digest is not None
            or body.version != 1
            or envelope.binding_version != 1
        ):
            raise ProductionBindingIntegrityError("binding first append disagrees with locked genesis head")
        target = envelope.target_ref
        scene = envelope.scene_ref
        claims = envelope.ordered_claims
        row = ProductionBindingVersionModel(
            user_id=head.user_id,
            project_name=head.project_name,
            binding_id=head.binding_id,
            binding_version=1,
            binding_body_json=body.model_dump(mode="json"),
            binding_body_digest=binding_body_digest(body),
            envelope_json=envelope.model_dump(mode="json"),
            envelope_digest=binding_envelope_digest(envelope.model_dump(mode="json")),
            target_type=target.target_type.value,
            target_id=target.target_id,
            target_registry_version=target.registry_version,
            target_version_digest=target.version_digest,
            scene_type=scene.target_type.value,
            scene_id=scene.target_id,
            scene_registry_version=scene.registry_version,
            scene_version_digest=scene.version_digest,
            receipt_a_id=claims[0].receipt_id,
            receipt_b_id=claims[1].receipt_id,
            created_at=datetime.now(UTC),
        )
        verify_stored_binding_version(
            row,
            user_id=head.user_id,
            project_name=head.project_name,
            expected_target_ref=target,
            expected_scene_ref=scene,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def advance_first_head(
        self,
        *,
        head: ProductionBindingHeadModel,
        version: ProductionBindingVersionModel,
        expected_target_ref: TargetVersionRef,
        expected_scene_ref: TargetVersionRef,
    ) -> None:
        current = await self._head(user_id=head.user_id, project_name=head.project_name, binding_id=head.binding_id)
        if current is None or current.current_version is not None or current.current_envelope_digest is not None:
            raise ProductionBindingIntegrityError("binding first head CAS predecessor disagrees")
        row = (
            await self.session.execute(
                select(ProductionBindingVersionModel)
                .where(
                    ProductionBindingVersionModel.user_id == head.user_id,
                    ProductionBindingVersionModel.project_name == head.project_name,
                    ProductionBindingVersionModel.binding_id == head.binding_id,
                    ProductionBindingVersionModel.binding_version == 1,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if (
            row is None
            or row.binding_version != version.binding_version
            or row.envelope_digest != version.envelope_digest
        ):
            raise ProductionBindingIntegrityError("binding first head CAS successor disagrees")
        latest = await self.session.scalar(
            select(func.max(ProductionBindingVersionModel.binding_version)).where(
                ProductionBindingVersionModel.user_id == head.user_id,
                ProductionBindingVersionModel.project_name == head.project_name,
                ProductionBindingVersionModel.binding_id == head.binding_id,
            )
        )
        if latest != 1:
            raise ProductionBindingIntegrityError("binding first head CAS successor is not latest")
        verified = verify_stored_binding_version(
            row,
            user_id=head.user_id,
            project_name=head.project_name,
            expected_target_ref=expected_target_ref,
            expected_scene_ref=expected_scene_ref,
        )
        current.current_version = 1
        current.current_envelope_digest = verified.envelope_digest
        await self.session.flush()

    async def get_current_verified(
        self,
        *,
        user_id: str,
        project_name: str,
        binding_id: str,
        expected_target_ref: TargetVersionRef,
        expected_scene_ref: TargetVersionRef,
    ) -> VerifiedBindingVersion | None:
        """Verify the current local row after the caller locked Scene and Shot authority."""
        head = await self._head(user_id=user_id, project_name=project_name, binding_id=binding_id)
        if head is None:
            return None
        if head.current_version is None or head.current_envelope_digest is None:
            raise ProductionBindingIntegrityError(
                "binding head integrity: committed genesis or incomplete current pair"
            )
        row = (
            await self.session.execute(
                select(ProductionBindingVersionModel)
                .where(
                    ProductionBindingVersionModel.user_id == user_id,
                    ProductionBindingVersionModel.project_name == project_name,
                    ProductionBindingVersionModel.binding_id == binding_id,
                    ProductionBindingVersionModel.binding_version == head.current_version,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        latest = await self.session.scalar(
            select(func.max(ProductionBindingVersionModel.binding_version)).where(
                ProductionBindingVersionModel.user_id == user_id,
                ProductionBindingVersionModel.project_name == project_name,
                ProductionBindingVersionModel.binding_id == binding_id,
            )
        )
        if row is None or latest != head.current_version or row.envelope_digest != head.current_envelope_digest:
            raise ProductionBindingIntegrityError("binding head integrity: current version is missing or not latest")
        return verify_stored_binding_version(
            row,
            user_id=user_id,
            project_name=project_name,
            expected_target_ref=expected_target_ref,
            expected_scene_ref=expected_scene_ref,
        )


__all__ = [
    "ProductionBindingAlreadyCurrentError",
    "ProductionBindingIntegrityError",
    "ProductionBindingRepository",
    "VerifiedBindingCommandReceipt",
    "VerifiedBindingVersion",
    "verify_stored_binding_version",
]
