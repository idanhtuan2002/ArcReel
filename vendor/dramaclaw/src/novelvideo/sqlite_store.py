"""Seam: ``load_episode_planning_content`` copied verbatim from DramaClaw @ b299bfd ``sqlite_store.py`` (lines 111-147).

The rest of DramaClaw's SQLite store is not ported; ArcReel passes its own store object.
"""

from __future__ import annotations

from typing import Any


async def load_episode_planning_content(store: Any, episode: Any) -> str:
    """Return the current production text shared by episode-level planners.

    The persisted beat source is the most explicit user-approved input. When it
    is absent, ``load_working_content`` resolves the adapted draft before the
    imported raw episode. Detached/test stores may not expose that adapter, so
    the model fields and ``load_episode_content`` remain compatible fallbacks.
    """

    beat_source_text = str(getattr(episode, "beat_source_text", "") or "")
    if beat_source_text.strip():
        return beat_source_text

    content_store = getattr(store, "sqlite_store", None) or store
    working_loader = getattr(content_store, "load_working_content", None)
    if callable(working_loader):
        working_content = str(await working_loader(episode.number) or "")
        if working_content.strip():
            return working_content

    adapted_content = str(getattr(episode, "adapted_content", "") or "")
    if adapted_content.strip():
        return adapted_content

    raw_loader = getattr(store, "load_episode_content", None)
    if not callable(raw_loader):
        raw_loader = getattr(content_store, "load_episode_content", None)
    if callable(raw_loader):
        raw_content = str(await raw_loader(episode.number) or "")
        if raw_content.strip():
            return raw_content

    raw_content = str(getattr(episode, "raw_content", "") or "")
    if raw_content.strip():
        return raw_content

    return str(getattr(episode, "content_summary", "") or "")
