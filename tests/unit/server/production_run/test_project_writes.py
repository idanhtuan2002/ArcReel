"""A run-owned write under a live run never moves the inputs the run pinned (the trial 7 lesson)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from lib.project_manager import ProjectManager
from server.production_run.owner_support import OwnerBlocked
from server.production_run.project_writes import update_run_project

ROOT = Path(__file__).resolve().parents[4]


def _projects(tmp_path: Path) -> ProjectManager:
    projects = ProjectManager(tmp_path / "projects")
    projects.create_project("demo")
    projects.create_project_metadata("demo", "Demo", "", "drama")
    projects.update_project("demo", lambda p: p.update(characters={"Hòa": {"description": "cô gái"}}))
    (projects.get_project_path("demo") / "source" / "story.txt").write_text("Hòa gọi đò.", encoding="utf-8")
    return projects


def test_a_write_outside_the_pinned_inputs_is_made(tmp_path: Path):
    projects = _projects(tmp_path)

    def cast(project: dict) -> None:
        project["characters"]["Hòa"].update(tts_voice="Leda", tts_voice_route="custom-7/gemini-tts")

    update_run_project(projects, "demo", cast)
    assert projects.load_project("demo")["characters"]["Hòa"]["tts_voice"] == "Leda"


@pytest.mark.parametrize(
    "change",
    [
        {"source_language": "vi"},  # part of the workflow source revision
        {"style": "noir"},  # a witnessed setting
        {"character_speech_delivery": "tts"},  # a setting witnessed once set
    ],
)
def test_a_write_that_would_move_a_pinned_input_is_refused_and_not_made(tmp_path: Path, change):
    projects = _projects(tmp_path)
    before = projects.load_project("demo")
    with pytest.raises(OwnerBlocked) as refused:
        update_run_project(projects, "demo", lambda project: project.update(change))
    assert refused.value.reason == "RUN_WRITE_WOULD_MOVE_INPUT"
    assert projects.load_project("demo") == before


#: Direct project writes in server/production_run, each made before a run pins its inputs or by the user.
ALLOWED_DIRECT_WRITES = {
    "server/production_run/inputs.py",  # settle_source_language: at run start, before the run exists
    "server/production_run/story_adapter.py",  # HANDOFF records the story language before the inventory pins it
    "server/production_run/autopilot_batch.py",  # adopts settings for a project without a run
    "server/production_run/settings.py",  # the user's settings route
    "server/production_run/project_writes.py",  # the guarded write itself
}


def test_every_other_project_write_of_a_run_goes_through_the_guard():
    direct = {
        str(path.relative_to(ROOT))
        for path in (ROOT / "server" / "production_run").glob("*.py")
        if re.search(r"\.update_project\(|\.save_project\(", path.read_text(encoding="utf-8"))
    }
    assert direct <= ALLOWED_DIRECT_WRITES, sorted(direct - ALLOWED_DIRECT_WRITES)
