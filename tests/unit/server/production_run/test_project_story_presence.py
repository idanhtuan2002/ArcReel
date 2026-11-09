"""A run of the project's story (ADR-0115) needs story text in the project's sources."""

from __future__ import annotations

from pathlib import Path

from lib.project_manager import ProjectManager
from server.production_run.inputs import ProjectInputWitness


async def test_only_non_blank_source_text_counts_as_a_story(tmp_path: Path):
    projects = ProjectManager(tmp_path / "projects")
    projects.create_project("demo")
    projects.create_project_metadata("demo", "Demo", "", "narration")
    witness = ProjectInputWitness(None, projects=projects)
    assert await witness.has_source_text("demo") is False
    source = projects.get_project_path("demo") / "source" / "story.txt"
    source.write_text("   \n", encoding="utf-8")
    assert await witness.has_source_text("demo") is False
    source.write_text("Lan mở cửa tiệm thuốc.", encoding="utf-8")
    assert await witness.has_source_text("demo") is True
