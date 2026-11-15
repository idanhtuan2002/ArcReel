"""The voice cast task answers a voice per speaker from the audio route's catalog and never writes (ADR-0166)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from lib.audio_backends.base import VoiceOption
from lib.project_manager import ProjectManager
from lib.text_backends.base import TextGenerationResult
from server import tool_runtime
from server.services import generation_context


class _Generator:
    def __init__(self, answer: dict) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    async def generate(self, request, project_name, user_id):
        self.prompts.append(request.prompt)
        return TextGenerationResult(text=json.dumps(self.answer), provider="p", model="m")


@pytest.fixture
def cast_task_host(tmp_path: Path, monkeypatch):
    projects = ProjectManager(tmp_path / "projects")
    projects.create_project("demo")
    projects.create_project_metadata("demo", "Demo", "", "drama")
    lane = SimpleNamespace(
        provider_model=SimpleNamespace(provider_id="custom-7"),
        backend_model="gemini-3.8-flash-tts",
        voices=(VoiceOption("Charon", "Charon"), VoiceOption("Kore", "Kore"), VoiceOption("Puck", "Puck")),
        narration_voice="Charon",
    )

    async def context(*args, **kwargs):
        return SimpleNamespace(audio_lane=lane)

    async def no_gate(scope, services):
        return None

    generator = _Generator(
        {"picks": [{"character": "Hòa", "sex": "female", "age": "young", "voice": "Kore", "reason": ""}]}
    )

    async def create(*args, **kwargs):
        return generator

    monkeypatch.setattr(generation_context, "resolve_generation_context", context)
    monkeypatch.setattr(tool_runtime, "migration_gate", no_gate)
    monkeypatch.setattr(tool_runtime.TextGenerator, "create", create)
    scope = tool_runtime.ProjectScope(project_name="demo", projects_root=projects.projects_root)
    services = SimpleNamespace(projects=projects)
    return projects, scope, services, generator


def _task(route: str) -> dict:
    speakers = [{"name": "Hòa", "description": "cô gái trẻ", "lines": 3}]
    return {"task_id": "t", "user_id": "u", "payload": {"route": route, "speakers": speakers}}


async def test_each_speaker_gets_a_catalog_voice_and_the_project_is_not_written(cast_task_host):
    projects, scope, services, generator = cast_task_host
    before = projects.load_project("demo")
    result = await tool_runtime._execute_voice_cast(_task("custom-7/gemini-3.8-flash-tts"), scope, services)
    assert result == {"route": "custom-7/gemini-3.8-flash-tts", "voices": {"Hòa": "Kore"}}
    assert "Charon" not in generator.prompts[0].split("Voices")[1].split("\n- ", 1)[1]  # the narrator's voice is kept
    assert projects.load_project("demo") == before


async def test_a_moved_audio_route_fails_the_task(cast_task_host):
    _projects, scope, services, _generator = cast_task_host
    with pytest.raises(RuntimeError, match="voice_route_moved"):
        await tool_runtime._execute_voice_cast(_task("custom-2/vieneu-tts-v3-turbo"), scope, services)
