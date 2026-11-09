"""Story projects and film projects (ADR-0122).

A story project holds a story as a product in its own right: written by story runs, imported, continued, varied or
translated, and publishable on its own. A film project makes a film; it may name the story project it adapts
(``story_project``), whose story text it imports into its own sources. A project without a kind is a film project,
so every project made before this decision keeps working as it did.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

type ProjectKind = Literal["story", "film"]

KIND_FIELD = "project_kind"
STORY_LINK_FIELD = "story_project"


def project_kind(project: Mapping[str, Any] | None) -> ProjectKind:
    return "story" if isinstance(project, Mapping) and project.get(KIND_FIELD) == "story" else "film"


def linked_story(project: Mapping[str, Any] | None) -> str | None:
    """The story project a film project adapts, if it names one."""
    if project_kind(project) != "film" or not isinstance(project, Mapping):
        return None
    value = project.get(STORY_LINK_FIELD)
    return value if isinstance(value, str) and value else None


__all__ = ["KIND_FIELD", "STORY_LINK_FIELD", "ProjectKind", "linked_story", "project_kind"]
