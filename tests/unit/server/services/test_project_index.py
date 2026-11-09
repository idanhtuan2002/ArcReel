"""The project index pages thousands of projects and recomputes only changed rows (ADR-0122)."""

from __future__ import annotations

import os
from pathlib import Path

from server.routers.operations import _lane_of_run, _lane_of_story
from server.services.project_index import ProjectIndex, page_of


class _Manager:
    def __init__(self, root: Path, names: list[str]) -> None:
        self.root = root
        self.names = names
        for name in names:
            (root / name).mkdir(parents=True, exist_ok=True)
            (root / name / "project.json").write_text("{}", encoding="utf-8")

    def list_projects(self) -> list[str]:
        return list(self.names)

    def get_project_path(self, name: str) -> Path:
        return self.root / name


def _row(name: str, *, kind: str = "film", title: str = "", phase: str = "", story: str | None = None) -> dict:
    return {
        "name": name,
        "title": title or name,
        "project_kind": kind,
        "story_project": story,
        "status": {"phase": phase},
    }


def test_a_row_is_recomputed_only_when_its_files_change(tmp_path):
    manager = _Manager(tmp_path, ["a", "b"])
    computed: list[str] = []

    def compute(name: str) -> dict:
        computed.append(name)
        return _row(name)

    index = ProjectIndex()
    first = index.rows(manager, compute)
    index.rows(manager, compute)
    assert computed == ["a", "b"]
    assert all(row["updated_at"] for row in first)

    stamp = (tmp_path / "b" / "project.json").stat().st_mtime_ns + 10_000_000
    os.utime(tmp_path / "b" / "project.json", ns=(stamp, stamp))
    index.rows(manager, compute)
    assert computed == ["a", "b", "b"]

    manager.names = ["a"]
    assert [row["name"] for row in index.rows(manager, compute)] == ["a"]


def test_a_page_is_searched_filtered_sorted_counted_and_carries_film_counts():
    rows = [
        {**_row("s1", kind="story", title="Bến đò"), "updated_at": "2026-11-01"},
        {**_row("f1", title="Bến đò — phim", story="s1", phase="production"), "updated_at": "2026-11-03"},
        {**_row("f2", title="Chợ đêm", phase="production"), "updated_at": "2026-11-02"},
        {**_row("s2", kind="story", title="Gió lạnh"), "updated_at": "2026-11-04"},
    ]

    everything = page_of(rows, q=None, kind="all", stage=None, sort="updated", offset=0, limit=10)
    assert [r["name"] for r in everything["items"]] == ["s2", "f1", "f2", "s1"]
    assert everything["counts"] == {"all": 4, "story": 2, "film": 2}

    stories = page_of(rows, q=None, kind="story", stage=None, sort="title", offset=0, limit=10)
    assert [(r["name"], r["films"]) for r in stories["items"]] == [("s1", 1), ("s2", 0)]

    search = page_of(rows, q="BẾN", kind="all", stage=None, sort="updated", offset=0, limit=10)
    assert [r["name"] for r in search["items"]] == ["f1", "s1"]

    staged = page_of(rows, q=None, kind="film", stage="production", sort="updated", offset=1, limit=1)
    assert (staged["total"], [r["name"] for r in staged["items"]]) == (2, ["f2"])


def test_runs_fall_into_the_operators_lanes():
    assert _lane_of_story("READY_FOR_APPROVAL") == "decision"
    assert _lane_of_story("BLOCKED_QUALITY") == "blocked"
    assert _lane_of_story("RUNNING") == "running"
    assert _lane_of_story("COMMITTED") is None
    assert _lane_of_run("WAITING_REVIEW") == "decision"
    assert _lane_of_run("BLOCKED_BUDGET") == "blocked"
    assert _lane_of_run("PAUSED") == "blocked"
    assert _lane_of_run("RUNNING") == "running"
    assert _lane_of_run("SUCCEEDED") is None
