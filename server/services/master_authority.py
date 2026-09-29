"""Host composition of the M7 master authority (ADR-0096).

Every server path that promotes or consumes an R2 master uses these functions, so the database
head stays the one authority and the file manifest stays its guarded projection.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from lib.artifact_manifest import ProjectArtifactManifestAdapter
from lib.db.repositories.host_hardening import (
    CandidateObjectRepository,
    MasterAuthorityRepository,
    PromotionReceiptRepository,
)
from r2.host_hardening.master_authority import (
    FileMasterProjection,
    MasterAuthorityUnit,
    verify_project_masters,
)
from r2.production import ApprovedMasterMetadata, R2ArtifactMetadata


def _utc_now() -> datetime:
    return datetime.now(UTC)


def master_authority_unit(session: AsyncSession) -> MasterAuthorityUnit:
    """A promotion unit whose single commit is ``session``'s."""
    return MasterAuthorityUnit(
        candidates=CandidateObjectRepository(session),
        authorities=MasterAuthorityRepository(session),
        receipts=PromotionReceiptRepository(session),
        commit=session.commit,
        clock=_utc_now,
    )


def projected_master_records(project_dir: Path) -> dict[str, ApprovedMasterMetadata]:
    """The file manifest's approved masters by artifact key."""
    records: dict[str, ApprovedMasterMetadata] = {}
    for key, entry in ProjectArtifactManifestAdapter(Path(project_dir)).snapshot_entries().items():
        if entry.r2 is None:
            continue
        try:
            metadata = R2ArtifactMetadata.model_validate(entry.r2)
        except ValidationError:
            continue
        if metadata.approved_master is not None:
            records[key.encode()] = metadata.approved_master
    return records


def projected_masters(project_dir: Path) -> dict[str, str]:
    """The file manifest's approved masters: artifact key -> selected generation candidate id."""
    return {key: record.selected_candidate_id for key, record in projected_master_records(project_dir).items()}


def file_master_projection(project_dir: Path) -> FileMasterProjection:
    return FileMasterProjection(lambda _project, artifact_key: projected_masters(project_dir).get(artifact_key))


async def verify_masters(session: AsyncSession, *, user_id: str, project_name: str, project_dir: Path) -> None:
    """Raise ``MasterDivergedError`` if any of the project's masters disagrees with its projection."""
    authorities = MasterAuthorityRepository(session)
    database_keys = await authorities.list_current_keys(user_id=user_id, project_name=project_name)
    projected = await asyncio.to_thread(projected_masters, project_dir)
    await verify_project_masters(
        user_id=user_id,
        project_name=project_name,
        authorities=authorities,
        projection=FileMasterProjection(lambda _project, artifact_key: projected.get(artifact_key)),
        database_keys=database_keys,
        projected_keys=projected,
    )


__all__ = [
    "file_master_projection",
    "master_authority_unit",
    "projected_master_records",
    "projected_masters",
    "verify_masters",
]
