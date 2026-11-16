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
