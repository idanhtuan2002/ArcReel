"""MEDIA casts the voices of a drama voiced by TTS before its speech is made, and records them guarded (ADR-0166)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from lib.project_manager import ProjectManager
from server.production_run import media_adapter
from server.production_run.media_adapter import MediaAdapter
from server.production_run.owner_support import OwnerBlocked
from server.production_run.project_writes import pinned_inputs

ROUTE = "custom-7/gemini-3.8-flash-tts"


class _Resolver:
    async def resolve_audio_backend(self, project, payload):
        return SimpleNamespace(provider_id="custom-7", model_id="gemini-3.8-flash-tts")


class _Tasks:
    def __init__(self) -> None:
        self.by_key: dict[str, dict] = {}
        self.submitted: list[dict] = []

    async def find(self, sessions, intent, key):
        return self.by_key.get(key)

    async def submit(self, sessions, authority, intent, *, sub_key, task_type, resource_id, payload, subject_digest):
        self.submitted.append({"key": sub_key, "type": task_type, "payload": payload})
        self.by_key[sub_key] = {"status": "queued"}


@pytest.fixture
def drama_media(tmp_path: Path, monkeypatch):
    projects = ProjectManager(tmp_path / "projects")
    projects.create_project("demo")
    projects.create_project_metadata("demo", "Demo", "", "drama")
    projects.update_project(
        "demo",
        lambda p: p.update(character_speech_delivery="tts", characters={"Hòa": {"description": "cô gái"}}),
    )
    (projects.get_project_path("demo") / "source" / "story.txt").write_text("Hòa gọi đò.", encoding="utf-8")
    script = {
        "episode": 1,
        "content_mode": "drama",
        "scenes": [{"scene_id": "E1S01", "utterances": [{"kind": "dialogue", "speaker": "Hòa", "text": "Bác ơi!"}]}],
    }
    scripts = projects.get_project_path("demo") / "scripts"
    scripts.mkdir(exist_ok=True)
    (scripts / "episode_1.json").write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
    tasks = _Tasks()
    monkeypatch.setattr(media_adapter, "find_task", tasks.find)
    monkeypatch.setattr(media_adapter, "submit_task", tasks.submit)
    adapter = object.__new__(MediaAdapter)
    adapter._projects, adapter._resolver, adapter._sessions, adapter._authority = projects, _Resolver(), None, None
    plan = SimpleNamespace(status=SimpleNamespace(target=SimpleNamespace(script_filename="episode_1.json")))
    intent = SimpleNamespace(scope=SimpleNamespace(project_name="demo"))
    return projects, tasks, adapter, plan, intent


async def test_a_speaker_without_a_voice_is_cast_then_recorded_without_moving_the_pinned_inputs(drama_media):
    projects, tasks, adapter, plan, intent = drama_media
    path = projects.get_project_path("demo")
    pinned = pinned_inputs(projects.load_project("demo"), path)

    assert await adapter._cast_voices(intent, "sha256:" + "1" * 64, plan) is True
    [sent] = tasks.submitted
    assert (sent["type"], sent["payload"]["route"]) == ("text_voice_cast", ROUTE)
    assert [s["name"] for s in sent["payload"]["speakers"]] == ["Hòa"]
    assert await adapter._cast_voices(intent, "d", plan) is True  # still running

    tasks.by_key[sent["key"]] = {"status": "succeeded", "result": {"route": ROUTE, "voices": {"Hòa": "Kore"}}}
    assert await adapter._cast_voices(intent, "d", plan) is True
    character = projects.load_project("demo")["characters"]["Hòa"]
    assert (character["tts_voice"], character["tts_voice_route"]) == ("Kore", ROUTE)
    assert pinned_inputs(projects.load_project("demo"), path) == pinned
    assert await adapter._cast_voices(intent, "d", plan) is False  # every speaker has a voice now


async def test_a_project_whose_video_model_speaks_casts_nothing(drama_media):
    projects, tasks, adapter, plan, intent = drama_media
    projects.update_project("demo", lambda p: p.update(character_speech_delivery="video"))
    assert await adapter._cast_voices(intent, "d", plan) is False
    assert tasks.submitted == []


async def test_spent_cast_attempts_block_the_step(drama_media):
    _projects, tasks, adapter, plan, intent = drama_media
    assert await adapter._cast_voices(intent, "d", plan) is True
    key = tasks.submitted[0]["key"]
    for attempt in (key, f"{key}#attempt-2", f"{key}#attempt-3"):
        tasks.by_key[attempt] = {"status": "failed"}
    with pytest.raises(OwnerBlocked) as blocked:
        await adapter._cast_voices(intent, "d", plan)
    assert blocked.value.reason == "VOICE_CAST_FAILED"


@pytest.mark.parametrize(("script_state", "complete"), [("current", True), ("stale", True), ("missing", False)])
def test_an_episode_whose_media_are_current_is_complete_even_if_assets_moved_its_script(script_state, complete):
    collection = {"current_ids": ["E1S01"], "missing_ids": [], "stale_ids": []}
    artifacts = {
        "script": {"state": script_state},
        "storyboards": collection,
        "videos": collection,
        "audio": collection,
    }
    plan = SimpleNamespace(status=SimpleNamespace(artifacts=artifacts))
    assert MediaAdapter._episode_media_current(plan) is complete


@pytest.mark.parametrize(
    ("storyboards", "videos", "complete"),
    [
        ({"missing_ids": [], "stale_ids": ["E1S05"]}, {"missing_ids": [], "stale_ids": []}, True),
        ({"missing_ids": ["E1S05"], "stale_ids": []}, {"missing_ids": [], "stale_ids": []}, False),
        ({"missing_ids": [], "stale_ids": []}, {"missing_ids": [], "stale_ids": ["E1S05"]}, False),
    ],
)
def test_a_storyboard_its_neighbours_selection_moved_does_not_hold_back_an_episode_whose_videos_are_current(
    storyboards, videos, complete
):
    current = {"current_ids": ["E1S01"]}
    artifacts = {
        "script": {"state": "current"},
        "storyboards": {**current, **storyboards},
        "videos": {**current, **videos},
        "audio": {**current, "missing_ids": [], "stale_ids": []},
    }
    plan = SimpleNamespace(status=SimpleNamespace(artifacts=artifacts))
    assert MediaAdapter._episode_media_current(plan) is complete


async def test_videos_made_stale_by_new_storyboards_are_made_again_once_the_workflow_has_nothing_left(drama_media):
    _projects, _tasks, adapter, _plan, intent = drama_media
    sent: list[tuple] = []

    async def send(intent, subject_digest, sub_keys, action, args, limit_reason):
        sent.append((sub_keys, action, args, limit_reason))

    adapter._send = send
    collection = {"current_ids": ["E1S01"], "missing_ids": [], "stale_ids": []}

    def plan_with(videos, storyboards=collection):
        artifacts = {"storyboards": storyboards, "videos": videos, "audio": collection}
        return SimpleNamespace(
            status=SimpleNamespace(artifacts=artifacts, target=SimpleNamespace(script_filename="episode_1.json"))
        )

    stale = {"current_ids": [], "missing_ids": [], "stale_ids": ["E1S02", "E1S01"]}
    assert await adapter._refresh_stale_videos(intent, "d", plan_with(stale)) is True
    [(sub_keys, action, args, reason)] = sent
    assert sub_keys == ["stale:videos:E1S01", "stale:videos:E1S02"]
    assert (action.value, reason) == ("generate_videos", "MEDIA_RETRY_LIMIT")
    assert args["target"] == {"scope": "selected", "ids": ["E1S01", "E1S02"]}
    assert args["force"] is True

    assert await adapter._refresh_stale_videos(intent, "d", plan_with(collection)) is False
    missing_board = {**collection, "missing_ids": ["E1S03"]}
    assert await adapter._refresh_stale_videos(intent, "d", plan_with(stale, missing_board)) is False


def test_a_unit_whose_kept_choice_is_still_current_is_not_selected_again(tmp_path: Path):
    root = tmp_path
    run_dir = root / "production" / "automation" / "run-1"
    for generation, segments in (
        ("g4", {"E1S01": {"chosen_version": 1, "kept_version": 3}, "E1S02": {"chosen_version": 2}}),
        ("g5", {"E1S03": {"chosen_version": 1, "kept_version": 2}}),
    ):
        path = run_dir / generation / "episode_1" / "image_selection.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"segments": segments}), encoding="utf-8")
    current = {"E1S01": 3, "E1S02": 2, "E1S03": 5, "E1S04": 1}
    kept = MediaAdapter._kept_units(root, "run-1", 1, current)
    # E1S02 recorded no kept version; E1S03 was drawn again since its choice; E1S04 was never chosen.
    assert kept == {"E1S01"}


def test_a_tool_call_that_queued_nothing_and_refused_units_names_their_problem():
    from lib.generation_result import (
        GenerationAction,
        GenerationBatchResult,
        GenerationItemResult,
        GenerationItemState,
        GenerationProblem,
        GenerationSelectionMode,
    )
    from server.tool_runtime import ToolOutcome

    problem = GenerationProblem(code="video_shorter_than_tts", detail="x", action=GenerationAction.REGENERATE_TTS)
    refused = GenerationBatchResult(
        operation="generate_videos",
        selection=GenerationSelectionMode.EXPLICIT,
        requested=["E1S01"],
        succeeded=[],
        failed=[],
        blocked=["E1S01"],
        items=[GenerationItemResult(unit_id="E1S01", state=GenerationItemState.BLOCKED, problem=problem)],
    )
    assert MediaAdapter._refusal_reason(ToolOutcome(value={"generation_result": refused})) == (
        "MEDIA_VIDEO_SHORTER_THAN_TTS"
    )
    assert MediaAdapter._refusal_reason(ToolOutcome(value={"summary": "queued"})) is None
