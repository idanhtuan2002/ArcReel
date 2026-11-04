from __future__ import annotations

import pytest

from r2.contracts.automation import AutomationMode, RunStage
from server.production_run import composition
from server.production_run.service import ProductionRunRefused


class Projects:
    projects_root = "/projects"

    def __init__(self, project: dict) -> None:
        self.project = project

    def load_project(self, name: str) -> dict:
        return self.project

    def get_project_path(self, name: str):
        from pathlib import Path

        return Path("/projects") / name


def test_every_stage_has_exactly_one_owner_adapter():
    adapters = composition.build_adapters(
        None, authority=None, projects=Projects({}), resolver=None, stories=None, upload_for=None, evaluator=None
    )
    assert set(adapters) == set(RunStage)
    assert len({adapter.owner for adapter in adapters.values()}) == len(RunStage)


def test_activation_stays_off_unless_the_release_gate_sets_it(monkeypatch):
    monkeypatch.delenv(composition.ACTIVATION_ENV, raising=False)
    assert composition.activation_from_env().enabled is False
    monkeypatch.setenv(composition.ACTIVATION_ENV, "true")
    assert composition.activation_from_env().enabled is False
    monkeypatch.setenv(composition.ACTIVATION_ENV, "1")
    assert composition.activation_from_env().enabled is True


async def test_a_project_without_automation_settings_resolves_no_policy():
    resolver = composition.ProjectPolicyResolver(None, projects=Projects({"content_mode": "narration"}), resolver=None)
    with pytest.raises(ProductionRunRefused, match="AUTOMATION_NOT_CONFIGURED"):
        await resolver.resolve(user_id="u", project_name="p", mode=AutomationMode.AUTO)


async def test_the_launch_profiles_quality_gate_is_frozen_into_the_policy(monkeypatch):
    settings = {"profile_id": "auto-review", "profile_digest": "sha256:" + "a" * 64}
    resolver = composition.ProjectPolicyResolver(
        None, projects=Projects({"content_mode": "narration", "automation": settings}), resolver=None
    )

    async def no_routes(project_name: str) -> tuple:
        return ()

    monkeypatch.setattr(resolver, "routes", no_routes)

    policy = await resolver.resolve(user_id="u", project_name="p", mode=AutomationMode.AUTO)

    assert policy.quality_gate == "record"


@pytest.mark.parametrize(("asked", "frozen"), [(None, 1), (3, 3), (99, composition.MAX_TARGET_EPISODES)])
async def test_the_episode_limit_comes_from_the_project_and_is_capped(monkeypatch, asked, frozen):
    settings: dict = {"profile_id": "auto-review", "profile_digest": "sha256:" + "a" * 64}
    if asked is not None:
        settings["max_target_episodes"] = asked
    resolver = composition.ProjectPolicyResolver(
        None, projects=Projects({"content_mode": "narration", "automation": settings}), resolver=None
    )

    async def no_routes(project_name: str) -> tuple:
        return ()

    monkeypatch.setattr(resolver, "routes", no_routes)

    policy = await resolver.resolve(user_id="u", project_name="p", mode=AutomationMode.AUTO)

    assert policy.max_target_episodes == frozen
