"""ScriptAdapter settles narration mixed speech through the script edit tool before pinning the script."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace

from lib.config.resolver import ConfigResolver
from lib.project_manager import ProjectManager
from server.production_run.text_adapter import ScriptAdapter
from server.services.workflow_planner import WorkflowPlanner
from server.tool_runtime import CallerContext, CreateProjectToolRequest, Services, ToolRequest, create_project

LINE = "Cha ơi, con biết mình đã sai,"
SEGMENT = {
    "segment_id": "E1S01",
    "novel_text": f'Nam đọc lá thư. "{LINE}" Nam thì thầm.',
    "duration_seconds": 2,
    "segment_break": False,
    "characters_in_segment": ["Nam"],
    "scenes": [],
    "props": [],
    "image_prompt": {
        "scene": "Nam đọc lá thư trên bãi biển.",
        "composition": {"shot_type": "Close-up", "lighting": "nắng", "ambiance": "gió biển"},
    },
    "video_prompt": {
        "action": "Nam thì thầm.",
        "camera_motion": "Static",
        "ambiance_audio": "",
        "dialogue": [{"speaker": "Nam", "line": LINE}],
    },
    "needs_replan": True,
}


async def _project(tmp_path, segments: list[dict]) -> ProjectManager:
    projects = ProjectManager(tmp_path)
    created = await create_project(
        ToolRequest(
            CreateProjectToolRequest(name="project", title="t", content_mode="narration", generation_mode="storyboard")
        ),
        CallerContext(user_id="default", source="embedded"),
        Services(projects=projects, workflow_planner=WorkflowPlanner(projects), capabilities=ConfigResolver(None)),
    )
    assert created.problem is None
    projects.update_project("project", lambda project: project.update(characters={"Nam": {}}))
    script = {"title": "Tập 1", "episode": 1, "content_mode": "narration", "segments": segments}
    (projects.get_project_path("project") / "scripts" / "episode_1.json").write_text(
        json.dumps(script, ensure_ascii=False), encoding="utf-8"
    )
    return projects


def _intent():
    return SimpleNamespace(scope=SimpleNamespace(project_name="project", user_id="default"))


def _status(projects: ProjectManager, filename: str = "episode_1.json"):
    target = SimpleNamespace(script_filename=filename)
    return SimpleNamespace(project=SimpleNamespace(content_mode="narration"), target=target)


async def test_a_character_line_only_in_video_prompt_is_patched_to_the_narrator(tmp_path):
    projects = await _project(tmp_path, [copy.deepcopy(SEGMENT)])
    adapter = ScriptAdapter(None, authority=None, projects=projects, resolver=None)

    await adapter._settle(_intent(), _status(projects))

    [segment] = projects.load_script("project", "episode_1.json")["segments"]
    assert segment["video_prompt"]["dialogue"] == []
    assert not segment.get("needs_replan")
    assert segment["novel_text"] == SEGMENT["novel_text"]


async def test_a_segment_without_a_speech_problem_is_left_as_is(tmp_path):
    clean = {**copy.deepcopy(SEGMENT), "needs_replan": False}
    clean["video_prompt"]["dialogue"] = []
    projects = await _project(tmp_path, [clean])
    before = (projects.get_project_path("project") / "scripts" / "episode_1.json").read_bytes()
    adapter = ScriptAdapter(None, authority=None, projects=projects, resolver=None)

    await adapter._settle(_intent(), _status(projects))

    assert (projects.get_project_path("project") / "scripts" / "episode_1.json").read_bytes() == before


async def test_empty_prompts_are_filled_from_the_segments_own_text(tmp_path):
    empty = {**copy.deepcopy(SEGMENT), "needs_replan": False}
    empty["video_prompt"]["dialogue"] = []
    empty["video_prompt"]["action"] = " "
    empty["image_prompt"]["scene"] = ""
    projects = await _project(tmp_path, [empty])
    adapter = ScriptAdapter(None, authority=None, projects=projects, resolver=None)

    await adapter._settle(_intent(), _status(projects))

    [segment] = projects.load_script("project", "episode_1.json")["segments"]
    assert segment["image_prompt"]["scene"] == SEGMENT["novel_text"]
    assert segment["video_prompt"]["action"] == SEGMENT["novel_text"]


async def test_a_registered_character_named_in_the_text_is_added_to_the_segment(tmp_path):
    unlisted = {**copy.deepcopy(SEGMENT), "needs_replan": False, "characters_in_segment": []}
    unlisted["video_prompt"]["dialogue"] = []
    projects = await _project(tmp_path, [unlisted])
    adapter = ScriptAdapter(None, authority=None, projects=projects, resolver=None)

    await adapter._settle(_intent(), _status(projects))

    [segment] = projects.load_script("project", "episode_1.json")["segments"]
    assert segment["characters_in_segment"] == ["Nam"]
