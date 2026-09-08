"""Scoped SQLAlchemy adapters for the append-only Canon authority.

``CanonProjectionRepository`` exposes only scoped reads plus projection
load/upsert. ``CanonRepository`` adds branch locking and the authoritative
write-port methods. Neither commits, rolls back, or constructs a session; the
Canon unit-of-work owns that lifecycle.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.canon import (
    CanonBranchModel,
    CanonDeltaModel,
    CanonResolvedProjectionModel,
    CanonVersionModel,
)
from lib.db.repositories.base import rowcount
from r2.contracts import (
    AcceptedCanonDeltaSnapshot,
    CanonBranchSnapshot,
    CanonCommitApproval,
    CanonDelta,
    CanonVersionSnapshot,
)
from r2.narrative.canon_state import ResolvedCanonView
from r2.narrative.errors import CanonApprovalError, CanonIdentityConflictError, CanonIntegrityError, CanonNotFoundError


def _is_unique_violation(exc: IntegrityError) -> bool:
    """A unique/exclusion constraint hit (23505/23P01) — not an FK or NOT NULL failure."""
    sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
    if sqlstate is not None:
        return sqlstate in {"23505", "23P01"}
    message = str(getattr(exc, "orig", None) or exc).lower()
    return "unique constraint failed" in message or "unique" in message


def _stored_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _require_stored_aware(value: datetime | None, *, field: str) -> datetime:
    aware = _stored_aware(value)
    if aware is None:
        raise CanonIntegrityError(f"Canon row is missing required timestamp {field!r}")
    return aware


def _branch_snapshot(row: CanonBranchModel) -> CanonBranchSnapshot:
    # Stored selector strings (branch_type, ...) are coerced by the strict contract;
    # an unsupported value raises ValidationError -> CanonIntegrityError below.
    try:
        return CanonBranchSnapshot.model_validate(
            {
                "branch_id": row.branch_id,
                "user_id": row.user_id,
                "project_name": row.project_name,
                "branch_type": row.branch_type,
                "parent_branch_id": row.parent_branch_id,
                "parent_version_id": row.parent_version_id,
                "head_version_id": row.head_version_id,
                "created_at": _require_stored_aware(row.created_at, field="created_at"),
                "created_by": row.created_by,
            }
        )
    except ValidationError as exc:
        raise CanonIntegrityError(f"corrupt Canon branch row {row.branch_id!r}: {exc}") from exc


def _version_snapshot(row: CanonVersionModel) -> CanonVersionSnapshot:
    try:
        return CanonVersionSnapshot(
            canon_version_id=row.canon_version_id,
            branch_id=row.branch_id,
            version_number=row.version_number,
            parent_version_id=row.parent_version_id,
            committed_delta_id=row.committed_delta_id,
            committed_at=_require_stored_aware(row.committed_at, field="committed_at"),
            committed_by=row.committed_by,
            content_hash=row.content_hash,
            content_hash_algorithm=row.content_hash_algorithm,
            content_hash_version=row.content_hash_version,
            content_schema_version=row.content_schema_version,
        )
    except ValidationError as exc:
        raise CanonIntegrityError(f"corrupt Canon version row {row.canon_version_id!r}: {exc}") from exc


def _accepted_delta_snapshot(row: CanonDeltaModel) -> AcceptedCanonDeltaSnapshot:
    try:
        delta = CanonDelta.model_validate(
            {
                "canon_delta_id": row.canon_delta_id,
                "target_branch_id": row.target_branch_id,
                "base_canon_version_id": row.base_canon_version_id,
                "operations": row.operations_json,
                "source_change_set_refs": row.source_change_set_refs_json,
                "author_decision_refs": row.author_decision_refs_json,
                "validation_report_refs": row.validation_report_refs_json,
                "payload_hash_algorithm": row.payload_hash_algorithm,
                "payload_hash_version": row.payload_hash_version,
                "content_schema_version": row.content_schema_version,
                "created_at": _require_stored_aware(row.created_at, field="created_at"),
                "created_by": row.created_by,
                "payload_hash": row.payload_hash,
            }
        )
        approval = CanonCommitApproval.model_validate(
            {
                "approval_ref": row.approval_ref,
                "canon_delta_id": row.canon_delta_id,
                "payload_hash": row.payload_hash,
                "payload_hash_algorithm": row.payload_hash_algorithm,
                "payload_hash_version": row.payload_hash_version,
                "content_schema_version": row.content_schema_version,
                "project_name": row.project_name,
                "user_id": row.user_id,
                "approved_by": row.approved_by,
                "approved_at": _require_stored_aware(row.approved_at, field="approved_at"),
                "status": row.approval_status,
            }
        )
    except (ValidationError, CanonIntegrityError) as exc:
        raise CanonIntegrityError(f"corrupt Canon delta row {row.canon_delta_id!r}: {exc}") from exc
    return AcceptedCanonDeltaSnapshot(delta=delta, approval=approval, committed_version_id=row.committed_version_id)


class CanonProjectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_branch(self, *, branch_id: str, project_name: str, user_id: str) -> CanonBranchSnapshot | None:
        row = (
            await self.session.execute(
                select(CanonBranchModel).where(
                    CanonBranchModel.branch_id == branch_id,
                    CanonBranchModel.project_name == project_name,
                    CanonBranchModel.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        return _branch_snapshot(row) if row is not None else None

    async def get_version(
        self, *, canon_version_id: str, project_name: str, user_id: str
    ) -> CanonVersionSnapshot | None:
        row = (
            await self.session.execute(
                select(CanonVersionModel)
                .join(CanonBranchModel, CanonVersionModel.branch_id == CanonBranchModel.branch_id)
                .where(
                    CanonVersionModel.canon_version_id == canon_version_id,
                    CanonBranchModel.project_name == project_name,
                    CanonBranchModel.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        return _version_snapshot(row) if row is not None else None

    async def get_accepted_delta(
        self, *, canon_delta_id: str, project_name: str, user_id: str
    ) -> AcceptedCanonDeltaSnapshot | None:
        row = (
            await self.session.execute(
                select(CanonDeltaModel).where(
                    CanonDeltaModel.canon_delta_id == canon_delta_id,
                    CanonDeltaModel.project_name == project_name,
                    CanonDeltaModel.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        return _accepted_delta_snapshot(row) if row is not None else None

    async def get_accepted_delta_by_approval_ref(
        self, *, approval_ref: str, project_name: str, user_id: str
    ) -> AcceptedCanonDeltaSnapshot | None:
        row = (
            await self.session.execute(
                select(CanonDeltaModel).where(
                    CanonDeltaModel.approval_ref == approval_ref,
                    CanonDeltaModel.project_name == project_name,
                    CanonDeltaModel.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        return _accepted_delta_snapshot(row) if row is not None else None

    async def list_scope_branches(self, *, project_name: str, user_id: str) -> tuple[CanonBranchSnapshot, ...]:
        rows = (
            (
                await self.session.execute(
                    select(CanonBranchModel)
                    .where(
                        CanonBranchModel.project_name == project_name,
                        CanonBranchModel.user_id == user_id,
                    )
                    .order_by(CanonBranchModel.branch_id)
                )
            )
            .scalars()
            .all()
        )
        return tuple(_branch_snapshot(row) for row in rows)

    async def list_branch_versions(
        self, *, branch_id: str, project_name: str, user_id: str
    ) -> tuple[CanonVersionSnapshot, ...]:
        rows = (
            (
                await self.session.execute(
                    select(CanonVersionModel)
                    .join(CanonBranchModel, CanonVersionModel.branch_id == CanonBranchModel.branch_id)
                    .where(
                        CanonVersionModel.branch_id == branch_id,
                        CanonBranchModel.project_name == project_name,
                        CanonBranchModel.user_id == user_id,
                    )
                    .order_by(CanonVersionModel.version_number)
                )
            )
            .scalars()
            .all()
        )
        return tuple(_version_snapshot(row) for row in rows)

    async def load_projection(
        self, *, canon_version_id: str, project_name: str, user_id: str
    ) -> ResolvedCanonView | None:
        row = (
            await self.session.execute(
                select(CanonResolvedProjectionModel, CanonVersionModel.branch_id)
                .join(
                    CanonVersionModel,
                    CanonResolvedProjectionModel.canon_version_id == CanonVersionModel.canon_version_id,
                )
                .join(CanonBranchModel, CanonVersionModel.branch_id == CanonBranchModel.branch_id)
                .where(
                    CanonResolvedProjectionModel.canon_version_id == canon_version_id,
                    CanonBranchModel.project_name == project_name,
                    CanonBranchModel.user_id == user_id,
                )
            )
        ).one_or_none()
        if row is None:
            return None
        projection, version_branch_id = row
        try:
            view = ResolvedCanonView.model_validate(projection.resolved_view_json)
        except ValidationError:
            return None
        if (
            view.canon_version_id != canon_version_id
            or view.branch_id != version_branch_id
            or view.content_hash != projection.content_hash
            or view.content_hash_algorithm != projection.content_hash_algorithm
            or view.content_hash_version != projection.content_hash_version
            or view.content_schema_version != projection.content_schema_version
        ):
            return None
        return view

    async def upsert_projection(
        self, *, view: ResolvedCanonView, built_at: datetime, project_name: str, user_id: str
    ) -> None:
        if view.canon_version_id is None:
            raise CanonNotFoundError("cannot cache a projection for a versionless resolved view")
        referenced = await self.get_version(
            canon_version_id=view.canon_version_id, project_name=project_name, user_id=user_id
        )
        if referenced is None:
            raise CanonNotFoundError(f"cannot cache projection for unknown version {view.canon_version_id!r}")
        if referenced.branch_id != view.branch_id:
            raise CanonIntegrityError(
                f"resolved view labels branch {view.branch_id!r} but version "
                f"{view.canon_version_id!r} belongs to {referenced.branch_id!r}"
            )
        values = {
            "canon_version_id": view.canon_version_id,
            "resolved_view_json": view.model_dump(mode="json"),
            "content_hash": view.content_hash,
            "content_hash_algorithm": view.content_hash_algorithm,
            "content_hash_version": view.content_hash_version,
            "content_schema_version": view.content_schema_version,
            "built_at": built_at,
        }
        dialect = self.session.get_bind().dialect.name
        if dialect == "postgresql":
            statement = pg_insert(CanonResolvedProjectionModel).values(**values)
        elif dialect == "sqlite":
            statement = sqlite_insert(CanonResolvedProjectionModel).values(**values)
        else:
            raise CanonIntegrityError(f"unsupported dialect for Canon projection upsert: {dialect}")
        statement = statement.on_conflict_do_update(
            index_elements=["canon_version_id"],
            set_={
                "resolved_view_json": statement.excluded.resolved_view_json,
                "content_hash": statement.excluded.content_hash,
                "content_hash_algorithm": statement.excluded.content_hash_algorithm,
                "content_hash_version": statement.excluded.content_hash_version,
                "content_schema_version": statement.excluded.content_schema_version,
                "built_at": statement.excluded.built_at,
            },
        )
        await self.session.execute(statement)


class CanonRepository(CanonProjectionRepository):
    async def lock_branch(self, *, branch_id: str, project_name: str, user_id: str) -> CanonBranchSnapshot:
        row = (
            await self.session.execute(
                select(CanonBranchModel)
                .where(
                    CanonBranchModel.branch_id == branch_id,
                    CanonBranchModel.project_name == project_name,
                    CanonBranchModel.user_id == user_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise CanonNotFoundError(f"Canon branch {branch_id!r} not found in scope")
        return _branch_snapshot(row)

    async def insert_branch(self, branch: CanonBranchSnapshot) -> None:
        self.session.add(
            CanonBranchModel(
                branch_id=branch.branch_id,
                user_id=branch.user_id,
                project_name=branch.project_name,
                branch_type=branch.branch_type.value,
                parent_branch_id=branch.parent_branch_id,
                parent_version_id=branch.parent_version_id,
                head_version_id=branch.head_version_id,
                created_at=branch.created_at,
                created_by=branch.created_by,
            )
        )
        try:
            await self.session.flush()
        except IntegrityError as exc:
            if not _is_unique_violation(exc):
                raise
            raise CanonIdentityConflictError(
                f"Canon branch {branch.branch_id!r} conflicts with an existing branch in this scope"
            ) from exc

    async def insert_delta(self, accepted: AcceptedCanonDeltaSnapshot) -> None:
        delta = accepted.delta
        approval = accepted.approval
        self.session.add(
            CanonDeltaModel(
                canon_delta_id=delta.canon_delta_id,
                user_id=approval.user_id,
                project_name=approval.project_name,
                target_branch_id=delta.target_branch_id,
                base_canon_version_id=delta.base_canon_version_id,
                operations_json=[operation.model_dump(mode="json") for operation in delta.operations],
                source_change_set_refs_json=list(delta.source_change_set_refs),
                author_decision_refs_json=list(delta.author_decision_refs),
                validation_report_refs_json=list(delta.validation_report_refs),
                payload_hash=delta.payload_hash,
                payload_hash_algorithm=delta.payload_hash_algorithm,
                payload_hash_version=delta.payload_hash_version,
                content_schema_version=delta.content_schema_version,
                created_at=delta.created_at,
                created_by=delta.created_by,
                approval_ref=approval.approval_ref,
                approved_by=approval.approved_by,
                approved_at=approval.approved_at,
                approval_status=approval.status,
                committed_version_id=accepted.committed_version_id,
            )
        )
        try:
            await self.session.flush()
        except IntegrityError as exc:
            if not _is_unique_violation(exc):
                raise
            raise CanonApprovalError(
                f"approval {approval.approval_ref!r} or delta {delta.canon_delta_id!r} "
                "was already recorded in this scope"
            ) from exc

    async def insert_version(self, version: CanonVersionSnapshot) -> None:
        self.session.add(
            CanonVersionModel(
                canon_version_id=version.canon_version_id,
                branch_id=version.branch_id,
                version_number=version.version_number,
                parent_version_id=version.parent_version_id,
                committed_delta_id=version.committed_delta_id,
                committed_at=version.committed_at,
                committed_by=version.committed_by,
                content_hash=version.content_hash,
                content_hash_algorithm=version.content_hash_algorithm,
                content_hash_version=version.content_hash_version,
                content_schema_version=version.content_schema_version,
            )
        )
        await self.session.flush()

    async def advance_head(
        self,
        *,
        branch_id: str,
        expected_head_id: str | None,
        version_id: str,
        project_name: str,
        user_id: str,
    ) -> None:
        head_predicate = (
            CanonBranchModel.head_version_id.is_(None)
            if expected_head_id is None
            else CanonBranchModel.head_version_id == expected_head_id
        )
        result = await self.session.execute(
            update(CanonBranchModel)
            .where(
                CanonBranchModel.branch_id == branch_id,
                CanonBranchModel.project_name == project_name,
                CanonBranchModel.user_id == user_id,
                head_predicate,
            )
            .values(head_version_id=version_id)
        )
        if rowcount(result) != 1:
            raise CanonIntegrityError("locked Canon branch head changed unexpectedly")

    async def flush(self) -> None:
        await self.session.flush()
