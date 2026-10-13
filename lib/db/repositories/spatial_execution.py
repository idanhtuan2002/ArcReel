"""Scoped, append-only access to spatial execution evidence and its exact raw response."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.spatial_source import SpatialExecutionEvidenceModel
from r2.contracts.spatial_execution import SpatialExecutionEvidenceV1


@dataclass(frozen=True)
class StoredSpatialExecution:
    evidence: SpatialExecutionEvidenceV1
    candidate_id: str
    revision: int
    command_id: str
    raw_response: bytes


def _byte_digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _from_row(row: SpatialExecutionEvidenceModel) -> StoredSpatialExecution:
    evidence = SpatialExecutionEvidenceV1.model_validate(row.evidence_body_json)
    master, reverse = evidence.ordered_source_frames
    if (
        evidence.user_id != row.user_id
        or evidence.project_name != row.project_name
        or evidence.execution_id != row.execution_id
        or master.frame_receipt_id != row.master_frame_receipt_id
        or reverse.frame_receipt_id != row.reverse_frame_receipt_id
        or evidence.digest != row.evidence_digest
        or evidence.raw_response.byte_digest != _byte_digest(row.raw_response)
    ):
        raise ValueError("spatial execution evidence row failed integrity verification")
    return StoredSpatialExecution(
        evidence=evidence,
        candidate_id=row.candidate_id,
        revision=row.revision,
        command_id=row.command_id,
        raw_response=bytes(row.raw_response),
    )


class SpatialExecutionEvidenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _one(self, *conditions: object) -> StoredSpatialExecution | None:
        row = (
            await self.session.execute(select(SpatialExecutionEvidenceModel).where(*conditions))  # pyright: ignore[reportArgumentType]
        ).scalar_one_or_none()
        return None if row is None else _from_row(row)

    async def get_by_execution(
        self, *, user_id: str, project_name: str, execution_id: str
    ) -> StoredSpatialExecution | None:
        return await self._one(
            SpatialExecutionEvidenceModel.user_id == user_id,
            SpatialExecutionEvidenceModel.project_name == project_name,
            SpatialExecutionEvidenceModel.execution_id == execution_id,
        )

    async def get_by_command(
        self, *, user_id: str, project_name: str, command_id: str
    ) -> StoredSpatialExecution | None:
        return await self._one(
            SpatialExecutionEvidenceModel.user_id == user_id,
            SpatialExecutionEvidenceModel.project_name == project_name,
            SpatialExecutionEvidenceModel.command_id == command_id,
        )

    async def stage(
        self,
        *,
        evidence: SpatialExecutionEvidenceV1,
        candidate_id: str,
        revision: int,
        command_id: str,
        raw_response: bytes,
        created_at: datetime,
    ) -> None:
        if evidence.raw_response.byte_digest != _byte_digest(raw_response):
            raise ValueError("raw response bytes differ from the evidence digest")
        master, reverse = evidence.ordered_source_frames
        self.session.add(
            SpatialExecutionEvidenceModel(
                user_id=evidence.user_id,
                project_name=evidence.project_name,
                execution_id=evidence.execution_id,
                candidate_id=candidate_id,
                revision=revision,
                command_id=command_id,
                master_frame_receipt_id=master.frame_receipt_id,
                reverse_frame_receipt_id=reverse.frame_receipt_id,
                evidence_body_json=evidence.model_dump(mode="json"),
                evidence_digest=evidence.digest,
                raw_response=raw_response,
                created_at=created_at,
            )
        )
        await self.session.flush()


__all__ = ["SpatialExecutionEvidenceRepository", "StoredSpatialExecution"]
