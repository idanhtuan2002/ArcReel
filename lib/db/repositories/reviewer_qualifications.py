"""Reviewer qualification records: append-only, content-addressed, read by exact profile scope."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.production_run import ReviewerQualificationModel
from r2.automation.identity import digest_value
from r2.automation.profiles import reviewer_is_qualified
from r2.contracts.automation import ReviewerQualification
from r2.contracts.common import ensure_json_value


def qualification_digest(record: ReviewerQualification) -> str:
    return digest_value(
        "r2.reviewer-qualification.v1",
        ensure_json_value(ReviewerQualification.model_validate(record).model_dump(mode="json")),
    )


class ReviewerQualificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(self, record: ReviewerQualification) -> str:
        record = ReviewerQualification.model_validate(record)
        digest = qualification_digest(record)
        if await self.session.get(ReviewerQualificationModel, digest) is None:
            self.session.add(
                ReviewerQualificationModel(
                    qualification_digest=digest,
                    profile_digest=record.profile_digest,
                    launch_profile_id=record.launch_profile_id,
                    language=record.language,
                    model_identity=record.model_identity,
                    config_digest=record.config_digest,
                    record_json=record.model_dump_json(),
                    created_at=datetime.now(UTC),
                )
            )
            await self.session.flush()
        return digest

    async def current(self, digest: str) -> ReviewerQualification | None:
        """The intact record of ``digest`` while it still meets the qualification rule."""
        row = await self.session.get(ReviewerQualificationModel, digest)
        if row is None:
            return None
        record = ReviewerQualification.model_validate_json(row.record_json)
        if qualification_digest(record) != digest or not reviewer_is_qualified(record):
            return None
        return record

    async def qualified(
        self, *, profile_digest: str, launch_profile_id: str, language: str
    ) -> tuple[ReviewerQualification, ...]:
        """Records of this scope whose corpus results meet the qualification rule; integrity is re-checked."""
        rows = (
            await self.session.execute(
                select(ReviewerQualificationModel).where(
                    ReviewerQualificationModel.profile_digest == profile_digest,
                    ReviewerQualificationModel.launch_profile_id == launch_profile_id,
                    ReviewerQualificationModel.language == language,
                )
            )
        ).scalars()
        found = []
        for row in rows:
            record = ReviewerQualification.model_validate_json(row.record_json)
            if qualification_digest(record) == row.qualification_digest and reviewer_is_qualified(record):
                found.append(record)
        return tuple(found)


__all__ = ["ReviewerQualificationRepository", "qualification_digest"]
