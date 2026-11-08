"""The host preflight reader derives the voice and the resource envelope from the project and its launch profile."""

from __future__ import annotations

from pathlib import Path

import pytest

from server.production_run.composition import HostPreflightReader, ProjectPolicyResolver
from tests.integration.lib.db.repositories.test_production_runs import policy

AUDIO = {"role": "audio", "provider_id": "custom-2", "model_id": "vieneu-tts-v3-turbo"}


class Projects:
    def __init__(self, project: dict, root: Path) -> None:
        self.project, self.projects_root = project, root

    def load_project(self, name: str) -> dict:
        return self.project


class Voices:
    def __init__(self, voice: str) -> None:
        self.voice = voice

    async def resolve_narration_voice(self, project: dict | None) -> str:
        return self.voice


class Policies(ProjectPolicyResolver):
    async def routes(self, project_name: str):
        return ()


class Witness:
    async def digest(self, *, user_id: str, project_name: str) -> str:
        return "sha256:" + "c" * 64


async def _read(session_factory, tmp_path: Path, *, mode: str = "narration", routes=(AUDIO,), voice: str = "nova"):
    projects = Projects(
        {
            "content_mode": mode,
            "generation_mode": "storyboard",
            "automation": {"launch_profile_id": "fiction_narration_vi_v1", "routes": list(routes)},
        },
        tmp_path,
    )
    reader = HostPreflightReader(
        session_factory,
        projects=projects,
        policies=Policies(session_factory, projects=projects, resolver=Voices(voice)),
        witness=Witness(),
        profile_reader=_no_profile,
        gpu_free_bytes=lambda: 8 * 1024**3,
    )
    return await reader.read(user_id="default", project_name="p", policy=policy())


async def _no_profile(user_id: str, project_name: str, profile_id: str):
    return None


async def test_settings_saved_from_the_panel_carry_a_voice_and_the_launch_profile_envelope(session_factory, tmp_path):
    snapshot = await _read(session_factory, tmp_path)

    assert snapshot.voice_available is True
    assert (snapshot.required_disk_bytes, snapshot.required_gpu_bytes) == (8 * 1024**3, 7 * 1024**3)


@pytest.mark.parametrize(
    "case",
    [
        {"mode": "drama"},
        {"routes": ()},
        {"voice": "  "},
    ],
    ids=["drama-needs-character-voices", "no-audio-route", "no-narration-voice"],
)
async def test_without_a_narration_voice_the_voice_is_missing(session_factory, tmp_path, case):
    snapshot = await _read(session_factory, tmp_path, **case)

    assert snapshot.voice_available is False
