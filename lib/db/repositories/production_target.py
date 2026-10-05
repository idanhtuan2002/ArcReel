"""Scoped, transaction-owned reads of Take-derived target heads and versions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.production_target import (
    ProductionTargetCommandModel,
    ProductionTargetHeadModel,
    ProductionTargetVersionModel,
)
from r2.contracts.adaptation import AdmittedScreenplayRef
from r2.contracts.enums import CreativeApprovalStatus, ProductionBindingTarget
from r2.contracts.production import SceneSpec, ShotSpecV2
from r2.contracts.production_target import (
    TargetRegistrationResult,
    TargetRegistrationResultBody,
    TargetVersionBody,
    TargetVersionRef,
)
from r2.target_registry.digests import registration_result_digest, target_body_digest, target_version_digest


class ProductionTargetIntegrityError(ValueError):
    """A scoped target head, version or dependency fails authority validation."""


class ProductionTargetCommandConflictError(ValueError):
    """A scoped command ID has already been used for different input."""


@dataclass(frozen=True)
class VerifiedTargetVersion:
    ref: TargetVersionRef
    target: SceneSpec | ShotSpecV2
    admitted_screenplay_ref: AdmittedScreenplayRef
    take_derivation_version: str
    scene: VerifiedTargetVersion | None = None


@dataclass(frozen=True)
class TargetAdmissionHint:
    ref: TargetVersionRef
    admitted_screenplay_ref: AdmittedScreenplayRef


class ProductionTargetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def peek_current_admission_hint(
        self, *, user_id: str, project_name: str, target_type: ProductionBindingTarget | str, target_id: str
    ) -> TargetAdmissionHint | None:
        kind = ProductionBindingTarget(target_type)
        head = ProductionTargetHeadModel
        version = ProductionTargetVersionModel
        row = (
            await self.session.execute(
                select(
                    head.current_version,
                    head.current_version_digest,
                    version.version_digest,
                    version.admitted_screenplay_ref_json,
                )
                .select_from(head)
                .outerjoin(
                    version,
                    and_(
                        version.user_id == head.user_id,
                        version.project_name == head.project_name,
                        version.target_type == head.target_type,
                        version.target_id == head.target_id,
                        version.registry_version == head.current_version,
                    ),
                )
                .where(
                    head.user_id == user_id,
                    head.project_name == project_name,
                    head.target_type == kind.value,
                    head.target_id == target_id,
                )
            )
        ).one_or_none()
        if row is None:
            return None
        current_version, head_digest, version_digest, admission_json = row
        if current_version is None or head_digest is None or version_digest != head_digest or admission_json is None:
            raise ProductionTargetIntegrityError("target admission hint has no complete current version")
        try:
            return TargetAdmissionHint(
                ref=TargetVersionRef(
                    target_type=kind,
                    target_id=target_id,
                    registry_version=current_version,
                    version_digest=head_digest,
                ),
                admitted_screenplay_ref=AdmittedScreenplayRef.model_validate(admission_json),
            )
        except (ValidationError, ValueError) as exc:
            raise ProductionTargetIntegrityError("target admission hint is malformed") from exc

    async def get_command_receipt(
        self,
        *,
        user_id: str,
        project_name: str,
        principal: str,
        command_id: str,
        expected_command_digest: str,
    ) -> TargetRegistrationResult | None:
        row = await self.session.get(
            ProductionTargetCommandModel, (user_id, project_name, principal, command_id), populate_existing=True
        )
        if row is None:
            return None
        try:
            body = TargetRegistrationResultBody.model_validate(row.result_json)
            if (
                row.result_json != body.model_dump(mode="json")
                or body.command_digest != row.command_digest
                or registration_result_digest(body) != row.result_digest
            ):
                raise ValueError("receipt columns disagree with canonical result")
        except (ValidationError, ValueError) as exc:
            raise ProductionTargetIntegrityError("registration receipt integrity verification failed") from exc
        if row.command_digest != expected_command_digest:
            raise ProductionTargetCommandConflictError("registration command ID has different input")
        return TargetRegistrationResult.model_validate(
            body.model_dump(mode="json") | {"result_digest": row.result_digest}
        )

    async def lock_target_head(
        self, *, user_id: str, project_name: str, target_type: ProductionBindingTarget | str, target_id: str
    ) -> ProductionTargetHeadModel:
        kind = ProductionBindingTarget(target_type)
        insert = pg_insert if self.session.get_bind().dialect.name == "postgresql" else sqlite_insert
        statement = insert(ProductionTargetHeadModel).values(
            user_id=user_id,
            project_name=project_name,
            target_type=kind.value,
            target_id=target_id,
            current_version=None,
            current_version_digest=None,
        )
        inserted = (
            await self.session.execute(
                statement.on_conflict_do_nothing(
                    index_elements=["user_id", "project_name", "target_type", "target_id"]
                ).returning(ProductionTargetHeadModel.target_id)
            )
        ).scalar_one_or_none()
        head = await self._head(
            user_id=user_id, project_name=project_name, target_type=kind, target_id=target_id, lock=True
        )
        if head is None:
            raise ProductionTargetIntegrityError("target head disappeared after scoped claim")
        if (head.current_version is None) != (head.current_version_digest is None):
            raise ProductionTargetIntegrityError("target head has incomplete current pair")
        if inserted is None and head.current_version is None:
            raise ProductionTargetIntegrityError("committed genesis target head has no current version")
        return head

    async def append_version(
        self, *, head: ProductionTargetHeadModel, body: TargetVersionBody, target: SceneSpec | ShotSpecV2
    ) -> TargetVersionRef:
        if (
            (head.user_id, head.project_name, head.target_type, head.target_id)
            != (body.user_id, body.project_name, body.target_type.value, body.target_id)
            or body.registry_version != (head.current_version or 0) + 1
            or target.id != body.target_id
            or target.approval_status != CreativeApprovalStatus.APPROVED
            or (body.target_type == ProductionBindingTarget.SCENE and not isinstance(target, SceneSpec))
            or (body.target_type == ProductionBindingTarget.SHOT and not isinstance(target, ShotSpecV2))
            or target_body_digest(body.target_type, target) != body.target_body_digest
        ):
            raise ProductionTargetIntegrityError("target append disagrees with locked head or canonical body")
        if head.current_version is not None:
            await self._version(head)
        dependency = body.scene_dependency
        if dependency is not None:
            if not isinstance(target, ShotSpecV2) or target.scene_id != dependency.target_id:
                raise ProductionTargetIntegrityError("Shot scene dependency disagrees with target body")
            scene_head = await self._head(
                user_id=body.user_id,
                project_name=body.project_name,
                target_type=ProductionBindingTarget.SCENE,
                target_id=dependency.target_id,
                lock=True,
            )
            if scene_head is None:
                raise ProductionTargetIntegrityError("Shot scene dependency is missing")
            scene = self._verify_row(await self._version(scene_head), body.admitted_screenplay_ref)
            if (scene.ref.registry_version, scene.ref.version_digest) != (
                dependency.registry_version,
                dependency.target_version_digest,
            ):
                raise ProductionTargetIntegrityError("Shot scene dependency is not current")
        digest = target_version_digest(body)
        self.session.add(
            ProductionTargetVersionModel(
                user_id=body.user_id,
                project_name=body.project_name,
                target_type=body.target_type.value,
                target_id=body.target_id,
                registry_version=body.registry_version,
                target_body_json=target.model_dump(mode="json"),
                target_body_digest=body.target_body_digest,
                admitted_screenplay_ref_json=body.admitted_screenplay_ref.model_dump(mode="json"),
                take_derivation_version=body.take_derivation_version,
                version_digest=digest,
                scene_target_type=None if dependency is None else dependency.target_type,
                scene_target_id=None if dependency is None else dependency.target_id,
                scene_registry_version=None if dependency is None else dependency.registry_version,
                scene_version_digest=None if dependency is None else dependency.target_version_digest,
                created_at=datetime.now(UTC),
            )
        )
        await self.session.flush()
        return TargetVersionRef(
            target_type=body.target_type,
            target_id=body.target_id,
            registry_version=body.registry_version,
            version_digest=digest,
        )

    async def advance_head(
        self,
        *,
        head: ProductionTargetHeadModel,
        expected_version: int | None,
        expected_digest: str | None,
        new_ref: TargetVersionRef,
    ) -> None:
        current = await self._head(
            user_id=head.user_id,
            project_name=head.project_name,
            target_type=ProductionBindingTarget(head.target_type),
            target_id=head.target_id,
            lock=True,
        )
        if (
            current is None
            or (current.current_version, current.current_version_digest) != (expected_version, expected_digest)
            or (new_ref.target_type.value, new_ref.target_id) != (head.target_type, head.target_id)
            or new_ref.registry_version != (expected_version or 0) + 1
        ):
            raise ProductionTargetIntegrityError("target head predecessor or new reference disagrees")
        row = await self.session.get(
            ProductionTargetVersionModel,
            (head.user_id, head.project_name, head.target_type, head.target_id, new_ref.registry_version),
            populate_existing=True,
        )
        if row is None or row.version_digest != new_ref.version_digest:
            raise ProductionTargetIntegrityError("target head successor version is missing or mismatched")
        current.current_version = new_ref.registry_version
        current.current_version_digest = new_ref.version_digest
        await self.session.flush()

    async def record_command(
        self,
        *,
        user_id: str,
        project_name: str,
        principal: str,
        command_id: str,
        result: TargetRegistrationResultBody,
    ) -> TargetRegistrationResult:
        digest = registration_result_digest(result)
        self.session.add(
            ProductionTargetCommandModel(
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
        return TargetRegistrationResult.model_validate(result.model_dump(mode="json") | {"result_digest": digest})

    async def _head(
        self, *, user_id: str, project_name: str, target_type: ProductionBindingTarget, target_id: str, lock: bool
    ) -> ProductionTargetHeadModel | None:
        statement = (
            select(ProductionTargetHeadModel)
            .where(
                ProductionTargetHeadModel.user_id == user_id,
                ProductionTargetHeadModel.project_name == project_name,
                ProductionTargetHeadModel.target_type == target_type.value,
                ProductionTargetHeadModel.target_id == target_id,
            )
            .execution_options(populate_existing=True)
        )
        if lock:
            statement = statement.with_for_update()
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def _version(self, head: ProductionTargetHeadModel) -> ProductionTargetVersionModel:
        if head.current_version is None or head.current_version_digest is None:
            raise ProductionTargetIntegrityError("target head integrity: committed genesis or incomplete current pair")
        row = (
            await self.session.execute(
                select(ProductionTargetVersionModel)
                .where(
                    ProductionTargetVersionModel.user_id == head.user_id,
                    ProductionTargetVersionModel.project_name == head.project_name,
                    ProductionTargetVersionModel.target_type == head.target_type,
                    ProductionTargetVersionModel.target_id == head.target_id,
                    ProductionTargetVersionModel.registry_version == head.current_version,
                )
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        latest = await self.session.scalar(
            select(func.max(ProductionTargetVersionModel.registry_version)).where(
                ProductionTargetVersionModel.user_id == head.user_id,
                ProductionTargetVersionModel.project_name == head.project_name,
                ProductionTargetVersionModel.target_type == head.target_type,
                ProductionTargetVersionModel.target_id == head.target_id,
            )
        )
        if row is None or latest != head.current_version or row.version_digest != head.current_version_digest:
            raise ProductionTargetIntegrityError("target head integrity: current version is missing or not latest")
        return row

    @staticmethod
    def _verify_row(
        row: ProductionTargetVersionModel, expected_admission: AdmittedScreenplayRef | None
    ) -> VerifiedTargetVersion:
        try:
            kind = ProductionBindingTarget(row.target_type)
            target = (
                SceneSpec.model_validate(row.target_body_json)
                if kind == ProductionBindingTarget.SCENE
                else ShotSpecV2.model_validate(row.target_body_json)
            )
            if target.id != row.target_id or target.approval_status != CreativeApprovalStatus.APPROVED:
                raise ValueError("target ID or approval status disagrees with stored authority")
            actual_body_digest = target_body_digest(kind, target)
            if actual_body_digest != row.target_body_digest:
                raise ValueError("stored target body digest disagrees with canonical body")
            dependency = None
            if any(
                value is not None
                for value in (
                    row.scene_target_type,
                    row.scene_target_id,
                    row.scene_registry_version,
                    row.scene_version_digest,
                )
            ):
                dependency = {
                    "target_type": row.scene_target_type,
                    "target_id": row.scene_target_id,
                    "registry_version": row.scene_registry_version,
                    "target_version_digest": row.scene_version_digest,
                }
            body = TargetVersionBody.model_validate(
                {
                    "user_id": row.user_id,
                    "project_name": row.project_name,
                    "registry_version": row.registry_version,
                    "admitted_screenplay_ref": row.admitted_screenplay_ref_json,
                    "take_derivation_version": row.take_derivation_version,
                    "target_type": kind,
                    "target_id": row.target_id,
                    "target_body_digest": row.target_body_digest,
                    "scene_dependency": dependency,
                }
            )
            if expected_admission is not None and body.admitted_screenplay_ref != expected_admission:
                raise ValueError("target admission does not match the expected full admission")
            if kind == ProductionBindingTarget.SHOT and (
                not isinstance(target, ShotSpecV2)
                or body.scene_dependency is None
                or target.scene_id != body.scene_dependency.target_id
            ):
                raise ValueError("Shot scene ID disagrees with its registry dependency")
            actual_version_digest = target_version_digest(body)
            if actual_version_digest != row.version_digest:
                raise ValueError("stored target version digest disagrees with canonical version")
            return VerifiedTargetVersion(
                ref=TargetVersionRef(
                    target_type=kind,
                    target_id=row.target_id,
                    registry_version=row.registry_version,
                    version_digest=row.version_digest,
                ),
                target=target,
                admitted_screenplay_ref=body.admitted_screenplay_ref,
                take_derivation_version=body.take_derivation_version,
            )
        except (ValidationError, ValueError) as exc:
            raise ProductionTargetIntegrityError("target version integrity verification failed") from exc

    async def get_current_verified(
        self,
        *,
        user_id: str,
        project_name: str,
        target_type: ProductionBindingTarget | str,
        target_id: str,
        expected_admission: AdmittedScreenplayRef | None,
    ) -> VerifiedTargetVersion | None:
        kind = ProductionBindingTarget(target_type)
        if kind == ProductionBindingTarget.SCENE:
            head = await self._head(
                user_id=user_id, project_name=project_name, target_type=kind, target_id=target_id, lock=True
            )
            return None if head is None else self._verify_row(await self._version(head), expected_admission)

        shot_hint = await self._head(
            user_id=user_id, project_name=project_name, target_type=kind, target_id=target_id, lock=False
        )
        if shot_hint is None:
            return None
        hint_version = await self._version(shot_hint)
        scene_id = hint_version.scene_target_id
        if hint_version.scene_target_type != ProductionBindingTarget.SCENE.value or scene_id is None:
            raise ProductionTargetIntegrityError("Shot scene dependency integrity verification failed")
        hint_snapshot = (
            hint_version.registry_version,
            hint_version.version_digest,
            hint_version.scene_target_type,
            hint_version.scene_target_id,
            hint_version.scene_registry_version,
            hint_version.scene_version_digest,
        )
        scene_head = await self._head(
            user_id=user_id,
            project_name=project_name,
            target_type=ProductionBindingTarget.SCENE,
            target_id=scene_id,
            lock=True,
        )
        shot_head = await self._head(
            user_id=user_id, project_name=project_name, target_type=kind, target_id=target_id, lock=True
        )
        if scene_head is None or shot_head is None:
            raise ProductionTargetIntegrityError("Shot scene/head integrity verification failed")
        shot_row = await self._version(shot_head)
        current_snapshot = (
            shot_row.registry_version,
            shot_row.version_digest,
            shot_row.scene_target_type,
            shot_row.scene_target_id,
            shot_row.scene_registry_version,
            shot_row.scene_version_digest,
        )
        if current_snapshot != hint_snapshot:
            raise ProductionTargetIntegrityError("Shot head changed after its untrusted scene hint")
        scene_row = await self._version(scene_head)
        scene = self._verify_row(scene_row, expected_admission)
        shot = self._verify_row(shot_row, expected_admission)
        if (
            shot_row.scene_registry_version != scene.ref.registry_version
            or shot_row.scene_version_digest != scene.ref.version_digest
            or shot.admitted_screenplay_ref != scene.admitted_screenplay_ref
        ):
            raise ProductionTargetIntegrityError("Shot scene dependency integrity verification failed")
        return replace(shot, scene=scene)


__all__ = [
    "ProductionTargetCommandConflictError",
    "ProductionTargetIntegrityError",
    "ProductionTargetRepository",
    "TargetAdmissionHint",
    "VerifiedTargetVersion",
]
