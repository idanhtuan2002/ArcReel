"""Portfolio admission controls: project pause and per-project running ceiling (ADR-0094).

They are operator runtime configuration held in the system settings store, like the provider pool
limits, and enforced as filters when the worker claims queued tasks. No run state is stored.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from lib.config.service import ConfigService

logger = logging.getLogger(__name__)

PAUSED_PROJECTS_SETTING = "project_admission.paused"
PROJECT_CEILING_SETTING = "project_admission.max_running_per_project"


@dataclass(frozen=True)
class ProjectAdmission:
    paused: frozenset[str] = frozenset()
    #: Running tasks per project and media lane; ``None`` means unlimited.
    ceiling: int | None = None


def parse_project_admission(settings: Mapping[str, str]) -> ProjectAdmission:
    """Read the two settings; a malformed value is logged and ignored rather than stopping the worker."""
    paused: frozenset[str] = frozenset()
    raw_paused = settings.get(PAUSED_PROJECTS_SETTING, "")
    if raw_paused:
        try:
            value = json.loads(raw_paused)
            if not isinstance(value, list) or not all(isinstance(name, str) for name in value):
                raise ValueError("not a JSON array of project names")
            paused = frozenset(value)
        except ValueError:
            logger.warning("ignoring malformed setting %s=%r", PAUSED_PROJECTS_SETTING, raw_paused)
    ceiling: int | None = None
    raw_ceiling = settings.get(PROJECT_CEILING_SETTING, "").strip()
    if raw_ceiling:
        try:
            ceiling = int(raw_ceiling)
        except ValueError:
            logger.warning("ignoring malformed setting %s=%r", PROJECT_CEILING_SETTING, raw_ceiling)
        else:
            if ceiling < 0:
                logger.warning("ignoring negative setting %s=%r", PROJECT_CEILING_SETTING, raw_ceiling)
                ceiling = None
            elif ceiling == 0:
                ceiling = None
    return ProjectAdmission(paused=paused, ceiling=ceiling)


async def load_project_admission(session: AsyncSession) -> ProjectAdmission:
    return parse_project_admission(await ConfigService(session).get_all_settings())


async def set_project_paused(session: AsyncSession, project_name: str, *, paused: bool) -> ProjectAdmission:
    """Pause or resume one project's claiming; running tasks are not interrupted."""
    service = ConfigService(session)
    current = parse_project_admission(await service.get_all_settings())
    names = set(current.paused)
    if paused:
        names.add(project_name)
    else:
        names.discard(project_name)
    await service.set_setting(PAUSED_PROJECTS_SETTING, json.dumps(sorted(names)))
    return ProjectAdmission(paused=frozenset(names), ceiling=current.ceiling)


async def set_project_ceiling(session: AsyncSession, ceiling: int | None) -> None:
    """Set the per-project running ceiling; ``None`` or ``0`` removes it."""
    if ceiling is not None and ceiling < 0:
        raise ValueError("the per-project running ceiling cannot be negative")
    await ConfigService(session).set_setting(PROJECT_CEILING_SETTING, str(ceiling or 0))


__all__ = [
    "PAUSED_PROJECTS_SETTING",
    "PROJECT_CEILING_SETTING",
    "ProjectAdmission",
    "load_project_admission",
    "parse_project_admission",
    "set_project_ceiling",
    "set_project_paused",
]
