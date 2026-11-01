"""Launch qualification records: append-only, content-addressed; the newest intact record of a project scope is current."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.production_run import LaunchQualificationModel
from r2.automation.identity import digest_value
from r2.contracts.automation import LaunchQualification
from r2.contracts.common import ensure_json_value


def launch_qualification_digest(record: LaunchQualification) -> str:
    return digest_value(
        "r2.launch-qualification.v1",
        ensure_json_value(LaunchQualification.model_validate(record).model_dump(mode="json")),
    )


class LaunchQualificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(self, record: LaunchQualification, *, at: datetime | None = None) -> str:
        record = LaunchQualification.model_validate(record)
        digest = launch_qualification_digest(record)
        if await self.session.get(LaunchQualificationModel, digest) is None:
            self.session.add(
                LaunchQualificationModel(
                    qualification_digest=digest,
                    user_id=record.user_id,
                    project_name=record.project_name,
                    launch_profile_id=record.launch_profile_id,
                    record_json=record.model_dump_json(),
                    created_at=at or datetime.now(UTC),
                )
            )
            await self.session.flush()
        return digest

    async def current(self, *, user_id: str, project_name: str, launch_profile_id: str) -> LaunchQualification | None:
        """The newest record of this scope; a record whose stored bytes no longer match its digest is never current."""
        row = (
            await self.session.execute(
                select(LaunchQualificationModel)
                .where(
                    LaunchQualificationModel.user_id == user_id,
                    LaunchQualificationModel.project_name == project_name,
                    LaunchQualificationModel.launch_profile_id == launch_profile_id,
                )
                .order_by(LaunchQualificationModel.created_at.desc(), LaunchQualificationModel.qualification_digest)
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        record = LaunchQualification.model_validate_json(row.record_json)
        if launch_qualification_digest(record) != row.qualification_digest:
            return None
        return record


__all__ = ["LaunchQualificationRepository", "launch_qualification_digest"]
