"""ADR-0124 §6: one film project per finished story project, in creation order, each on autopilot.

A story is finished when its book has every part handed off, or, without a book, when it has story text. A story
that a film already adapts is skipped, so running the batch again resumes where it stopped. Each new film copies
its production settings from a template film project the Showrunner names, adapts the story (its text is synced
in) and has its autopilot turned on by the same interactive Showrunner.
"""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from lib.episode_ledger import discover_sources
from lib.project_kinds import KIND_FIELD, STORY_LINK_FIELD, linked_story, project_kind
from lib.project_manager import ProjectManager
from lib.style_templates import resolve_template_prompt
from server.story_authoring.film_looks import film_look
from server.story_authoring.idea_profile import PROFILE_SETTING

#: What a new film takes from its template: how it is made, never what it is about.
TEMPLATE_FIELDS = (
    "generation_mode",
    "grid_storyboard",
    "model_settings",
    "automation",
    "speech_rate_units_per_second",
    "video_backend",
    "video_provider_i2v",
    "video_provider_r2v",
    "image_provider_t2i",
    "image_provider_i2i",
    "default_image_backend",
    "text_backend_simple",
    "text_backend_complex",
    "default_text_backend",
)


class BatchRefused(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class BatchResult:
    created: list[dict[str, str]] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)


def _created_at(project: dict[str, Any]) -> str:
    metadata = project.get("metadata")
    value = metadata.get("created_at") if isinstance(metadata, dict) else None
    return value if isinstance(value, str) else ""


async def films_for_finished_stories(
    projects: ProjectManager,
    *,
    template_project: str,
    limit: int,
    book_parts: Callable[[str], Awaitable[tuple[int, int] | None]],
    sync_story: Callable[[str], Awaitable[list[str]]],
    enable_autopilot: Callable[[str, str], Awaitable[None]],
) -> BatchResult:
    """``enable_autopilot(film, story)`` turns the new film's autopilot on as the interactive Showrunner."""
    try:
        template = await asyncio.to_thread(projects.load_project, template_project)
    except FileNotFoundError:
        raise BatchRefused("TEMPLATE_NOT_FOUND") from None
    if project_kind(template) != "film":
        raise BatchRefused("TEMPLATE_NOT_A_FILM")

    loaded: list[tuple[str, dict[str, Any]]] = []
    for name in await asyncio.to_thread(projects.list_projects):
        try:
            loaded.append((name, await asyncio.to_thread(projects.load_project, name)))
        except (FileNotFoundError, ValueError):
            continue
    adapted = {story for _name, project in loaded if (story := linked_story(project)) is not None}
    stories = sorted(
        ((name, project) for name, project in loaded if project_kind(project) == "story" and name not in adapted),
        key=lambda item: (_created_at(item[1]), item[0]),
    )

    result = BatchResult()
    for name, story in stories:
        if len(result.created) >= limit:
            break
        parts = await book_parts(name)
        if parts is not None:
            finished = parts[0] >= parts[1]
        else:
            finished = bool(await asyncio.to_thread(discover_sources, projects.get_project_path(name)))
        if not finished:
            result.skipped.append({"story": name, "reason": "STORY_NOT_FINISHED"})
            continue
        film = await asyncio.to_thread(_create_film, projects, name, story, template)
        conflicts = await sync_story(film)
        if conflicts:
            result.skipped.append({"story": name, "film": film, "reason": "STORY_SYNC_CONFLICT"})
            continue
        try:
            await enable_autopilot(film, name)
        except Exception as error:
            result.skipped.append({"story": name, "film": film, "reason": f"AUTOPILOT_NOT_ENABLED:{error}"})
            continue
        result.created.append({"story": name, "film": film})
    return result


def _create_film(projects: ProjectManager, story_name: str, story: dict[str, Any], template: dict[str, Any]) -> str:
    """The film takes how it is made from the template; its look follows the story's drawn genre when there is one
    (ADR-0125 §6), else the template's."""
    title = f"{story.get('title') or story_name} · Phim"
    name = projects.generate_project_name(title)
    content_mode = template.get("content_mode") or "narration"
    projects.create_project(name, content_mode=content_mode)
    extras = {key: copy.deepcopy(template[key]) for key in TEMPLATE_FIELDS if template.get(key) is not None}
    extras.pop(KIND_FIELD, None)
    extras[STORY_LINK_FIELD] = story_name
    profile = story.get(PROFILE_SETTING)
    look = film_look(profile.get("genre_pack") if isinstance(profile, dict) else None)
    if look is not None:
        style, style_template_id = resolve_template_prompt(look.style_template_id), look.style_template_id
        aspect_ratio, episode_duration = look.aspect_ratio, look.episode_target_duration
    else:
        style, style_template_id = template.get("style") or "", template.get("style_template_id")
        aspect_ratio = template.get("aspect_ratio") or "9:16"
        episode_duration = template.get("episode_target_duration")
    projects.create_project_metadata(
        name,
        title,
        style,
        content_mode,
        aspect_ratio=aspect_ratio,
        default_duration=template.get("default_duration"),
        episode_target_duration=episode_duration,
        style_template_id=style_template_id,
        extras=extras,
    )
    return name


def adopt_automation_settings(projects: ProjectManager, project_name: str) -> str | None:
    """Give a project without automatic production settings those of the most recently changed project of the same
    content mode that has them; returns that project's name, or ``None`` when the project already has its own."""
    project = projects.load_project(project_name)
    if isinstance(project.get("automation"), dict):
        return None
    candidates: list[tuple[float, str, dict[str, Any]]] = []
    for name in projects.list_projects():
        if name == project_name:
            continue
        try:
            other = projects.load_project(name)
            changed = (projects.get_project_path(name) / "project.json").stat().st_mtime
        except (FileNotFoundError, ValueError, OSError):
            continue
        settings = other.get("automation")
        if isinstance(settings, dict) and other.get("content_mode", "narration") == project.get(
            "content_mode", "narration"
        ):
            candidates.append((changed, name, settings))
    if not candidates:
        raise BatchRefused("AUTOPILOT_NO_SETTINGS_TEMPLATE")
    _changed, template, settings = max(candidates, key=lambda item: (item[0], item[1]))
    projects.update_project(project_name, lambda current: current.update(automation=copy.deepcopy(settings)))
    return template


__all__ = ["TEMPLATE_FIELDS", "BatchRefused", "BatchResult", "adopt_automation_settings", "films_for_finished_stories"]
