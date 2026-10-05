"""Resolve a current spatial frame receipt into verified immutable PNG bytes."""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.artifact_manifest import ArtifactManifestError
from lib.db.repositories.host_hardening import CandidateObjectRepository
from lib.db.repositories.spatial_source import SpatialFrameReceiptRepository, _receipt_digest
from lib.path_safety import PathTraversalError
from r2.contracts.spatial_source import FrameDerivationReceiptV1
from r2.host_hardening.master_resolver import MasterDivergedError
from server.services.master_authority import serialized_artifacts
from server.services.spatial_source import FrameDerivationService, FrameSourceConflictError, copy_frame_verified


@dataclass(frozen=True)
class VerifiedSpatialFrame:
    receipt: FrameDerivationReceiptV1
    receipt_digest: str
    png_bytes: bytes


class SpatialFrameReader:
    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession], project_dir: Path) -> None:
        self._sessions = session_factory
        self._project_dir = project_dir.resolve()
        self._parents = FrameDerivationService(session_factory=session_factory, project_dir=project_dir)

    async def read_locked(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        project_name: str,
        receipt_id: str,
        expected_receipt_digest: str,
        expected_parent_artifact_key: str,
    ) -> VerifiedSpatialFrame:
        try:
            receipt = await SpatialFrameReceiptRepository(session).get_exact(
                user_id=user_id, project_name=project_name, receipt_id=receipt_id
            )
        except ValueError as exc:
            raise FrameSourceConflictError("frame receipt integrity verification failed") from exc
        if receipt is None:
            raise FrameSourceConflictError("frame receipt is missing in this scope")
        receipt_digest = _receipt_digest(receipt)
        if receipt_digest != expected_receipt_digest:
            raise FrameSourceConflictError("frame receipt digest differs from pinned digest")
        identity = receipt.identity
        if identity.parent_artifact_key != expected_parent_artifact_key:
            raise FrameSourceConflictError("frame receipt parent differs from locked artifact key")
        try:
            head, _, _ = await self._parents._parent(
                session,
                user_id=user_id,
                project_name=project_name,
                artifact_key=expected_parent_artifact_key,
                expected_version=identity.parent_master_version,
            )
        except (ArtifactManifestError, MasterDivergedError) as exc:
            raise FrameSourceConflictError("frame parent master projection is incomplete") from exc
        except (NoResultFound, ValidationError) as exc:
            raise FrameSourceConflictError("frame parent metadata is missing or malformed") from exc
        except (OSError, PathTraversalError) as exc:
            raise FrameSourceConflictError("frame parent media is missing or unsafe") from exc
        if head.candidate_id != identity.parent_candidate_id or head.content_digest != identity.parent_content_digest:
            raise FrameSourceConflictError("frame parent differs from approved master")
        try:
            candidate = await CandidateObjectRepository(session).get_exact(
                user_id=user_id, project_name=project_name, candidate_id=receipt.frame_candidate_id
            )
        except ValidationError as exc:
            raise FrameSourceConflictError("frame candidate metadata is malformed") from exc
        frame_path = self._project_dir / "spatial" / "frames" / f"{receipt.frame_candidate_id}.png"
        if (
            candidate is None
            or candidate.project_name != project_name
            or candidate.candidate_id != receipt.frame_candidate_id
            or candidate.artifact_key != f"spatial_frame:{receipt.frame_candidate_id}"
            or candidate.object_ref != str(frame_path)
            or candidate.byte_size != receipt.frame_byte_size
            or candidate.content_digest != identity.frame_content_digest
            or candidate.media_probe_digest != receipt.frame_probe_digest
        ):
            raise FrameSourceConflictError("frame candidate differs from receipt")
        with tempfile.TemporaryDirectory(prefix=".m8frame-read-", dir=self._project_dir) as private_dir:
            png_bytes = await asyncio.to_thread(
                copy_frame_verified,
                frame_path,
                Path(private_dir) / "frame.png",
                expected_digest=identity.frame_content_digest,
                expected_size=receipt.frame_byte_size,
                expected_probe_digest=receipt.frame_probe_digest,
            )
        return VerifiedSpatialFrame(receipt=receipt, receipt_digest=receipt_digest, png_bytes=png_bytes)

    async def read_current(
        self, *, user_id: str, project_name: str, receipt_id: str, expected_receipt_digest: str
    ) -> VerifiedSpatialFrame:
        try:
            async with self._sessions() as session:
                receipt = await SpatialFrameReceiptRepository(session).get_exact(
                    user_id=user_id, project_name=project_name, receipt_id=receipt_id
                )
        except ValueError as exc:
            raise FrameSourceConflictError("frame receipt integrity verification failed") from exc
        if receipt is None:
            raise FrameSourceConflictError("frame receipt is missing in this scope")
        parent_key = receipt.identity.parent_artifact_key
        async with serialized_artifacts(
            self._sessions, user_id=user_id, project_name=project_name, artifact_keys=(parent_key,)
        ) as session:
            return await self.read_locked(
                session,
                user_id=user_id,
                project_name=project_name,
                receipt_id=receipt_id,
                expected_receipt_digest=expected_receipt_digest,
                expected_parent_artifact_key=parent_key,
            )


__all__ = ["SpatialFrameReader", "VerifiedSpatialFrame"]
