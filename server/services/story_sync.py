"""ADR-0122: a film project imports the story text of the story project it adapts."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from lib.config.resolver import ConfigResolver
from lib.db import async_session_factory
from lib.episode_ledger import discover_sources, normalize_source_text
from lib.project_kinds import linked_story
from lib.project_manager import ProjectManager
from server.services import workflow_planner
from server.tool_runtime import (
    CallerContext,
    ProjectScope,
    Services,
    ToolRequest,
    UploadSourceRequest,
    upload_source,
)


class StorySyncRefused(Exception):
    def __init__(self, code: str, detail: str, status: int) -> None:
        super().__init__(code)
        self.code, self.detail, self.status = code, detail, status


@dataclass
class StorySyncResult:
    story_project: str
    imported: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)


async def sync_linked_story(projects: ProjectManager, project_name: str, *, user_id: str) -> StorySyncResult:
    """Files the film does not hold yet are added to its sources; files it holds with the same text are skipped; a
    file it holds with other text is never overwritten and is reported, because episodes may already be planned
    from it."""
    try:
        film = await asyncio.to_thread(projects.load_project, project_name)
    except FileNotFoundError:
        raise StorySyncRefused("PROJECT_NOT_FOUND", project_name, 404) from None
    story = linked_story(film)
    if story is None:
        raise StorySyncRefused("NO_STORY_LINK", "the project adapts no story", 409)
    try:
        story_dir = projects.get_project_path(story)
    except (FileNotFoundError, ValueError):
        raise StorySyncRefused("STORY_PROJECT_MISSING", story, 409) from None
    docs = await asyncio.to_thread(discover_sources, story_dir)
    source_dir = projects.get_project_path(project_name) / "source"
    scope = ProjectScope(project_name=project_name, projects_root=projects.projects_root)
    services = Services(
        projects=projects,
        workflow_planner=workflow_planner.get_workflow_planner(projects),
        capabilities=ConfigResolver(async_session_factory),
    )
    result = StorySyncResult(story_project=story)
    for doc in docs:
        # A source is stored as ``<stem>.txt`` whatever its upload suffix; compare against what an upload writes.
        filename = Path(doc.rel_path).stem + ".txt"
        target = source_dir / filename
        if target.exists():
            held = await asyncio.to_thread(target.read_text, encoding="utf-8")
            (result.skipped if normalize_source_text(held) == doc.text else result.conflicts).append(filename)
            continue
        outcome = await upload_source(
            ToolRequest(UploadSourceRequest(filename=filename, content=doc.text, on_conflict="fail")),
            scope,
            CallerContext(user_id=user_id, source="embedded"),
            services,
        )
        (result.conflicts if outcome.problem is not None else result.imported).append(filename)
    return result


__all__ = ["StorySyncRefused", "StorySyncResult", "sync_linked_story"]
