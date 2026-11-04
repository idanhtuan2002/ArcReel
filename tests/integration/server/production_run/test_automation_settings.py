"""Project automation settings edited from the UI: model per role, cost ceilings, kept registered identities."""

from __future__ import annotations

import copy

import pytest

from lib.db.repositories.custom_provider_repo import CustomProviderRepository
from server.production_run.settings import SettingsRefused, SettingsUpdate, save_settings, settings_options

TEXT = ("qwen3.5-vimax:9b", "qwen2.5vl:7b", "gemma3:4b")


class Projects:
    def __init__(self, automation: dict | None) -> None:
        self.project: dict = {"content_mode": "narration"}
        if automation is not None:
            self.project["automation"] = automation

    def load_project(self, name: str) -> dict:
        return copy.deepcopy(self.project)

    def update_project(self, name: str, mutate) -> None:
        mutate(self.project)


async def _providers(sessions) -> None:
    async with sessions() as session, session.begin():
        repository = CustomProviderRepository(session)
        await repository.create_provider(
            "Ollama local",
            "openai",
            "http://127.0.0.1:11434",
            "",
            [{"model_id": m, "display_name": m, "endpoint": "ollama-chat"} for m in TEXT],
        )
        await repository.create_provider(
            "Gemini",
            "google",
            "https://generativelanguage.googleapis.com",
            "key",
            [{"model_id": "gemini-3.6-flash", "display_name": "3.6 Flash", "endpoint": "gemini-generate"}],
        )
        await repository.create_provider(
            "Images",
            "openai",
            "http://127.0.0.1:9000/v1",
            "",
            [
                {"model_id": "img", "display_name": "img", "endpoint": "openai-images"},
                {"model_id": "vid", "display_name": "vid", "endpoint": "openai-video"},
                {"model_id": "tts", "display_name": "tts", "endpoint": "openai-tts"},
            ],
        )


def _update(**reviewer_b) -> SettingsUpdate:
    routes = [
        {"role": "writer", "provider_id": "custom-1", "model_id": TEXT[0]},
        {"role": "script", "provider_id": "custom-1", "model_id": TEXT[0]},
        {"role": "reviewer_a", "provider_id": "custom-1", "model_id": TEXT[1]},
        {"role": "reviewer_b", "provider_id": "custom-1", "model_id": TEXT[2], **reviewer_b},
        {"role": "image", "provider_id": "custom-3", "model_id": "img"},
        {"role": "video", "provider_id": "custom-3", "model_id": "vid"},
        {"role": "audio", "provider_id": "custom-3", "model_id": "tts"},
    ]
    return SettingsUpdate.model_validate(
        {"launch_profile_id": "fiction_narration_vi_v1", "routes": routes, "max_target_episodes": 2}
    )


async def test_options_list_enabled_models_per_role_and_mark_local_ones(session_factory):
    await _providers(session_factory)

    options = await settings_options(session_factory, Projects(None), "p", user_id="default")

    writers = {(o["model_id"], o["local"]) for o in options["options"]["writer"]}
    assert writers == {(m, True) for m in TEXT} | {("gemini-3.6-flash", False)}
    assert [o["model_id"] for o in options["options"]["video"]] == ["vid"]
    assert "fiction_narration_vi_v1" in options["launch_profiles"]
    assert options["settings"]["configured"] is False


async def test_a_saved_edit_keeps_governance_fields_and_registered_identities(session_factory):
    await _providers(session_factory)
    pinned = "ollama/qwen2.5vl:7b@sha256:" + "5" * 64
    projects = Projects(
        {
            "profile_id": "profile",
            "profile_digest": "sha256:" + "a" * 64,
            "voice_available": True,
            "routes": [
                {"role": "reviewer_a", "provider_id": "custom-1", "model_id": TEXT[1], "model_identity": pinned}
            ],
        }
    )
    looked_up: list[str] = []

    async def digest(base_url: str, model_id: str) -> str:
        looked_up.append(model_id)
        return f"ollama/{model_id}@sha256:" + "9" * 64

    saved = await save_settings(session_factory, projects, "p", _update(), user_id="default", identify_ollama=digest)

    stored = projects.project["automation"]
    identities = {route["role"]: route["model_identity"] for route in stored["routes"]}
    assert identities["reviewer_a"] == pinned
    assert identities["image"] == "openai/img"
    assert sorted(looked_up) == sorted([TEXT[0], TEXT[0], TEXT[2]])
    assert (stored["profile_id"], stored["voice_available"], stored["local_only"], stored["paid"]) == (
        "profile",
        True,
        True,
        False,
    )
    assert stored["max_target_episodes"] == 2
    assert saved["has_quality_profile"] is True


async def test_a_cloud_model_needs_a_per_call_ceiling_and_is_marked_paid(session_factory):
    await _providers(session_factory)

    async def digest(base_url: str, model_id: str) -> str:
        return f"ollama/{model_id}@sha256:" + "9" * 64

    projects = Projects({})
    cloud = {"provider_id": "custom-2", "model_id": "gemini-3.6-flash"}

    with pytest.raises(SettingsRefused, match="UNBOUNDED_PAID_ROUTE"):
        await save_settings(session_factory, projects, "p", _update(**cloud), user_id="default", identify_ollama=digest)
    await save_settings(
        session_factory, projects, "p", _update(**cloud, max_cost_per_call=5), user_id="default", identify_ollama=digest
    )

    reviewer = next(r for r in projects.project["automation"]["routes"] if r["role"] == "reviewer_b")
    assert (reviewer["model_identity"], reviewer["paid"], reviewer["max_cost_per_call"]) == (
        "gemini/gemini-3.6-flash",
        True,
        5,
    )
    assert projects.project["automation"]["local_only"] is False


async def test_a_model_of_another_media_type_or_a_missing_role_is_refused(session_factory):
    await _providers(session_factory)
    wrong = _update()
    wrong.routes[4] = wrong.routes[4].model_copy(update={"model_id": "vid"})
    missing = _update()
    missing.routes[6] = missing.routes[6].model_copy(update={"role": "image"})

    with pytest.raises(SettingsRefused, match="PINNED_MODEL_UNAVAILABLE"):
        await save_settings(session_factory, Projects({}), "p", wrong, user_id="default")
    with pytest.raises(SettingsRefused, match="MISSING_MODEL_ROLE"):
        await save_settings(session_factory, Projects({}), "p", missing, user_id="default")


async def test_an_unpublished_quality_profile_is_refused(session_factory):
    await _providers(session_factory)
    update = _update().model_copy(update={"profile_id": "never-published"})

    with pytest.raises(SettingsRefused, match="MISSING_PUBLISHED_PROFILE"):
        await save_settings(session_factory, Projects({}), "p", update, user_id="default")
