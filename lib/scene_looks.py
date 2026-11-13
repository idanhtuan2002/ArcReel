"""Scene looks: one time of day, key light, palette and mood shared by every shot of a scene.

A scene runs from a script-plan entry marked ``segment_break`` (or the episode's first entry) to the entry before the
next break; its look is keyed by its first entry's id. Prompt authoring writes the look of every scene it rewrites
the start of; a scene whose start is kept keeps the look its shots already carry. The look is copied into each
shot's ``image_prompt.look``, so every storyboard of the scene is generated under the same light and colour.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def scene_starts(plan_entries: Sequence[Mapping[str, Any]], *, id_field: str = "segment_id") -> dict[str, str]:
    """Each entry id → the id of the first entry of its scene, in plan order."""
    starts: dict[str, str] = {}
    current: str | None = None
    for entry in plan_entries:
        entry_id = str(entry[id_field])
        if current is None or entry.get("segment_break") is True:
            current = entry_id
        starts[entry_id] = current
    return starts


def kept_look(entry: object) -> dict[str, Any] | None:
    """The look an existing script entry carries, if any."""
    prompt = entry.get("image_prompt") if isinstance(entry, Mapping) else None
    look = prompt.get("look") if isinstance(prompt, Mapping) else None
    return dict(look) if isinstance(look, Mapping) else None


def looks_to_write(
    starts: Mapping[str, str], rewritten: Sequence[str], existing_start_looks: Mapping[str, Mapping[str, Any]]
) -> list[str]:
    """Scene starts whose look this authoring writes: a rewritten scene start, or a scene with rewritten shots whose
    kept start has no look yet."""
    rewritten_set = set(rewritten)
    needed: list[str] = []
    for entry_id in rewritten:
        start = starts[entry_id]
        if start in needed:
            continue
        if start in rewritten_set or start not in existing_start_looks:
            needed.append(start)
    return needed


def apply_looks(
    segments: list[dict[str, Any]],
    starts: Mapping[str, str],
    written: Mapping[str, Mapping[str, Any]],
    kept: Mapping[str, Mapping[str, Any]],
    *,
    id_field: str = "segment_id",
) -> None:
    """Copy each segment's scene look (written now, else kept) into its ``image_prompt.look``."""
    for segment in segments:
        start = starts.get(str(segment[id_field]))
        look = written.get(start) if start is not None else None
        if look is None and start is not None:
            look = kept.get(start)
        prompt = segment.get("image_prompt")
        if look is not None and isinstance(prompt, dict):
            prompt["look"] = dict(look)


__all__ = ["apply_looks", "kept_look", "looks_to_write", "scene_starts"]
