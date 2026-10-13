"""Transaction-bound storage and local integrity checks for spatial frame review."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.spatial_review import (
    SpatialReviewAcknowledgmentModel,
    SpatialReviewDeliveryModel,
    SpatialReviewSessionModel,
)
from r2.contracts.production_target import Sha256Digest
from r2.contracts.review_evidence import (
    ReviewAcknowledgmentV1,
    ReviewDeliveryV1,
    ReviewEvidenceV1,
    ReviewRole,
    ReviewSnapshotV1,
)
from r2.spatial_pair.review_digests import review_evidence_digest, review_snapshot_digest


class SpatialReviewIntegrityError(ValueError):
    """Review custody is absent, incomplete, stale or internally inconsistent."""


def _utc(value: datetime | str) -> datetime:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


class SpatialReviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _now(self) -> datetime:
        # SQLite's CURRENT_TIMESTAMP has whole-second precision; the grant ledger's SQLite clock is the
        # microsecond process clock, so review times must use the same one to order against imports.
        if self.session.get_bind().dialect.name != "postgresql":
            return datetime.now(UTC)
        value = await self.session.scalar(select(func.clock_timestamp()))
        if not isinstance(value, (datetime, str)):
            raise SpatialReviewIntegrityError("database time unavailable for review custody")
        return _utc(value)

    @staticmethod
    def _verify_snapshot_row(
        row: SpatialReviewSessionModel | None, *, user_id: str, project_name: str, principal: str, session_id: str
    ) -> ReviewSnapshotV1:
        if row is None:
            raise SpatialReviewIntegrityError("review session unavailable")
        try:
            snapshot = ReviewSnapshotV1.model_validate(row.snapshot_body_json)
            if (
                snapshot.model_dump(mode="json") != row.snapshot_body_json
                or snapshot.user_id != user_id
                or snapshot.project_name != project_name
                or snapshot.principal != principal
                or snapshot.session_id != session_id
                or row.principal != principal
                or row.snapshot_digest != review_snapshot_digest(row.snapshot_body_json)
                or _utc(row.created_at) != snapshot.created_at
                or _utc(row.expires_at) != snapshot.expires_at
            ):
                raise ValueError("review snapshot columns differ from body")
        except (ValidationError, ValueError, TypeError) as exc:
            raise SpatialReviewIntegrityError("stored review snapshot integrity verification failed") from exc
        return snapshot

    async def read_snapshot_hint(
        self, *, user_id: str, project_name: str, principal: str, session_id: str
    ) -> ReviewSnapshotV1:
        row = await self.session.get(SpatialReviewSessionModel, (user_id, project_name, session_id))
        return self._verify_snapshot_row(
            row, user_id=user_id, project_name=project_name, principal=principal, session_id=session_id
        )

    async def _locked_snapshot(
        self, *, user_id: str, project_name: str, principal: str, session_id: str
    ) -> tuple[SpatialReviewSessionModel, ReviewSnapshotV1]:
        row = (
            await self.session.execute(
                select(SpatialReviewSessionModel)
                .where(
                    SpatialReviewSessionModel.user_id == user_id,
                    SpatialReviewSessionModel.project_name == project_name,
                    SpatialReviewSessionModel.session_id == session_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        snapshot = self._verify_snapshot_row(
            row, user_id=user_id, project_name=project_name, principal=principal, session_id=session_id
        )
        assert row is not None
        return row, snapshot

    async def read_active(
        self, *, user_id: str, project_name: str, principal: str, session_id: str
    ) -> ReviewSnapshotV1:
        row, snapshot = await self._locked_snapshot(
            user_id=user_id, project_name=project_name, principal=principal, session_id=session_id
        )
        now = await self._now()
        if row.consumed_command_digest is not None or not snapshot.created_at <= now < snapshot.expires_at:
            raise SpatialReviewIntegrityError("review session is no longer active")
        return snapshot

    async def create_session(self, snapshot: ReviewSnapshotV1) -> None:
        now = await self._now()
        if not snapshot.created_at <= now < snapshot.expires_at:
            raise SpatialReviewIntegrityError("review session interval is not current")
        body = snapshot.model_dump(mode="json")
        self.session.add(
            SpatialReviewSessionModel(
                user_id=snapshot.user_id,
                project_name=snapshot.project_name,
                session_id=snapshot.session_id,
                principal=snapshot.principal,
                snapshot_body_json=body,
                snapshot_digest=review_snapshot_digest(body),
                created_at=snapshot.created_at,
                expires_at=snapshot.expires_at,
                consumed_command_digest=None,
            )
        )
        await self.session.flush()

    async def record_delivery_attempt(
        self,
        *,
        user_id: str,
        project_name: str,
        principal: str,
        session_id: str,
        attempt_id: str,
        role: ReviewRole,
    ) -> ReviewDeliveryV1:
        row, snapshot = await self._locked_snapshot(
            user_id=user_id, project_name=project_name, principal=principal, session_id=session_id
        )
        now = await self._now()
        if row.consumed_command_digest is not None or not snapshot.created_at <= now < snapshot.expires_at:
            raise SpatialReviewIntegrityError("review session is no longer active")
        frame = next((item for item in snapshot.frames if item.role == role), None)
        if frame is None:
            raise SpatialReviewIntegrityError("review frame role unavailable")
        delivery = ReviewDeliveryV1(attempt_id=attempt_id, role=role, png_digest=frame.png_digest, delivered_at=now)
        self.session.add(
            SpatialReviewDeliveryModel(
                user_id=user_id,
                project_name=project_name,
                session_id=session_id,
                attempt_id=attempt_id,
                role=role,
                png_digest=frame.png_digest,
                recorded_at=now,
            )
        )
        await self.session.flush()
        return delivery

    async def record_acknowledgment(
        self,
        *,
        user_id: str,
        project_name: str,
        principal: str,
        session_id: str,
        attempt_id: str,
        role: ReviewRole,
        png_digest: str,
        decoded: bool,
    ) -> ReviewAcknowledgmentV1:
        row, snapshot = await self._locked_snapshot(
            user_id=user_id, project_name=project_name, principal=principal, session_id=session_id
        )
        now = await self._now()
        if (
            row.consumed_command_digest is not None
            or not snapshot.created_at <= now < snapshot.expires_at
            or not decoded
        ):
            raise SpatialReviewIntegrityError("review acknowledgment is not admissible")
        delivery = await self.session.get(
            SpatialReviewDeliveryModel, (user_id, project_name, session_id, attempt_id), populate_existing=True
        )
        frame = next((item for item in snapshot.frames if item.role == role), None)
        if (
            delivery is None
            or frame is None
            or delivery.role != role
            or delivery.png_digest != png_digest
            or frame.png_digest != png_digest
            or not snapshot.created_at <= _utc(delivery.recorded_at) <= now
        ):
            raise SpatialReviewIntegrityError("review acknowledgment differs from delivered frame")
        acknowledgment = ReviewAcknowledgmentV1(
            principal=principal,
            role=role,
            png_digest=frame.png_digest,
            decoded=True,
            delivery_attempt_id=attempt_id,
            acknowledged_at=now,
        )
        self.session.add(
            SpatialReviewAcknowledgmentModel(
                user_id=user_id,
                project_name=project_name,
                session_id=session_id,
                role=role,
                attempt_id=attempt_id,
                principal=principal,
                png_digest=png_digest,
                decoded=True,
                recorded_at=now,
            )
        )
        await self.session.flush()
        return acknowledgment

    async def read_complete(
        self, *, user_id: str, project_name: str, principal: str, session_id: str
    ) -> tuple[ReviewEvidenceV1, str]:
        _, snapshot = await self._locked_snapshot(
            user_id=user_id, project_name=project_name, principal=principal, session_id=session_id
        )
        deliveries = (
            await self.session.scalars(
                select(SpatialReviewDeliveryModel)
                .where(
                    SpatialReviewDeliveryModel.user_id == user_id,
                    SpatialReviewDeliveryModel.project_name == project_name,
                    SpatialReviewDeliveryModel.session_id == session_id,
                )
                .order_by(SpatialReviewDeliveryModel.recorded_at, SpatialReviewDeliveryModel.attempt_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
        acknowledgments = (
            await self.session.scalars(
                select(SpatialReviewAcknowledgmentModel)
                .where(
                    SpatialReviewAcknowledgmentModel.user_id == user_id,
                    SpatialReviewAcknowledgmentModel.project_name == project_name,
                    SpatialReviewAcknowledgmentModel.session_id == session_id,
                )
                .order_by(SpatialReviewAcknowledgmentModel.role)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
        try:
            evidence = ReviewEvidenceV1.model_validate(
                {
                    "snapshot": snapshot.model_dump(mode="json"),
                    "snapshot_digest": review_snapshot_digest(snapshot.model_dump(mode="json")),
                    "deliveries": [
                        {
                            "attempt_id": item.attempt_id,
                            "role": item.role,
                            "png_digest": item.png_digest,
                            "delivered_at": _utc(item.recorded_at),
                        }
                        for item in deliveries
                    ],
                    "acknowledgments": [
                        {
                            "principal": item.principal,
                            "role": item.role,
                            "png_digest": item.png_digest,
                            "decoded": item.decoded,
                            "delivery_attempt_id": item.attempt_id,
                            "acknowledged_at": _utc(item.recorded_at),
                        }
                        for item in acknowledgments
                    ],
                }
            )
        except (ValidationError, ValueError, TypeError) as exc:
            raise SpatialReviewIntegrityError("stored review evidence is incomplete or invalid") from exc
        return evidence, review_evidence_digest(evidence.model_dump(mode="json"))

    async def consume_session(
        self,
        *,
        user_id: str,
        project_name: str,
        principal: str,
        session_id: str,
        expected_evidence_digest: str,
        command_digest: str,
    ) -> ReviewEvidenceV1:
        row, snapshot = await self._locked_snapshot(
            user_id=user_id, project_name=project_name, principal=principal, session_id=session_id
        )
        now = await self._now()
        if row.consumed_command_digest is not None or not snapshot.created_at <= now < snapshot.expires_at:
            raise SpatialReviewIntegrityError("review session is no longer available for a new decision")
        try:
            TypeAdapter(Sha256Digest).validate_python(command_digest)
        except ValidationError as exc:
            raise SpatialReviewIntegrityError("review command digest is invalid") from exc
        evidence, digest = await self.read_complete(
            user_id=user_id, project_name=project_name, principal=principal, session_id=session_id
        )
        if digest != expected_evidence_digest:
            raise SpatialReviewIntegrityError("review evidence digest differs from current stored evidence")
        row.consumed_command_digest = command_digest
        await self.session.flush()
        return evidence


__all__ = ["SpatialReviewIntegrityError", "SpatialReviewRepository"]
