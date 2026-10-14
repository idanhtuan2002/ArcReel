"""Build a format projection plan from the current master of a source artifact (M8-E E3).

The client names the source artifact, the stored profile and overlay refs, the reframe kind and the
source evidence (focal span, subject span, caption spans). The server resolves the current master
head, measures a verified snapshot of its bytes outside any transaction, then builds and stores the
plan in a short transaction that first re-reads the head: a master that moved meanwhile is refused.
The client never supplies a digest or a size.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.formats import FormatProfileModel, OverlayConstraintSetModel
from lib.db.repositories.formats import FormatRepository
from lib.db.repositories.host_hardening import MasterAuthorityRepository
from r2.advanced_creative.errors import FormatConflictError, FormatMediaMissingError, FormatNotFoundError
from r2.advanced_creative.formats import (
    Box,
    FormatInvalidError,
    ReframeKind,
    build_plan,
    reframe_decision,
    source_master_id,
)
from r2.contracts.advanced_creative import FormatProjectionPlan, OutputProfile, OverlayConstraintSet
from r2.contracts.host_hardening import MasterHeadSnapshot
from server.services.format_render import probe_source, snapshot_dir, verified_snapshot


async def current_master(
    sessions: async_sessionmaker[AsyncSession], *, user_id: str, project_name: str, artifact_key: str
) -> MasterHeadSnapshot:
    async with sessions() as session:
        master = await MasterAuthorityRepository(session).get_current(
            user_id=user_id, project_name=project_name, artifact_key=artifact_key
        )
    if master is None:
        raise FormatNotFoundError("the source artifact has no approved master")
    return master


def master_path(master: MasterHeadSnapshot, project_dir: Path) -> Path:
    """The master's file inside the project; its bytes are verified by whoever snapshots it."""
    path = Path(master.object_ref).resolve()
    if not path.is_relative_to(project_dir.resolve()):
        raise FormatInvalidError("the master file lives outside the project")
    if not path.is_file():
        raise FormatMediaMissingError("the master file is missing")
    return path


async def plan_from_master(
    sessions: async_sessionmaker[AsyncSession],
    *,
    user_id: str,
    project_name: str,
    project_dir: Path,
    plan_id: str,
    source_artifact_key: str,
    profile_ref: str,
    constraint_ref: str,
    kind: ReframeKind,
    focal: Box | None,
    subject: Box | None,
    captions: tuple[Box, ...],
    rationale: str,
) -> FormatProjectionPlan:
    master = await current_master(
        sessions, user_id=user_id, project_name=project_name, artifact_key=source_artifact_key
    )
    path = await asyncio.to_thread(master_path, master, project_dir)
    async with verified_snapshot(path, master.content_digest, snapshot_dir(project_dir)) as snapshot:
        facts = await probe_source(snapshot)

    async with sessions() as session, session.begin():
        head = await MasterAuthorityRepository(session).get_current(
            user_id=user_id, project_name=project_name, artifact_key=source_artifact_key
        )
        if head != master:
            raise FormatConflictError("the source master moved while it was measured; plan again")
        profile_row = await session.get(FormatProfileModel, (user_id, project_name, profile_ref))
        overlay_row = await session.get(OverlayConstraintSetModel, (user_id, project_name, constraint_ref))
        if profile_row is None or overlay_row is None:
            raise FormatNotFoundError("unknown profile or overlay set")
        profile = OutputProfile.model_validate(profile_row.profile_json)
        overlay = OverlayConstraintSet.model_validate(overlay_row.overlay_json)
        decision = reframe_decision(
            decision_id=f"{plan_id}:reframe",
            kind=kind,
            source_size=(facts.width, facts.height),
            profile=profile,
            focal=focal,
            subject=subject,
            captions=captions,
            rationale=rationale,
        )
        plan = build_plan(
            plan_id=plan_id,
            source_master_id=source_master_id(source_artifact_key, master.master_version),
            source_master_digest=master.content_digest,
            profile=profile,
            overlay=overlay,
            decisions=(decision,),
        )
        return await FormatRepository(session).create_plan(user_id=user_id, project_name=project_name, plan=plan)


__all__ = ["current_master", "master_path", "plan_from_master"]
