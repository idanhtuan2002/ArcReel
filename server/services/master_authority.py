"""Host composition of the M7 master authority (ADR-0096).

Every server path that promotes or consumes an R2 master uses these functions, so the database
head stays the one authority and the file manifest stays its guarded projection.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from lib.artifact_manifest import ArtifactKind, ProjectArtifactManifestAdapter
from lib.db.models.host_hardening import MasterAuthorityModel
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


class MasterSupersededError(RuntimeError):
    """The artifact's master head moved past this promotion before it was projected."""


async def project_if_current[T](
    session: AsyncSession,
    *,
    user_id: str,
    project_name: str,
    artifact_key: str,
    candidate_id: str,
    project: Callable[[], Awaitable[T]],
) -> T:
    """Run ``project`` only while ``candidate_id`` is the artifact's head, holding its write lock.

    The transaction first rewrites the artifact's authority row unchanged. That takes the row's
    write lock on PostgreSQL and the database write lock on SQLite, across processes, so a
    concurrent promotion or projection of the artifact waits, and the lock ends with the
    transaction, including on cancellation. A projection whose promotion was superseded writes
    nothing, so projections always follow the newest head.
    """
    async with session.begin():
        await session.execute(
            update(MasterAuthorityModel)
            .where(
                MasterAuthorityModel.user_id == user_id,
                MasterAuthorityModel.project_name == project_name,
                MasterAuthorityModel.artifact_key == artifact_key,
            )
            .values(current_version=MasterAuthorityModel.current_version)
        )
        head = await MasterAuthorityRepository(session).get_current(
            user_id=user_id, project_name=project_name, artifact_key=artifact_key
        )
        if head is None or head.candidate_id != candidate_id:
            raise MasterSupersededError(f"{artifact_key!r} was promoted again before this approval was projected")
        return await project()


def projected_master_records(project_dir: Path) -> dict[str, ApprovedMasterMetadata]:
    """The file manifest's approved masters by artifact key."""
    records: dict[str, ApprovedMasterMetadata] = {}
    for key, entry in ProjectArtifactManifestAdapter(Path(project_dir)).snapshot_entries().items():
        # Gate C masters are episode videos; no host route approves another kind.
        if key.kind is not ArtifactKind.EPISODE_VIDEO or entry.r2 is None:
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
    "MasterSupersededError",
    "file_master_projection",
    "master_authority_unit",
    "project_if_current",
    "projected_master_records",
    "projected_masters",
    "verify_masters",
]
