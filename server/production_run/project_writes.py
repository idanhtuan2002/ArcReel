"""Project writes a run makes while it is live, kept off the inputs the run pinned.

A run pins its inputs: the input witness digest (``inputs.WITNESSED_SETTINGS`` and the source files) and, from the
asset inventory on, the workflow's source revision (source files, ``source_kind``, ``source_language``). A run-owned
write that moved either would make the run's own receipts stale and send it back through earlier stages. Such a
write is refused before anything is written, with ``RUN_WRITE_WOULD_MOVE_INPUT``.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from lib.project_manager import ProjectManager
from lib.source_revision import SourceScope, compute_source_revision
from server.production_run.inputs import LATER_WITNESSED_SETTINGS, WITNESSED_SETTINGS
from server.production_run.owner_support import OwnerBlocked

REFUSED = "RUN_WRITE_WOULD_MOVE_INPUT"


def pinned_inputs(project: Mapping[str, Any], project_path: Path) -> dict[str, Any]:
    """The project inputs a live run pinned, as values comparable before and after a write."""
    revision = compute_source_revision(project_path, dict(project), SourceScope(kind="all"))
    return {
        "source_revision": revision.revision,
        "settings": {key: project.get(key) for key in (*WITNESSED_SETTINGS, *LATER_WITNESSED_SETTINGS)},
    }


def update_run_project(projects: ProjectManager, project_name: str, mutate: Callable[[dict[str, Any]], None]) -> None:
    """Apply ``mutate`` to the project under its lock, unless it would move a pinned input: then nothing is written
    and :class:`OwnerBlocked` (``RUN_WRITE_WOULD_MOVE_INPUT``) is raised."""
    project_path = projects.get_project_path(project_name)

    def guarded(current: dict[str, Any]) -> None:
        trial = copy.deepcopy(current)
        mutate(trial)
        if pinned_inputs(trial, project_path) != pinned_inputs(current, project_path):
            raise OwnerBlocked(REFUSED)
        mutate(current)

    projects.update_project(project_name, guarded)


__all__ = ["REFUSED", "pinned_inputs", "update_run_project"]
