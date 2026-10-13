"""Immutable typed spatial constraint sets; every read rehashes the stored body."""

from __future__ import annotations

from datetime import datetime

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.base import utc_now
from lib.db.models.spatial_pair import SpatialConstraintSetModel
from r2.contracts.spatial_constraint import SpatialConstraintSetV1
from r2.production_binding.spatial_set import spatial_constraint_set_digest, spatial_constraint_set_id


class SpatialConstraintSetIntegrityError(ValueError):
    """A stored or requested constraint set does not match its identity."""


class SpatialConstraintSetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def stage(self, constraint_set: SpatialConstraintSetV1, *, now: datetime | None = None) -> str:
        """Add the set unless the same bytes are already stored; return its ID. The caller commits."""
        body = constraint_set.model_dump(mode="json")
        digest = spatial_constraint_set_digest(body)
        set_id = spatial_constraint_set_id(digest)
        existing = await self.session.get(
            SpatialConstraintSetModel, (constraint_set.user_id, constraint_set.project_name, set_id)
        )
        if existing is not None:
            if existing.set_digest != digest or existing.body_json != body:
                raise SpatialConstraintSetIntegrityError("a stored constraint set differs from its ID")
            return set_id
        self.session.add(
            SpatialConstraintSetModel(
                user_id=constraint_set.user_id,
                project_name=constraint_set.project_name,
                set_id=set_id,
                set_digest=digest,
                binding_id=constraint_set.binding_id,
                master_receipt_id=constraint_set.ordered_sources[0].frame_derivation_receipt_id,
                reverse_receipt_id=constraint_set.ordered_sources[1].frame_derivation_receipt_id,
                body_json=body,
                created_at=now or utc_now(),
            )
        )
        await self.session.flush()
        return set_id

    async def get_verified(
        self,
        *,
        user_id: str,
        project_name: str,
        set_id: str,
        expected_digest: str,
        expected_binding_id: str,
    ) -> SpatialConstraintSetV1:
        row = (
            await self.session.execute(
                select(SpatialConstraintSetModel).where(
                    SpatialConstraintSetModel.user_id == user_id,
                    SpatialConstraintSetModel.project_name == project_name,
                    SpatialConstraintSetModel.set_id == set_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise SpatialConstraintSetIntegrityError("the named constraint set is missing")
        try:
            constraint_set = SpatialConstraintSetV1.model_validate(row.body_json)
            digest = spatial_constraint_set_digest(row.body_json)
        except (ValidationError, ValueError) as exc:
            raise SpatialConstraintSetIntegrityError("the stored constraint set is malformed") from exc
        if (
            digest != expected_digest
            or row.set_digest != digest
            or spatial_constraint_set_id(digest) != set_id
            or (constraint_set.user_id, constraint_set.project_name) != (user_id, project_name)
            or constraint_set.binding_id != expected_binding_id
            or row.binding_id != expected_binding_id
            or (row.master_receipt_id, row.reverse_receipt_id)
            != tuple(source.frame_derivation_receipt_id for source in constraint_set.ordered_sources)
        ):
            raise SpatialConstraintSetIntegrityError("the stored constraint set differs from its identity")
        return constraint_set


__all__ = ["SpatialConstraintSetIntegrityError", "SpatialConstraintSetRepository"]
