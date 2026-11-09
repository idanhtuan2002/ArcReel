"""The project library as an index that holds thousands of projects (ADR-0122).

A project's list row (title, cover, project-level status) costs a load of the project and its scripts. The index
keeps each row with a signature of the files it was computed from (``project.json``, the source, script,
storyboard and video folders) and recomputes a row only when its signature changes or the row is older than
``TTL_SECONDS``, so a page of the library stays cheap however many projects exist. Pages are filtered by kind,
stage and a text query, sorted, and counted per kind.
"""

from __future__ import annotations

import threading
import time
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TTL_SECONDS = 300
WATCHED = ("project.json", "source", "scripts", "storyboards", "videos", "adaptations")

type Signature = tuple[tuple[str, int], ...]


def signature(project_dir: Path) -> Signature:
    """Modification times of the files and folders a row is computed from."""
    marks: list[tuple[str, int]] = []
    for name in WATCHED:
        try:
            marks.append((name, (project_dir / name).stat().st_mtime_ns))
        except OSError:
            marks.append((name, 0))
    return tuple(marks)


class ProjectIndex:
    def __init__(self, ttl: float = TTL_SECONDS) -> None:
        self._ttl = ttl
        self._rows: dict[str, tuple[Signature, float, dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def rows(self, manager: Any, compute: Callable[[str], dict[str, Any]]) -> list[dict[str, Any]]:
        names = manager.list_projects()
        now = time.monotonic()
        out: list[dict[str, Any]] = []
        for name in names:
            try:
                sig = signature(Path(manager.get_project_path(name)))
            except (OSError, ValueError):
                sig = ()  # a folder that vanished or is not a valid project: its row is recomputed every time
            with self._lock:
                cached = self._rows.get(name)
            if cached is not None and cached[0] == sig and now - cached[1] < self._ttl:
                out.append(cached[2])
                continue
            row = dict(compute(name))
            stamp = max((mark for _, mark in sig), default=0)
            row["updated_at"] = datetime.fromtimestamp(stamp / 1e9, UTC).isoformat() if stamp else None
            with self._lock:
                self._rows[name] = (sig, now, row)
            out.append(row)
        with self._lock:
            for gone in set(self._rows) - set(names):
                del self._rows[gone]
        return out


PROJECT_INDEX = ProjectIndex()


def _fold(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


def _stage(row: dict[str, Any]) -> str:
    status = row.get("status") or {}
    phase = status.get("phase") if isinstance(status, dict) else None
    return phase if isinstance(phase, str) else ""


def page_of(
    rows: list[dict[str, Any]],
    *,
    q: str | None,
    kind: str,
    stage: str | None,
    sort: str,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    """One page of rows, with the counts per kind of the rows the query and stage match. A story row carries the
    number of film projects that adapt it."""
    films_of: dict[str, int] = {}
    for row in rows:
        linked = row.get("story_project")
        if isinstance(linked, str) and linked:
            films_of[linked] = films_of.get(linked, 0) + 1
    needle = _fold(q.strip()) if q and q.strip() else ""
    matched = [
        row
        for row in rows
        if (not needle or needle in _fold(f"{row.get('title') or ''} {row.get('name') or ''}"))
        and (not stage or _stage(row) == stage)
    ]
    counts = {
        "all": len(matched),
        "story": sum(1 for row in matched if row.get("project_kind") == "story"),
        "film": sum(1 for row in matched if row.get("project_kind") != "story"),
    }
    if kind != "all":
        matched = [row for row in matched if (row.get("project_kind") == "story") == (kind == "story")]
    if sort == "title":
        matched.sort(key=lambda row: _fold(row.get("title") or row.get("name") or ""))
    elif sort == "stage":
        matched.sort(key=lambda row: (_stage(row), _fold(row.get("title") or "")))
    else:
        matched.sort(key=lambda row: row.get("updated_at") or "", reverse=True)
    items = [
        {**row, "films": films_of.get(str(row.get("name")), 0)} if row.get("project_kind") == "story" else row
        for row in matched[offset : offset + limit]
    ]
    return {"total": len(matched), "counts": counts, "offset": offset, "limit": limit, "items": items}


__all__ = ["PROJECT_INDEX", "ProjectIndex", "page_of", "signature"]
