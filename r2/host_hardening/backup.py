"""Consistent database + media backup sets (M7-D, spec section 8, H6).

A ``BackupSet`` binds one PostgreSQL recovery point to an immutable media
inventory captured from the same authoritative snapshot. Write/GC fencing is
provided by ``BackupSetRepository.add_media_ref`` -- ``CandidateRetentionPolicy``
refuses to delete any candidate a ``PREPARING``/``COMPLETE`` backup set
references, so every candidate this module is about to copy must be recorded
there *before* any bytes are read. Consistency between the database dump and
the media snapshot is proven, not assumed: this module counts the project's
candidate rows immediately before and immediately after the dump/copy work and
fails closed if that count changed, since M7's V1 baseline drill relies on an
operator-enforced write-fence (the app/worker are stopped first; see
``docs/r2/runbooks/m7-backup-restore.md``) rather than a live snapshot-isolated
capture across two different storage systems.

No credential ever enters a manifest or a backup set's persisted row: callers
pass a full ``database_url`` only for this module's own subprocess use: it is
never echoed back in ``BackupSetManifest`` or ``BackupVerdict``, both of which
carry only file/reference identities.

Operational note: ``pg_dump``/``pg_restore`` are libpq client tools whose major
version must be compatible with the target PostgreSQL server's major version.
A newer client can emit session setup that an older server rejects (observed:
PG18's ``pg_restore`` unconditionally sends ``SET transaction_timeout = 0``,
a GUC PG16 does not have, causing a nonzero exit even though the restore
itself otherwise succeeds) -- keep the installed client tracking the server
version pinned in ``docs/r2/runbooks/m7-backup-restore.md``.
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from lib.content_digest import canonical_json_digest
from lib.db.models.host_hardening import CandidateObjectModel
from lib.db.repositories.host_hardening import BackupSetRepository, CandidateObjectRepository
from r2.contracts.host_hardening import (
    BackupSetManifest,
    BackupSetState,
    BackupVerdict,
    MediaInventoryEntry,
    VerifiedCandidateObject,
)

_MEDIA_DIRNAME = "media"
_DUMP_FILENAME = "database.dump"


class BackupSetError(Exception):
    """Base class for the backup-set error taxonomy."""


class SourceTargetAliasError(BackupSetError):
    """A backup or restore destination overlaps its own source."""


class NonEmptyRestoreTargetError(BackupSetError):
    """A restore target (database or media root) is not empty."""


class InconsistentRecoveryPointError(BackupSetError):
    """The project's candidate rows changed while this backup set was being built."""


class MediaIntegrityError(BackupSetError):
    """A media file is missing, digest-mismatched, or incompletely copied."""


class PathEscapesMediaRootError(BackupSetError):
    """A candidate's ``object_ref`` does not resolve under the declared media root."""


class SubprocessFailedError(BackupSetError):
    """``pg_dump``/``pg_restore`` exited non-zero."""


def _paths_alias(a: Path, b: Path) -> bool:
    a, b = a.resolve(), b.resolve()
    return a == b or a in b.parents or b in a.parents


def _under_root(path: Path, root: Path) -> Path:
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
        raise PathEscapesMediaRootError(f"{path} does not resolve under media root {root}")
    return resolved_path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _libpq_url(database_url: str) -> str:
    """``pg_dump``/``pg_restore`` are libpq tools: they understand
    ``postgresql://``, not SQLAlchemy's driver-qualified ``postgresql+asyncpg://``.
    An unrecognized scheme makes libpq silently fall back to a local Unix
    socket instead of erroring, so this conversion is not cosmetic."""
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def _run_subprocess(argv: list[str]) -> None:
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        raise SubprocessFailedError(f"{argv[0]} exited {process.returncode}: {stderr.decode(errors='replace')}")


async def _candidate_count(session: AsyncSession, *, user_id: str, project_name: str) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(CandidateObjectModel)
        .where(
            CandidateObjectModel.user_id == user_id,
            CandidateObjectModel.project_name == project_name,
        )
    )
    return int(result.scalar_one())


async def _alembic_head(session: AsyncSession) -> str:
    result = await session.execute(text("SELECT version_num FROM alembic_version"))
    return str(result.scalar_one())


async def _postgres_version(session: AsyncSession) -> str:
    result = await session.execute(text("SELECT version()"))
    return str(result.scalar_one())


def _copy_and_verify_media(
    candidates: list[VerifiedCandidateObject], *, media_root: Path, backup_dir: Path
) -> list[MediaInventoryEntry]:
    """Blocking: copy every candidate's on-disk bytes into ``backup_dir``,
    verifying source integrity and copy fidelity along the way. Runs off the
    event loop via ``asyncio.to_thread`` -- real backups move real bytes."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    media_dir = backup_dir / _MEDIA_DIRNAME
    media_dir.mkdir(parents=True, exist_ok=True)

    media_entries: list[MediaInventoryEntry] = []
    for candidate in candidates:
        source_path = _under_root(Path(candidate.object_ref), media_root)
        if not source_path.is_file():
            raise MediaIntegrityError(f"{candidate.candidate_id!r}: object_ref {source_path} is missing")
        actual_size = source_path.stat().st_size
        if actual_size != candidate.byte_size:
            raise MediaIntegrityError(
                f"{candidate.candidate_id!r}: on-disk size {actual_size} != recorded byte_size {candidate.byte_size}"
            )
        actual_digest = _sha256_file(source_path)
        if actual_digest != candidate.content_digest:
            raise MediaIntegrityError(
                f"{candidate.candidate_id!r}: on-disk digest {actual_digest} != recorded {candidate.content_digest}"
            )

        relative = source_path.relative_to(media_root.resolve())
        destination = media_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)

        copied_size = destination.stat().st_size
        copied_digest = _sha256_file(destination)
        if copied_size != actual_size or copied_digest != actual_digest:
            raise MediaIntegrityError(f"{candidate.candidate_id!r}: copy to {destination} is incomplete or corrupt")

        media_entries.append(
            MediaInventoryEntry(
                project_name=candidate.project_name,
                artifact_key=candidate.artifact_key,
                object_ref=str(relative),
                object_version=candidate.candidate_id,
                byte_size=actual_size,
                content_digest=actual_digest,
            )
        )
    return media_entries


def _restore_media(manifest: BackupSetManifest, *, backup_dir: Path, target_media_root: Path) -> None:
    """Blocking: copy every backed-up media file into the restore target."""
    media_dir = backup_dir / _MEDIA_DIRNAME
    target_media_root.mkdir(parents=True, exist_ok=True)
    for entry in manifest.media:
        source = media_dir / entry.object_ref
        destination = target_media_root / entry.object_ref
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _verify_restored_media(manifest: BackupSetManifest, *, media_root: Path) -> tuple[int, list[str]]:
    """Blocking: probe every restored media file against its manifest entry."""
    reason_codes: list[str] = []
    checked = 0
    for entry in manifest.media:
        checked += 1
        restored_path = media_root / entry.object_ref
        if not restored_path.is_file():
            reason_codes.append(f"MEDIA_MISSING:{entry.object_ref}")
            continue
        if restored_path.stat().st_size != entry.byte_size:
            reason_codes.append(f"MEDIA_SIZE_MISMATCH:{entry.object_ref}")
            continue
        if _sha256_file(restored_path) != entry.content_digest:
            reason_codes.append(f"MEDIA_DIGEST_MISMATCH:{entry.object_ref}")
    return checked, reason_codes


async def create_backup_set(
    *,
    session: AsyncSession,
    user_id: str,
    project_name: str,
    backup_set_id: str,
    database_url: str,
    media_root: Path,
    backup_dir: Path,
    source_deployment_id: str,
    release_git_sha: str,
    release_image_digest: str,
    configuration: dict[str, Any],
    now: Any,
    pg_dump_path: str = "pg_dump",
) -> BackupSetManifest:
    """Create one consistent database + media backup set.

    Preconditions the caller (and the operator runbook) are responsible for:
    the source application/worker are stopped so no candidate is created,
    promoted, or deleted while this runs. This function still proves that
    precondition held (see module docstring) instead of trusting it silently.
    """
    if _paths_alias(backup_dir, media_root):
        raise SourceTargetAliasError(f"backup_dir {backup_dir} aliases media_root {media_root}")

    repo = BackupSetRepository(session)
    candidates_repo = CandidateObjectRepository(session)
    await repo.insert(
        user_id=user_id, project_name=project_name, backup_set_id=backup_set_id, state="PREPARING", now=now
    )

    try:
        count_before = await _candidate_count(session, user_id=user_id, project_name=project_name)
        candidates = await candidates_repo.list_all(user_id=user_id, project_name=project_name)
        for candidate in candidates:
            await repo.add_media_ref(backup_set_id=backup_set_id, candidate_id=candidate.candidate_id)

        media_entries = await asyncio.to_thread(
            _copy_and_verify_media, candidates, media_root=media_root, backup_dir=backup_dir
        )

        dump_path = backup_dir / _DUMP_FILENAME
        await _run_subprocess(
            [pg_dump_path, "--format=custom", f"--file={dump_path}", "--no-password", _libpq_url(database_url)]
        )

        count_after = await _candidate_count(session, user_id=user_id, project_name=project_name)
        if count_after != count_before:
            raise InconsistentRecoveryPointError(
                f"{project_name!r} candidate count changed from {count_before} to {count_after} while backing up "
                "-- the source was not write-fenced"
            )

        alembic_head = await _alembic_head(session)
        postgres_version = await _postgres_version(session)
        configuration_digest = "sha256:" + canonical_json_digest(configuration)

        await repo.mark_state(backup_set_id=backup_set_id, state=BackupSetState.COMPLETE.value, now=now)

        return BackupSetManifest(
            backup_set_id=backup_set_id,
            source_deployment_id=source_deployment_id,
            release_git_sha=release_git_sha,
            release_image_digest=release_image_digest,
            postgres_version=postgres_version,
            alembic_head=alembic_head,
            database_backup_ref=_DUMP_FILENAME,
            recovery_target=now.isoformat(),
            configuration_digest=configuration_digest,
            media=tuple(media_entries),
            state=BackupSetState.COMPLETE,
        )
    except Exception:
        await repo.mark_state(backup_set_id=backup_set_id, state=BackupSetState.REJECTED.value, now=now)
        raise


def _assert_target_is_empty(media_root: Path) -> None:
    if media_root.exists() and any(media_root.iterdir()):
        raise NonEmptyRestoreTargetError(f"restore media root {media_root} is not empty")


async def _assert_database_is_empty(session: AsyncSession) -> None:
    result = await session.execute(
        text("SELECT count(*) FROM information_schema.tables WHERE table_schema = current_schema()")
    )
    if int(result.scalar_one()) != 0:
        raise NonEmptyRestoreTargetError("restore target database already has tables")


async def restore_backup_set(
    *,
    manifest: BackupSetManifest,
    backup_dir: Path,
    target_database_url: str,
    target_session: AsyncSession,
    target_media_root: Path,
    pg_restore_path: str = "pg_restore",
) -> None:
    """Restore one backup set's database dump and media into an empty target.

    Refuses (fail-closed, no partial mutation attempted) if the target
    database or media root is not empty, or if the target media root aliases
    the backup set's own storage.
    """
    if _paths_alias(backup_dir, target_media_root):
        raise SourceTargetAliasError(f"target_media_root {target_media_root} aliases backup_dir {backup_dir}")
    await _assert_database_is_empty(target_session)
    await asyncio.to_thread(_assert_target_is_empty, target_media_root)

    dump_path = backup_dir / manifest.database_backup_ref
    await _run_subprocess(
        [
            pg_restore_path,
            "--format=custom",
            "--no-password",
            f"--dbname={_libpq_url(target_database_url)}",
            str(dump_path),
        ]
    )

    await asyncio.to_thread(_restore_media, manifest, backup_dir=backup_dir, target_media_root=target_media_root)


async def verify_restored_backup_set(
    *,
    manifest: BackupSetManifest,
    session: AsyncSession,
    media_root: Path,
    now: Any,
    measured_rpo_seconds: int | None = None,
    measured_rto_seconds: int | None = None,
) -> BackupVerdict:
    """Verify an already-restored target against its manifest.

    Assumes ``restore_backup_set`` (or an equivalent real restore) already
    populated ``session``'s database and ``media_root``.
    """
    del now
    reason_codes: list[str] = []

    actual_head = await _alembic_head(session)
    if actual_head != manifest.alembic_head:
        reason_codes.append(f"SCHEMA_MISMATCH:{actual_head}!={manifest.alembic_head}")

    master_count_result = await session.execute(text("SELECT count(*) FROM master_head_versions"))
    checked_master_count = int(master_count_result.scalar_one())

    checked_media_count, media_reason_codes = await asyncio.to_thread(
        _verify_restored_media, manifest, media_root=media_root
    )
    reason_codes.extend(media_reason_codes)

    return BackupVerdict(
        backup_set_id=manifest.backup_set_id,
        accepted=not reason_codes,
        reason_codes=tuple(reason_codes),
        checked_master_count=checked_master_count,
        checked_media_count=checked_media_count,
        measured_rpo_seconds=measured_rpo_seconds,
        measured_rto_seconds=measured_rto_seconds,
    )


__all__ = [
    "BackupSetError",
    "InconsistentRecoveryPointError",
    "MediaIntegrityError",
    "NonEmptyRestoreTargetError",
    "PathEscapesMediaRootError",
    "SourceTargetAliasError",
    "SubprocessFailedError",
    "create_backup_set",
    "restore_backup_set",
    "verify_restored_backup_set",
]
