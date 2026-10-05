"""Scoped, transaction-owned reads of Take-derived target heads and versions."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.production_target import ProductionTargetHeadModel, ProductionTargetVersionModel
from r2.contracts.adaptation import AdmittedScreenplayRef
from r2.contracts.enums import CreativeApprovalStatus, ProductionBindingTarget
from r2.contracts.production import SceneSpec, ShotSpecV2
from r2.contracts.production_target import TargetVersionBody, TargetVersionRef
from r2.target_registry.digests import target_body_digest, target_version_digest


class ProductionTargetIntegrityError(ValueError):
    """A scoped target head, version or dependency fails authority validation."""


@dataclass(frozen=True)
class VerifiedTargetVersion:
    ref: TargetVersionRef
    target: SceneSpec | ShotSpecV2
    admitted_screenplay_ref: AdmittedScreenplayRef
    take_derivation_version: str


class ProductionTargetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

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
        row: ProductionTargetVersionModel, expected_admission: AdmittedScreenplayRef
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
            if body.admitted_screenplay_ref != expected_admission:
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
        expected_admission: AdmittedScreenplayRef,
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
        ):
            raise ProductionTargetIntegrityError("Shot scene dependency integrity verification failed")
        return shot


__all__ = ["ProductionTargetIntegrityError", "ProductionTargetRepository", "VerifiedTargetVersion"]
