"""Repositories for the P1 Gate A/D decisions and Gate C's additive receipt.

``append()`` computes ``sequence`` itself (a per-scope running count, +1 of
whatever is currently stored) inside the same nested transaction as the
insert; the table's own unique constraint on ``(user_id, project_name,
sequence)`` (or ``..., artifact_key, sequence`` for the receipt table) is the
race-safety net -- a concurrent append computing the same next sequence loses
at the database and surfaces as a typed conflict error, mirroring
``PromotionReceiptRepository.add``'s exact pattern.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.gates import FinalCutReceiptModel, GreenlightDecisionModel, PublishApprovalDecisionModel
from r2.contracts.gates import FinalCutReceipt, GreenlightDecision, PublishApprovalDecision


def _is_unique_violation(exc: IntegrityError) -> bool:
    """A unique constraint hit (23505 on PostgreSQL) -- not an FK or NOT NULL failure."""
    sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
    if sqlstate is not None:
        return sqlstate == "23505"
    message = str(getattr(exc, "orig", None) or exc).lower()
    return "unique constraint failed" in message or "unique" in message


def _stored_aware(value: datetime) -> datetime:
    """SQLite does not reliably round-trip ``tzinfo`` through ``DateTime(timezone=True)``;
    every stored timestamp here is UTC by construction, so a naive read is UTC."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class GateSequenceConflictError(RuntimeError):
    """Two concurrent appends computed the same next sequence number for the
    same scope; the caller should retry with a fresh read."""


class GreenlightRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(self, decision: GreenlightDecision) -> None:
        try:
            async with self.session.begin_nested():
                next_sequence = await self._next_sequence(user_id=decision.user_id, project_name=decision.project_name)
                self.session.add(
                    GreenlightDecisionModel(
                        user_id=decision.user_id,
                        project_name=decision.project_name,
                        decision_id=decision.decision_id,
                        source_digest=decision.source_digest,
                        action=decision.action,
                        sequence=next_sequence,
                        authorization_json=decision.authorization.model_dump(mode="json"),
                        created_at=decision.created_at,
                    )
                )
                await self.session.flush()
        except IntegrityError as exc:
            if not _is_unique_violation(exc):
                raise
            raise GateSequenceConflictError(
                f"a greenlight decision for {decision.project_name!r} raced on sequence assignment"
            ) from exc

    async def _next_sequence(self, *, user_id: str, project_name: str) -> int:
        current_max = await self.session.scalar(
            select(func.max(GreenlightDecisionModel.sequence)).where(
                GreenlightDecisionModel.user_id == user_id,
                GreenlightDecisionModel.project_name == project_name,
            )
        )
        return 1 if current_max is None else current_max + 1

    async def list_for_project(self, *, user_id: str, project_name: str) -> list[GreenlightDecision]:
        rows = (
            await self.session.execute(
                select(GreenlightDecisionModel)
                .where(
                    GreenlightDecisionModel.user_id == user_id,
                    GreenlightDecisionModel.project_name == project_name,
                )
                .order_by(GreenlightDecisionModel.sequence)
            )
        ).scalars()
        return [
            GreenlightDecision.model_validate(
                {
                    "decision_id": row.decision_id,
                    "user_id": row.user_id,
                    "project_name": row.project_name,
                    "source_digest": row.source_digest,
                    "action": row.action,
                    "authorization": row.authorization_json,
                    "sequence": row.sequence,
                    "created_at": _stored_aware(row.created_at),
                }
            )
            for row in rows
        ]


class PublishApprovalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(self, decision: PublishApprovalDecision) -> None:
        try:
            async with self.session.begin_nested():
                next_sequence = await self._next_sequence(user_id=decision.user_id, project_name=decision.project_name)
                self.session.add(
                    PublishApprovalDecisionModel(
                        user_id=decision.user_id,
                        project_name=decision.project_name,
                        decision_id=decision.decision_id,
                        deliverable_digest=decision.deliverable_digest,
                        platform=decision.platform,
                        visibility=decision.visibility,
                        action=decision.action,
                        sequence=next_sequence,
                        authorization_json=decision.authorization.model_dump(mode="json"),
                        created_at=decision.created_at,
                    )
                )
                await self.session.flush()
        except IntegrityError as exc:
            if not _is_unique_violation(exc):
                raise
            raise GateSequenceConflictError(
                f"a publish-approval decision for {decision.project_name!r} raced on sequence assignment"
            ) from exc

    async def _next_sequence(self, *, user_id: str, project_name: str) -> int:
        current_max = await self.session.scalar(
            select(func.max(PublishApprovalDecisionModel.sequence)).where(
                PublishApprovalDecisionModel.user_id == user_id,
                PublishApprovalDecisionModel.project_name == project_name,
            )
        )
        return 1 if current_max is None else current_max + 1

    async def list_for_project(self, *, user_id: str, project_name: str) -> list[PublishApprovalDecision]:
        rows = (
            await self.session.execute(
                select(PublishApprovalDecisionModel)
                .where(
                    PublishApprovalDecisionModel.user_id == user_id,
                    PublishApprovalDecisionModel.project_name == project_name,
                )
                .order_by(PublishApprovalDecisionModel.sequence)
            )
        ).scalars()
        return [
            PublishApprovalDecision.model_validate(
                {
                    "decision_id": row.decision_id,
                    "user_id": row.user_id,
                    "project_name": row.project_name,
                    "deliverable_digest": row.deliverable_digest,
                    "platform": row.platform,
                    "visibility": row.visibility,
                    "action": row.action,
                    "authorization": row.authorization_json,
                    "sequence": row.sequence,
                    "created_at": _stored_aware(row.created_at),
                }
            )
            for row in rows
        ]


class FinalCutReceiptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(self, receipt: FinalCutReceipt) -> None:
        try:
            async with self.session.begin_nested():
                next_sequence = await self._next_sequence(
                    user_id=receipt.user_id, project_name=receipt.project_name, artifact_key=receipt.artifact_key
                )
                self.session.add(
                    FinalCutReceiptModel(
                        final_cut_receipt_id=str(uuid.uuid4()),
                        user_id=receipt.user_id,
                        project_name=receipt.project_name,
                        artifact_key=receipt.artifact_key,
                        selected_candidate_id=receipt.selected_candidate_id,
                        content_fingerprint=receipt.content_fingerprint,
                        approval_record=receipt.approval_record,
                        selected_by=receipt.selected_by,
                        selected_at=receipt.selected_at,
                        sequence=next_sequence,
                    )
                )
                await self.session.flush()
        except IntegrityError as exc:
            if not _is_unique_violation(exc):
                raise
            raise GateSequenceConflictError(
                f"a Final Cut receipt for {receipt.artifact_key!r} raced on sequence assignment"
            ) from exc

    async def _next_sequence(self, *, user_id: str, project_name: str, artifact_key: str) -> int:
        current_max = await self.session.scalar(
            select(func.max(FinalCutReceiptModel.sequence)).where(
                FinalCutReceiptModel.user_id == user_id,
                FinalCutReceiptModel.project_name == project_name,
                FinalCutReceiptModel.artifact_key == artifact_key,
            )
        )
        return 1 if current_max is None else current_max + 1

    async def list_for_artifact(self, *, user_id: str, project_name: str, artifact_key: str) -> list[FinalCutReceipt]:
        rows = (
            await self.session.execute(
                select(FinalCutReceiptModel)
                .where(
                    FinalCutReceiptModel.user_id == user_id,
                    FinalCutReceiptModel.project_name == project_name,
                    FinalCutReceiptModel.artifact_key == artifact_key,
                )
                .order_by(FinalCutReceiptModel.sequence)
            )
        ).scalars()
        return [
            FinalCutReceipt(
                user_id=row.user_id,
                project_name=row.project_name,
                artifact_key=row.artifact_key,
                selected_candidate_id=row.selected_candidate_id,
                content_fingerprint=row.content_fingerprint,
                approval_record=row.approval_record,
                selected_by=row.selected_by,
                selected_at=_stored_aware(row.selected_at),
                sequence=row.sequence,
            )
            for row in rows
        ]


__all__ = [
    "FinalCutReceiptRepository",
    "GateSequenceConflictError",
    "GreenlightRepository",
    "PublishApprovalRepository",
]
