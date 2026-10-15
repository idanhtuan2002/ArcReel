"""Host composition of the M7 master authority (ADR-0096).

Every server path that promotes or consumes an R2 master uses these functions, so the database
head stays the one authority and the file manifest stays its guarded projection.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable, Collection
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.artifact_manifest import ArtifactKind, ProjectArtifactManifestAdapter, decode_artifact_key_parts
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


async def _deferred_commit() -> None:
    """The enclosing transaction commits; the promotion stages its rows only."""


def master_authority_unit(session: AsyncSession, *, defer_commit: bool = False) -> MasterAuthorityUnit:
    """A promotion unit on ``session``; it commits the session unless ``defer_commit``."""
    return MasterAuthorityUnit(
        candidates=CandidateObjectRepository(session),
        authorities=MasterAuthorityRepository(session),
        receipts=PromotionReceiptRepository(session),
        commit=_deferred_commit if defer_commit else session.commit,
        clock=_utc_now,
    )


_ROW_CREATE_ATTEMPTS = 5


async def _ensure_authority_row(
    session_factory: async_sessionmaker[AsyncSession], *, user_id: str, project_name: str, artifact_key: str
) -> None:
    for attempt in range(_ROW_CREATE_ATTEMPTS):
        try:
            async with session_factory() as session:
                await MasterAuthorityRepository(session).get_current_version(
                    user_id=user_id, project_name=project_name, artifact_key=artifact_key
                )
                await session.commit()
            return
        except (IntegrityError, NoResultFound):
            # A concurrent approval is creating the same row; it is visible once that commits.
            if attempt == _ROW_CREATE_ATTEMPTS - 1:
                raise
            await asyncio.sleep(0.05 * (attempt + 1))


async def lock_current_master_rows(
    session: AsyncSession,
    *,
    user_id: str,
    project_name: str,
    artifact_keys: Collection[str],
) -> tuple[tuple[str, int], ...]:
    """Lock existing, promoted master heads in sorted order on the caller's transaction."""
    locked: list[tuple[str, int]] = []
    for key in sorted(set(artifact_keys)):
        version = (
            await session.execute(
                update(MasterAuthorityModel)
                .where(
                    MasterAuthorityModel.user_id == user_id,
                    MasterAuthorityModel.project_name == project_name,
                    MasterAuthorityModel.artifact_key == key,
                    MasterAuthorityModel.current_version > 0,
                )
                .values(current_version=MasterAuthorityModel.current_version)
                .returning(MasterAuthorityModel.current_version)
            )
        ).scalar_one_or_none()
        if version is None:
            raise MasterSupersededError("current master is missing in this scope")
        locked.append((key, version))
    return tuple(locked)


@asynccontextmanager
async def serialized_artifacts(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: str,
    project_name: str,
    artifact_keys: Collection[str],
) -> AsyncGenerator[AsyncSession]:
    """One transaction that holds the authority row write locks of ``artifact_keys`` until it commits.

    Missing rows are created first. The transaction then rewrites each row unchanged, in sorted
    key order, which takes the row locks on PostgreSQL and the database write lock on SQLite,
    across processes. Every writer that depends on those heads (a Gate C promotion or
    projection, a Gate D decision) runs inside, so none can interleave with another; the sorted
    order keeps multi-row holders from deadlocking. An error rolls everything back.
    """
    keys = sorted(set(artifact_keys))
    for key in keys:
        await _ensure_authority_row(session_factory, user_id=user_id, project_name=project_name, artifact_key=key)
    async with session_factory() as session, session.begin():
        for key in keys:
            await session.execute(
                update(MasterAuthorityModel)
                .where(
                    MasterAuthorityModel.user_id == user_id,
                    MasterAuthorityModel.project_name == project_name,
                    MasterAuthorityModel.artifact_key == key,
                )
                .values(current_version=MasterAuthorityModel.current_version)
            )
        yield session


def serialized_artifact(
    session_factory: async_sessionmaker[AsyncSession], *, user_id: str, project_name: str, artifact_key: str
):
    """``serialized_artifacts`` for one artifact."""
    return serialized_artifacts(
        session_factory, user_id=user_id, project_name=project_name, artifact_keys=(artifact_key,)
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


def scan_master_records(project_dir: Path) -> tuple[dict[str, ApprovedMasterMetadata], list[str]]:
    """The file manifest's approved masters by artifact key, and the episode-video keys whose R2
    metadata does not validate."""
    records: dict[str, ApprovedMasterMetadata] = {}
    invalid: list[str] = []
    for key, entry in ProjectArtifactManifestAdapter(Path(project_dir)).snapshot_entries().items():
        # Gate C masters are episode videos; no host route approves another kind.
        if key.kind is not ArtifactKind.EPISODE_VIDEO or entry.r2 is None:
            continue
        try:
            metadata = R2ArtifactMetadata.model_validate(entry.r2)
        except ValidationError:
            invalid.append(key.encode())
            continue
        if metadata.approved_master is not None:
            records[key.encode()] = metadata.approved_master
    return records, sorted(invalid)


def projected_master_records(project_dir: Path) -> dict[str, ApprovedMasterMetadata]:
    """The file manifest's approved masters by artifact key."""
    return scan_master_records(project_dir)[0]


def projected_masters(project_dir: Path) -> dict[str, str]:
    """The file manifest's approved masters: artifact key -> selected generation candidate id."""
    return {key: record.selected_candidate_id for key, record in projected_master_records(project_dir).items()}


def _is_projected_kind(artifact_key: str) -> bool:
    """Only manifest episode-video masters are projected; other slots (e.g. M8's) have no file master."""
    parts = decode_artifact_key_parts(artifact_key)
    return parts is not None and parts.kind == ArtifactKind.EPISODE_VIDEO.value


def file_master_projection(project_dir: Path, session: AsyncSession) -> FileMasterProjection:
    return FileMasterProjection(
        lambda _project, artifact_key: projected_masters(project_dir).get(artifact_key),
        candidates=CandidateObjectRepository(session),
    )


async def verify_masters(
    session: AsyncSession,
    *,
    user_id: str,
    project_name: str,
    project_dir: Path,
    artifact_keys: Collection[str] | None = None,
) -> tuple[tuple[str, int, str], ...]:
    """Raise ``MasterDivergedError`` if a master disagrees with its projection; return the verified heads.

    ``artifact_keys`` limits the check to the masters a request consumes; ``None`` checks all.
    """
    authorities = MasterAuthorityRepository(session)
    database_keys = [
        key
        for key in await authorities.list_current_keys(user_id=user_id, project_name=project_name)
        if _is_projected_kind(key)
    ]
    projected = await asyncio.to_thread(projected_masters, project_dir)
    if artifact_keys is not None:
        wanted = set(artifact_keys)
        database_keys = [key for key in database_keys if key in wanted]
        projected = {key: value for key, value in projected.items() if key in wanted}
    return await verify_project_masters(
        user_id=user_id,
        project_name=project_name,
        authorities=authorities,
        projection=FileMasterProjection(
            lambda _project, artifact_key: projected.get(artifact_key), candidates=CandidateObjectRepository(session)
        ),
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
    "scan_master_records",
    "serialized_artifact",
    "serialized_artifacts",
    "verify_masters",
]
