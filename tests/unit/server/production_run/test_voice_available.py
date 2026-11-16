"""A run needs a voice: the narrator's for a narration film, the audio route for a drama voiced by TTS (ADR-0166)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from lib.project_manager import ProjectManager
from server.production_run.composition import ProjectPolicyResolver


class _Resolver:
    def __init__(self, voice: str) -> None:
        self.voice = voice

    async def resolve_narration_voice(self, project):
        return self.voice


def _project(tmp_path: Path, mode: str, *, audio: bool = True, **extra) -> ProjectManager:
    projects = ProjectManager(tmp_path / "projects")
    projects.create_project("demo")
    projects.create_project_metadata("demo", "Demo", "", mode)
    routes = [{"role": "audio", "provider_id": "custom-2", "model_id": "vieneu-tts-v3-turbo"}] if audio else []
    projects.update_project("demo", lambda project: project.update(automation={"routes": routes}, **extra))
    return projects


@pytest.mark.parametrize(
    ("mode", "extra", "audio", "voice", "expected"),
    [
        ("narration", {}, True, "Ngọc", True),
        ("narration", {}, True, "", False),
        ("drama", {}, True, "Ngọc", False),
        ("drama", {"character_speech_delivery": "tts"}, True, "", True),
        ("drama", {"character_speech_delivery": "tts"}, False, "Ngọc", False),
    ],
)
async def test_the_voice_a_run_needs(tmp_path: Path, mode, extra, audio, voice, expected):
    projects = _project(tmp_path, mode, audio=audio, **extra)
    policies = ProjectPolicyResolver(None, projects=projects, resolver=_Resolver(voice))
    assert await policies.voice_available("demo") is expected


class _Lanes(_Resolver):
    async def resolve_image_backend(self, project, payload, *, capability):
        model = "flux2-klein-4b-ref-gguf" if capability == "i2i" else "flux2-klein-4b-gguf"
        return SimpleNamespace(provider_id="custom-3", model_id=model)

    async def resolve_video_backend(self, project, payload, *, capability=None):
        raise ValueError("no video model with that capability")

    async def resolve_audio_backend(self, project, payload):
        return SimpleNamespace(provider_id="custom-2", model_id="vieneu-tts-v3-turbo")


async def test_the_media_lanes_are_what_the_projects_settings_resolve_to(tmp_path: Path):
    projects = _project(tmp_path, "narration")
    policies = ProjectPolicyResolver(None, projects=projects, resolver=_Lanes("Ngọc"))
    assert await policies.media_lanes("demo") == {
        "image_t2i": ("custom-3", "flux2-klein-4b-gguf"),
        "image_i2i": ("custom-3", "flux2-klein-4b-ref-gguf"),
        "audio": ("custom-2", "vieneu-tts-v3-turbo"),
    }  # an unresolvable lane is left out, and the preflight names it
