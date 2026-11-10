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


def test_a_project_without_settings_adopts_the_latest_configured_ones(tmp_path):
    import os

    from server.production_run.autopilot_batch import adopt_automation_settings

    pm = ProjectManager(tmp_path)
    _project(pm, "old", extras={"automation": {"routes": [], "tag": "old"}}, created="2026-01-01T00:00:00")
    _project(pm, "new", extras={"automation": {"routes": [], "tag": "new"}}, created="2026-01-02T00:00:00")
    _project(pm, "fresh", extras={"project_kind": "story"}, created="2026-01-03T00:00:00")
    os.utime(pm.get_project_path("old") / "project.json", (1, 1))
    assert adopt_automation_settings(pm, "fresh") == "new"
    assert pm.load_project("fresh")["automation"]["tag"] == "new"
    # A project that has its own settings keeps them.
    assert adopt_automation_settings(pm, "fresh") is None

    lonely = ProjectManager(tmp_path / "other")
    _project(lonely, "alone", extras={}, created="2026-01-01T00:00:00")
    with pytest.raises(BatchRefused, match="AUTOPILOT_NO_SETTINGS_TEMPLATE"):
        adopt_automation_settings(lonely, "alone")


async def test_a_film_of_a_story_with_a_drawn_genre_takes_that_genres_look(tmp_path):
    from lib.style_templates import resolve_template_prompt
    from server.story_authoring.film_looks import LOOKS, film_look

    pm = ProjectManager(tmp_path)
    _project(pm, "tpl", extras={"automation": {"routes": []}}, created="2026-01-01T00:00:00")
    pm.update_project("tpl", lambda p: p.update(style_template_id="anim_ghibli", episode_target_duration=300))
    drawn = {"project_kind": "story", "story_profile": {"genre_pack": "horror", "idea": "x"}}
    _project(pm, "drawn", extras=drawn, created="2026-02-01T00:00:00", text="Hết.")
    _project(pm, "given", extras={"project_kind": "story"}, created="2026-03-01T00:00:00", text="Hết.")

    result, _enabled = await _run(pm)
    films = {entry["story"]: pm.load_project(entry["film"]) for entry in result.created}
    horror = films["drawn"]
    assert (horror["style_template_id"], horror["aspect_ratio"], horror["episode_target_duration"]) == (
        "live_lynch",
        "9:16",
        90,
    )
    assert horror["style"] == resolve_template_prompt("live_lynch")
    assert (films["given"]["style_template_id"], films["given"]["episode_target_duration"]) == ("anim_ghibli", 300)
    assert all(film_look(pack) is not None for pack in LOOKS)
    assert film_look("cyberpunk") is None
