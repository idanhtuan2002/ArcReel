"""Build a format projection plan from the current master of a source artifact (M8-E E3).

The client names the source artifact, the stored profile and overlay refs, the reframe kind and the
source evidence (focal span, subject span, caption spans). The server resolves the current master
head, verifies its bytes, reads its size, and builds the plan against exactly that master; the
client never supplies a digest or a size.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.formats import FormatProfileModel, OverlayConstraintSetModel
from lib.db.repositories.formats import FormatRepository
from lib.db.repositories.host_hardening import MasterAuthorityRepository
from r2.advanced_creative.errors import FormatConflictError, FormatNotFoundError
from r2.advanced_creative.formats import (
    Box,
    FormatInvalidError,
    ReframeKind,
    build_plan,
    reframe_decision,
    source_master_id,
)
from r2.contracts.advanced_creative import FormatProjectionPlan, OutputProfile, OverlayConstraintSet
from server.services.format_render import file_digest, probe_source


async def master_source(
    session: AsyncSession, *, user_id: str, project_name: str, project_dir: Path, artifact_key: str
):
    """The current master head of ``artifact_key`` and its verified file inside the project."""
    master = await MasterAuthorityRepository(session).get_current(
        user_id=user_id, project_name=project_name, artifact_key=artifact_key
    )
    if master is None:
        raise FormatNotFoundError("the source artifact has no approved master")
    path = await asyncio.to_thread(_verified_master_file, master.object_ref, master.content_digest, project_dir)
    return master, path


def _verified_master_file(object_ref: str, content_digest: str, project_dir: Path) -> Path:
    path = Path(object_ref).resolve()
    if not path.is_relative_to(project_dir.resolve()):
        raise FormatInvalidError("the master file lives outside the project")
    if not path.is_file() or file_digest(path) != content_digest:
        raise FormatConflictError("the master file is missing or changed")
    return path


async def plan_from_master(
    session: AsyncSession,
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
    master, path = await master_source(
        session, user_id=user_id, project_name=project_name, project_dir=project_dir, artifact_key=source_artifact_key
    )
    profile_row = await session.get(FormatProfileModel, (user_id, project_name, profile_ref))
    overlay_row = await session.get(OverlayConstraintSetModel, (user_id, project_name, constraint_ref))
    if profile_row is None or overlay_row is None:
        raise FormatNotFoundError("unknown profile or overlay set")
    profile = OutputProfile.model_validate(profile_row.profile_json)
    overlay = OverlayConstraintSet.model_validate(overlay_row.overlay_json)
    facts = await probe_source(path)
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


__all__ = ["master_source", "plan_from_master"]
