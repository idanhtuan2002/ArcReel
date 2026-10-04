"""Scoped, append-only access to spatial source-frame custody receipts."""

from __future__ import annotations

from datetime import UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.spatial_source import SpatialFrameReceiptModel
from r2.advanced_creative.digests import digest_canonical
from r2.contracts.spatial_source import FrameDerivationReceiptV1


def _receipt_digest(receipt: FrameDerivationReceiptV1) -> str:
    return digest_canonical({"domain": "r2.m8.spatial.frame.receipt.v1", "canonical_version": "1", "body": receipt})


def _from_row(row: SpatialFrameReceiptModel) -> FrameDerivationReceiptV1:
    receipt = FrameDerivationReceiptV1.model_validate(row.receipt_body_json)
    row_created_at = (
        row.created_at.replace(tzinfo=UTC) if row.created_at.tzinfo is None else row.created_at.astimezone(UTC)
    )
    if (
        receipt.identity.user_id != row.user_id
        or receipt.identity.project_name != row.project_name
        or receipt.identity.parent_artifact_key != row.parent_artifact_key
        or receipt.identity.parent_master_version != row.parent_master_version
        or receipt.identity.parent_candidate_id != row.parent_candidate_id
        or receipt.frame_candidate_id != row.receipt_id
        or receipt.frame_candidate_id != row.frame_candidate_id
        or receipt.frame_byte_size != row.frame_byte_size
        or receipt.frame_probe_digest != row.frame_probe_digest
        or receipt.command_digest != row.command_digest
        or receipt.created_at.astimezone(UTC) != row_created_at
        or _receipt_digest(receipt) != row.receipt_digest
    ):
        raise ValueError("spatial frame receipt row failed integrity verification")
    return receipt


class SpatialFrameReceiptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_exact(self, *, user_id: str, project_name: str, receipt_id: str) -> FrameDerivationReceiptV1 | None:
        row = (
            await self.session.execute(
                select(SpatialFrameReceiptModel).where(
                    SpatialFrameReceiptModel.user_id == user_id,
                    SpatialFrameReceiptModel.project_name == project_name,
                    SpatialFrameReceiptModel.receipt_id == receipt_id,
                )
            )
        ).scalar_one_or_none()
        return None if row is None else _from_row(row)

    async def get_by_command(
        self, *, user_id: str, project_name: str, command_id: str
    ) -> FrameDerivationReceiptV1 | None:
        row = (
            await self.session.execute(
                select(SpatialFrameReceiptModel).where(
                    SpatialFrameReceiptModel.user_id == user_id,
                    SpatialFrameReceiptModel.project_name == project_name,
                    SpatialFrameReceiptModel.command_id == command_id,
                )
            )
        ).scalar_one_or_none()
        return None if row is None else _from_row(row)

    async def insert(self, *, command_id: str, receipt: FrameDerivationReceiptV1) -> None:
        identity = receipt.identity
        if not command_id.strip():
            raise ValueError("command_id must be nonempty")
        self.session.add(
            SpatialFrameReceiptModel(
                user_id=identity.user_id,
                project_name=identity.project_name,
                receipt_id=receipt.frame_candidate_id,
                frame_candidate_id=receipt.frame_candidate_id,
                parent_artifact_key=identity.parent_artifact_key,
                parent_master_version=identity.parent_master_version,
                parent_candidate_id=identity.parent_candidate_id,
                command_id=command_id,
                command_digest=receipt.command_digest,
                frame_byte_size=receipt.frame_byte_size,
                frame_probe_digest=receipt.frame_probe_digest,
                receipt_body_json=receipt.model_dump(mode="json"),
                receipt_digest=_receipt_digest(receipt),
                created_at=receipt.created_at.astimezone(UTC),
            )
        )
        await self.session.flush()


__all__ = ["SpatialFrameReceiptRepository"]
