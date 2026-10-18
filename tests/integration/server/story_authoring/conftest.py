"""Shared story-authoring fixtures: the sponsor's Showrunner grant and a real, migrated project."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.project_manager import ProjectManager
from server.services.governance_grants import CurrentShowrunnerGrantReader
from server.tool_runtime import CallerContext, CreateProjectToolRequest, Services, ToolRequest, create_project
from tests.integration.server.routers.spatial_approval_support import showrunner_grants
from tests.integration.server.story_authoring.test_narrative import IDENTITY

SPONSOR = "sponsor"


class _Unused:
    pass


@pytest.fixture
async def grants(concurrent_session_factory: async_sessionmaker[AsyncSession]) -> CurrentShowrunnerGrantReader:
    """One signed grant import per test: a second import in another second would be a different event."""
    return await showrunner_grants(
        concurrent_session_factory, user_id=IDENTITY.user_id, project_name=IDENTITY.project_name, principal=SPONSOR
    )


@pytest.fixture
async def projects(tmp_path: Path) -> ProjectManager:
    """A real, migrated narration project, as hand-off needs one."""
    manager = ProjectManager(tmp_path / "projects")
    services = Services(projects=manager, workflow_planner=_Unused(), capabilities=_Unused())
    request = CreateProjectToolRequest(
        name=IDENTITY.project_name, title="Truyện", content_mode="narration", generation_mode="storyboard"
    )
    caller = CallerContext(user_id=IDENTITY.user_id, source="embedded")
    created = await create_project(ToolRequest(request), caller, services)
    assert created.problem is None
    return manager
