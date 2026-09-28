"""Portfolio admission controls (ADR-0094): pause a project's claiming and cap running tasks per project.

The controls are system settings read by the generation worker once per claim cycle, so a change
takes effect at the next cycle. Pausing never interrupts running tasks; cancel stays the task API.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db import get_async_session
from lib.project_admission import (
    ProjectAdmission,
    load_project_admission,
    set_project_ceiling,
    set_project_paused,
)
from lib.project_manager import get_project_manager

router = APIRouter()


class ProjectPauseRequest(BaseModel):
    paused: bool


class AdmissionCeilingRequest(BaseModel):
    max_running_per_project: int = Field(ge=0, description="0 removes the ceiling")


def _view(admission: ProjectAdmission) -> dict[str, object]:
    return {"paused": sorted(admission.paused), "max_running_per_project": admission.ceiling or 0}


@router.get("/admission")
async def get_admission(session: AsyncSession = Depends(get_async_session)) -> dict[str, object]:
    return _view(await load_project_admission(session))


@router.put("/projects/{project_name}/admission")
async def set_project_admission(
    project_name: str, req: ProjectPauseRequest, session: AsyncSession = Depends(get_async_session)
) -> dict[str, object]:
    if not get_project_manager().project_exists(project_name):
        raise HTTPException(status_code=404, detail=f"project {project_name!r} not found")
    admission = await set_project_paused(session, project_name, paused=req.paused)
    await session.commit()
    return {"project": project_name, "paused": project_name in admission.paused}


@router.put("/admission")
async def set_admission_ceiling(
    req: AdmissionCeilingRequest, session: AsyncSession = Depends(get_async_session)
) -> dict[str, object]:
    await set_project_ceiling(session, req.max_running_per_project)
    await session.commit()
    return _view(await load_project_admission(session))


__all__ = ["router"]
