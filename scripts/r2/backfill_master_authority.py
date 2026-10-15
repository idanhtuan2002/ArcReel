"""Promote existing file masters into the database master authority (ADR-0096).

A project approved before the database head became the authority has file masters only, and
master-consuming routes refuse it as diverged. This command registers each file master's
selected host version as a candidate object and promotes it, with the deterministic command
``backfill:<artifact_key>:<candidate>``, so a rerun replays instead of writing again.

    --user-id <id> --project <name>     one project
    --user-id <id> --all                every project

It prints a JSON summary per project: promoted, already current and diverged artifacts, and
unreadable projects. An artifact is diverged, and gets no master head, when any of these holds:

- its R2 metadata does not validate;
- its database head has no manifest projection;
- its projection is gone when it is read again under the row lock;
- its database head names another candidate;
- its selected host version has no recorded output digest, or its file is gone or no longer hashes
  to it (checked again on every rerun);
- another writer moves its head first.

A project whose path or manifest cannot be read is reported unreadable, and the run continues. The
complete outcome model is in docs/r2/evidence/R2_V2_02D_BACKFILL_SERIALIZATION_2026-09-29.md.

The exit status is 3 when ``ffprobe`` is missing at the start or lost during the run, 2 when any
artifact is diverged or any project unreadable, and 0 otherwise. A database failure aborts the run.

Each artifact is decided and promoted in one transaction that holds its master authority row lock
(``serialized_artifact``, the V2-02b rule), so a concurrent Gate C approval is never overwritten.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import shutil
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from lib.artifact_manifest import ArtifactKey, ArtifactKind, decode_artifact_key_parts
from lib.candidate_store import CandidateStoreError
from lib.content_digest import sha256_file
from lib.db import async_session_factory
from lib.db.repositories.host_hardening import (
    CandidateIdentityConflictError,
    CandidateObjectRepository,
    MasterAuthorityRepository,
    MasterHeadConflictError,
)
from lib.project_manager import get_project_manager
from r2.host_hardening.master_authority import CandidateObjectConflictError, resolve_m7_candidate_id
from r2.host_hardening.promotion import PromotionExpectedVersionConflictError, PromotionReceiptReplayMismatchError
from r2.m3.host_integration import GoldenAHostIntegration
from server.services.master_authority import master_authority_unit, scan_master_records, serialized_artifact

logger = logging.getLogger(__name__)


class MissingMediaProbeError(RuntimeError):
    """``ffprobe`` is not installed; candidate registration cannot verify any master."""


def _require_media_probe() -> None:
    if shutil.which("ffprobe") is None:
        raise MissingMediaProbeError("ffprobe is required to verify masters and was not found on PATH")


class _UnverifiableVersionError(Exception):
    """The selected version's file failed while the candidate was being registered."""


_DIVERGENT_PROMOTION = (
    CandidateStoreError,
    _UnverifiableVersionError,
    CandidateObjectConflictError,
    CandidateIdentityConflictError,
    MasterHeadConflictError,
    PromotionExpectedVersionConflictError,
    PromotionReceiptReplayMismatchError,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user-id", required=True)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--project")
    target.add_argument("--all", action="store_true")
    return parser


def _empty_summary() -> dict[str, list[str]]:
    return {"promoted": [], "current": [], "diverged": [], "unreadable": []}


def _is_episode_video(artifact_key: str) -> bool:
    return (
        decode_artifact_key_parts(artifact_key) is not None
        and ArtifactKey.decode(artifact_key).kind is ArtifactKind.EPISODE_VIDEO
    )


async def backfill_project(*, user_id: str, project_name: str, project_dir: Path) -> dict[str, list[str]]:
    _require_media_probe()
    summary = _empty_summary()
    try:
        records, invalid = await asyncio.to_thread(scan_master_records, project_dir)
        root = await asyncio.to_thread(Path(project_dir).resolve)
    except Exception as error:
        # Reading the manifest touches only project files; any failure makes this project unreadable.
        logger.warning("backfill: the manifest of %s is not readable: %r", project_name, error)
        summary["unreadable"].append(f"{type(error).__name__}: {error}")
        return summary
    async with async_session_factory() as session:
        database_keys = await MasterAuthorityRepository(session).list_current_keys(
            user_id=user_id, project_name=project_name
        )
    for artifact_key in invalid:
        logger.warning("backfill: %s has R2 metadata that does not validate", artifact_key)
        summary["diverged"].append(artifact_key)
    for artifact_key in database_keys:
        if _is_episode_video(artifact_key) and artifact_key not in records and artifact_key not in invalid:
            logger.warning("backfill: %s has a database head but no manifest projection", artifact_key)
            summary["diverged"].append(artifact_key)
    for artifact_key in sorted(records):
        try:
            async with serialized_artifact(
                async_session_factory, user_id=user_id, project_name=project_name, artifact_key=artifact_key
            ) as session:
                outcome = await _backfill_locked(
                    session, user_id=user_id, project_name=project_name, root=root, artifact_key=artifact_key
                )
        except _DIVERGENT_PROMOTION:
            # A registration probe that failed because ffprobe disappeared is a tool failure.
            _require_media_probe()
            outcome = "diverged"
        summary[outcome].append(artifact_key)
    summary["diverged"].sort()
    return summary


def _verified_staged_version(project_dir: Path, key: ArtifactKey, host_version_ref: str) -> tuple[Path, str] | None:
    """The selected host version file and its recorded digest, or ``None`` when it cannot be verified.

    This reads only the project's version metadata and files, never the database. Any failure here
    (a missing or malformed record, no recorded digest, an unmanaged or escaping path, an unreadable
    file or different bytes) means the selected version is not verifiable, so the artifact is
    diverged; the failure is logged.
    """
    try:
        host = GoldenAHostIntegration(project_dir, resource_type="videos", episode=int(key.components[0]))
        version_file, staged_digest = host.staged_version(str(key.components[1]), host_version_ref)
        if "sha256:" + sha256_file(version_file) != staged_digest:
            logger.warning("backfill: %s version %s no longer hashes to its recorded digest", key, host_version_ref)
            return None
    except Exception as error:
        logger.warning("backfill: %s version %s is not verifiable: %r", key, host_version_ref, error)
        return None
    return version_file, staged_digest


async def _backfill_locked(
    session: AsyncSession,
    *,
    user_id: str,
    project_name: str,
    root: Path,
    artifact_key: str,
) -> str:
    """Decide and stage one artifact under its authority row lock; the caller's transaction commits.

    The manifest is read again under the lock (Gate C writes its projection under the same lock), so
    a projection removed or changed after the project scan is never promoted from the stale scan.
    """
    try:
        records, _ = await asyncio.to_thread(scan_master_records, root)
    except Exception as error:
        logger.warning("backfill: the manifest was not readable under the lock of %s: %r", artifact_key, error)
        return "diverged"
    record = records.get(artifact_key)
    if record is None:
        logger.warning("backfill: the projection of %s changed before its lock", artifact_key)
        return "diverged"
    key = ArtifactKey.decode(artifact_key)
    expected = await resolve_m7_candidate_id(
        CandidateObjectRepository(session),
        user_id=user_id,
        project_name=project_name,
        artifact_key=artifact_key,
        generation_candidate_id=record.selected_candidate_id,
    )
    head = await MasterAuthorityRepository(session).get_current(
        user_id=user_id, project_name=project_name, artifact_key=artifact_key
    )
    if head is not None and head.candidate_id != expected:
        return "diverged"
    staged = await asyncio.to_thread(_verified_staged_version, root, key, record.host_version_ref)
    if staged is None:
        return "diverged"
    version_file, staged_digest = staged
    if head is not None:
        return "current" if head.content_digest == staged_digest else "diverged"
    try:
        await master_authority_unit(session, defer_commit=True).promote_staged(
            user_id=user_id,
            project_name=project_name,
            project_dir=root,
            artifact_key=artifact_key,
            generation_candidate_id=record.selected_candidate_id,
            version_file=version_file,
            expected_content_digest=staged_digest,
            approval_record=record.approval_record,
            command_id=f"backfill:{artifact_key}:{record.selected_candidate_id}",
        )
    except OSError as error:
        # The file changed or vanished after the check; raising rolls the transaction back.
        raise _UnverifiableVersionError(str(error)) from error
    return "promoted"


async def _run(args: argparse.Namespace) -> dict[str, dict[str, list[str]]]:
    manager = get_project_manager()
    names = manager.list_projects() if args.all else [args.project]
    results: dict[str, dict[str, list[str]]] = {}
    for name in names:
        try:
            project_dir = await asyncio.to_thread(manager.get_project_path, name)
        except Exception as error:
            logger.warning("backfill: project %s is not readable: %r", name, error)
            results[name] = _empty_summary()
            results[name]["unreadable"].append(f"{type(error).__name__}: {error}")
            continue
        results[name] = await backfill_project(user_id=args.user_id, project_name=name, project_dir=project_dir)
    return results


async def main_async(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        _require_media_probe()
        result = await _run(args)
    except MissingMediaProbeError as error:
        print(f"backfill: {error}", file=sys.stderr)
        return 3
    print(json.dumps(result, indent=2))
    return 2 if any(summary["diverged"] or summary["unreadable"] for summary in result.values()) else 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(main_async(argv))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
