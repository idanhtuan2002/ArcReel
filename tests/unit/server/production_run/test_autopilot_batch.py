"""One film per finished story, in creation order, copying how films are made from a template (ADR-0124 §6)."""

from __future__ import annotations

import pytest

from lib.project_manager import ProjectManager
from server.production_run.autopilot_batch import BatchRefused, films_for_finished_stories


def _project(pm: ProjectManager, name: str, *, extras: dict, created: str, text: str | None = None) -> None:
    pm.create_project(name, content_mode="narration")
    pm.create_project_metadata(name, name.title(), "", "narration", extras={"generation_mode": "storyboard", **extras})
    pm.update_project(name, lambda project: project["metadata"].update(created_at=created))
    if text is not None:
        (pm.get_project_path(name) / "source").mkdir(exist_ok=True)
        (pm.get_project_path(name) / "source" / "part-1.txt").write_text(text, encoding="utf-8")


async def _run(pm: ProjectManager, *, template: str = "tpl", books=None, conflicts=(), limit: int = 10):
    enabled: list[tuple[str, str]] = []

    async def book_parts(story: str):
        return (books or {}).get(story)

    async def sync_story(film: str):
        return list(conflicts)

    async def enable(film: str, story: str):
        enabled.append((film, story))

    result = await films_for_finished_stories(
        pm,
        template_project=template,
        limit=limit,
        book_parts=book_parts,
        sync_story=sync_story,
        enable_autopilot=enable,
    )
    return result, enabled


async def test_finished_stories_get_one_film_each_in_creation_order(tmp_path):
    pm = ProjectManager(tmp_path)
    automation = {"routes": [], "max_target_episodes": 2}
    _project(pm, "tpl", extras={"automation": automation, "grid_storyboard": True}, created="2026-01-01T00:00:00")
    _project(pm, "later", extras={"project_kind": "story"}, created="2026-03-01T00:00:00", text="Hết.")
    _project(pm, "earlier", extras={"project_kind": "story"}, created="2026-02-01T00:00:00", text="Hết.")
    _project(pm, "half-book", extras={"project_kind": "story"}, created="2026-02-15T00:00:00", text="Phần 1.")
    _project(pm, "no-text", extras={"project_kind": "story"}, created="2026-02-20T00:00:00")
    _project(pm, "adapted", extras={"project_kind": "story"}, created="2026-01-15T00:00:00", text="Hết.")
    _project(pm, "adapted-film", extras={"story_project": "adapted"}, created="2026-01-16T00:00:00")

    result, enabled = await _run(pm, books={"half-book": (1, 3)})
    assert [entry["story"] for entry in result.created] == ["earlier", "later"]
    assert [story for _film, story in enabled] == ["earlier", "later"]
    assert {entry["story"]: entry["reason"] for entry in result.skipped} == {
        "half-book": "STORY_NOT_FINISHED",
        "no-text": "STORY_NOT_FINISHED",
    }
    film = pm.load_project(result.created[0]["film"])
    assert (film["story_project"], film["automation"], film["grid_storyboard"]) == ("earlier", automation, True)
    assert "project_kind" not in film

    # A second batch finds nothing new to adapt.
    again, _ = await _run(pm, books={"half-book": (1, 3)})
    assert again.created == []


async def test_limit_conflicts_and_template_checks(tmp_path):
    pm = ProjectManager(tmp_path)
    _project(pm, "tpl", extras={}, created="2026-01-01T00:00:00")
    _project(pm, "one", extras={"project_kind": "story"}, created="2026-02-01T00:00:00", text="Hết.")
    _project(pm, "two", extras={"project_kind": "story"}, created="2026-03-01T00:00:00", text="Hết.")
    result, enabled = await _run(pm, conflicts=("part-1.txt",))
    assert result.created == []
    assert enabled == []
    assert {entry["reason"] for entry in result.skipped} == {"STORY_SYNC_CONFLICT"}
    with pytest.raises(BatchRefused, match="TEMPLATE_NOT_A_FILM"):
        await _run(pm, template="two")
    with pytest.raises(BatchRefused, match="TEMPLATE_NOT_FOUND"):
        await _run(pm, template="missing")
