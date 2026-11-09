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


async def test_a_handed_off_story_in_decomposed_unicode_still_counts_as_unchanged(tmp_path: Path):
    import unicodedata

    from server.story_authoring.artifacts import StoryBlobStore

    projects = ProjectManager(tmp_path / "projects")
    projects.create_project("demo")
    projects.create_project_metadata("demo", "Demo", "", "narration")
    path = projects.get_project_path("demo")
    export = "# Căn nhà cũ\n\nMinh về làng thăm mẹ."
    digest = StoryBlobStore(path).put(export.encode("utf-8"))
    source = path / "source" / "can-nha-cu.txt"
    source.write_text(unicodedata.normalize("NFD", "Căn nhà cũ\n\nMinh về làng thăm mẹ.\n"), encoding="utf-8")
    witness = ProjectInputWitness(None, projects=projects)
    handed = frozenset({("source/can-nha-cu.txt", digest)})
    with_unchanged_file = witness._digest("demo", handed)
    source.unlink()
    assert witness._digest("demo", handed) == with_unchanged_file  # the unchanged hand-off never counted
    source.write_text("Căn nhà cũ\n\nMinh bỏ làng đi.\n", encoding="utf-8")
    assert witness._digest("demo", handed) != with_unchanged_file  # an edit does
