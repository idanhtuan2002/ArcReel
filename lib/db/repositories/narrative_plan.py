"""Scoped SQLAlchemy adapter for the append-only NarrativePlan authority.

``NarrativePlanRepository`` exposes scoped reads plus branch-free plan locking and
the authoritative write-port methods. It never commits, rolls back, or constructs a
session; the plan unit-of-work owns that lifecycle.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.narrative_plan import NarrativePlanModel, NarrativePlanVersionModel
from lib.db.repositories.base import rowcount
from r2.contracts import NarrativePlanHeadSnapshot, NarrativePlanVersionSnapshot
from r2.narrative_plan.errors import (
    NarrativePlanApprovalError,
    NarrativePlanIdentityConflictError,
    NarrativePlanValidationError,
)


def _mentions(exc: IntegrityError, needle: str) -> bool:
    return needle in str(getattr(exc, "orig", None) or exc).lower()


def _stored_aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _head_snapshot(row: NarrativePlanModel) -> NarrativePlanHeadSnapshot:
    try:
        return NarrativePlanHeadSnapshot.model_validate(
            {
                "plan_id": row.plan_id,
                "user_id": row.user_id,
                "project_name": row.project_name,
                "head_version": row.head_version,
                "created_at": _stored_aware(row.created_at),
                "created_by": row.created_by,
            }
        )
    except ValidationError as exc:
        raise NarrativePlanValidationError(f"corrupt narrative plan row {row.plan_id!r}: {exc}") from exc


def _version_snapshot(row: NarrativePlanVersionModel) -> NarrativePlanVersionSnapshot:
    try:
        return NarrativePlanVersionSnapshot.model_validate(
            {
                "plan_id": row.plan_id,
                "version": row.version,
                "user_id": row.user_id,
                "project_name": row.project_name,
                "plan_revision_id": row.plan_revision_id,
                "parent_version": row.parent_version,
                "canon_branch_id": row.canon_branch_id,
                "canon_version_id": row.canon_version_id,
                "schema_version": row.schema_version,
                "content": row.content_json,
                "content_hash": row.content_hash,
                "content_hash_algorithm": row.content_hash_algorithm,
                "content_hash_version": row.content_hash_version,
                "approval_ref": row.approval_ref,
                "approved_by": row.approved_by,
                "approved_at": _stored_aware(row.approved_at),
                "committed_at": _stored_aware(row.committed_at),
                "committed_by": row.committed_by,
            }
        )
    except ValidationError as exc:
        raise NarrativePlanValidationError(
            f"corrupt narrative plan version row {row.plan_id!r}/{row.version}: {exc}"
        ) from exc


class NarrativePlanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_plan_head(self, *, plan_id: str, project_name: str, user_id: str) -> NarrativePlanHeadSnapshot | None:
        row = (
            await self.session.execute(
                select(NarrativePlanModel).where(
                    NarrativePlanModel.plan_id == plan_id,
                    NarrativePlanModel.project_name == project_name,
                    NarrativePlanModel.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        return _head_snapshot(row) if row is not None else None

    async def get_version(
        self, *, plan_id: str, version: int, project_name: str, user_id: str
    ) -> NarrativePlanVersionSnapshot | None:
        row = (
            await self.session.execute(
                select(NarrativePlanVersionModel).where(
                    NarrativePlanVersionModel.plan_id == plan_id,
                    NarrativePlanVersionModel.version == version,
                    NarrativePlanVersionModel.project_name == project_name,
                    NarrativePlanVersionModel.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        return _version_snapshot(row) if row is not None else None

    async def get_version_by_revision(
        self, *, plan_revision_id: str, project_name: str, user_id: str
    ) -> NarrativePlanVersionSnapshot | None:
        # plan_revision_id is GLOBALLY unique: the lookup is not scope-filtered so the
        # service can reject cross-scope reuse before a write rather than leaning on the DB
        # uniqueness constraint. The returned snapshot carries user_id / project_name.
        _ = (project_name, user_id)
        row = (
            await self.session.execute(
                select(NarrativePlanVersionModel).where(NarrativePlanVersionModel.plan_revision_id == plan_revision_id)
            )
        ).scalar_one_or_none()
        return _version_snapshot(row) if row is not None else None

    async def get_version_by_approval(
        self, *, approval_ref: str, project_name: str, user_id: str
    ) -> NarrativePlanVersionSnapshot | None:
        # approval_ref is GLOBALLY unique -- see get_version_by_revision.
        _ = (project_name, user_id)
        row = (
            await self.session.execute(
                select(NarrativePlanVersionModel).where(NarrativePlanVersionModel.approval_ref == approval_ref)
            )
        ).scalar_one_or_none()
        return _version_snapshot(row) if row is not None else None

    async def list_plan_versions(
        self, *, plan_id: str, project_name: str, user_id: str
    ) -> tuple[NarrativePlanVersionSnapshot, ...]:
        rows = (
            (
                await self.session.execute(
                    select(NarrativePlanVersionModel)
                    .where(
                        NarrativePlanVersionModel.plan_id == plan_id,
                        NarrativePlanVersionModel.project_name == project_name,
                        NarrativePlanVersionModel.user_id == user_id,
                    )
                    .order_by(NarrativePlanVersionModel.version)
                )
            )
            .scalars()
            .all()
        )
        return tuple(_version_snapshot(row) for row in rows)

    async def lock_plan(self, *, plan_id: str, project_name: str, user_id: str) -> NarrativePlanHeadSnapshot | None:
        row = (
            await self.session.execute(
                select(NarrativePlanModel)
                .where(
                    NarrativePlanModel.plan_id == plan_id,
                    NarrativePlanModel.project_name == project_name,
                    NarrativePlanModel.user_id == user_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        return _head_snapshot(row) if row is not None else None

    async def insert_plan(self, head: NarrativePlanHeadSnapshot) -> None:
        self.session.add(
            NarrativePlanModel(
                plan_id=head.plan_id,
                user_id=head.user_id,
                project_name=head.project_name,
                head_version=head.head_version,
                created_at=head.created_at,
                created_by=head.created_by,
            )
        )
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise NarrativePlanIdentityConflictError(
                f"narrative plan {head.plan_id!r} already exists in this scope"
            ) from exc

    async def insert_version(self, version: NarrativePlanVersionSnapshot) -> None:
        self.session.add(
            NarrativePlanVersionModel(
                plan_id=version.plan_id,
                version=version.version,
                user_id=version.user_id,
                project_name=version.project_name,
                plan_revision_id=version.plan_revision_id,
                parent_version=version.parent_version,
                canon_branch_id=version.canon_branch_id,
                canon_version_id=version.canon_version_id,
                schema_version=version.schema_version,
                content_json=version.content.model_dump(mode="json"),
                content_hash=version.content_hash,
                content_hash_algorithm=version.content_hash_algorithm,
                content_hash_version=version.content_hash_version,
                approval_ref=version.approval_ref,
                approved_by=version.approved_by,
                approved_at=version.approved_at,
                approval_status="APPROVED",
                committed_at=version.committed_at,
                committed_by=version.committed_by,
            )
        )
        try:
            await self.session.flush()
        except IntegrityError as exc:
            if _mentions(exc, "approval_ref"):
                raise NarrativePlanApprovalError(
                    f"approval {version.approval_ref!r} was already recorded in this scope"
                ) from exc
            raise NarrativePlanIdentityConflictError(
                f"narrative plan version {version.plan_id!r}/{version.version} or revision "
                f"{version.plan_revision_id!r} conflicts with an existing row"
            ) from exc

    async def advance_head(
        self,
        *,
        plan_id: str,
        expected_version: int | None,
        new_version: int,
        project_name: str,
        user_id: str,
    ) -> None:
        head_predicate = (
            NarrativePlanModel.head_version.is_(None)
            if expected_version is None
            else NarrativePlanModel.head_version == expected_version
        )
        result = await self.session.execute(
            update(NarrativePlanModel)
            .where(
                NarrativePlanModel.plan_id == plan_id,
                NarrativePlanModel.project_name == project_name,
                NarrativePlanModel.user_id == user_id,
                head_predicate,
            )
            .values(head_version=new_version)
        )
        if rowcount(result) != 1:
            raise NarrativePlanValidationError("locked narrative plan head changed unexpectedly")

    async def flush(self) -> None:
        await self.session.flush()
